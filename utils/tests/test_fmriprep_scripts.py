"""Tests for fMRIPrep Slurm helper scripts.

These mirror the MRIQC script tests but target:
- s7_fmriprep/run_fmriprep_bids_filter_array_all.sh
- s7_fmriprep/rerun_fmriprep_bold_create_job_array.sh
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FMRIPREP_DIR = REPO_ROOT / "s7_fmriprep"


def _setup_stub_binaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create stub `module` and `apptainer` commands on PATH for fMRIPrep tests."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    module_script = bin_dir / "module"
    module_script.write_text("""#!/usr/bin/env bash
# No-op stub for `module` used in tests.
exit 0
""")
    module_script.chmod(0o755)

    apptainer_script = bin_dir / "apptainer"
    apptainer_script.write_text(
        """#!/usr/bin/env bash
# No-op stub for `apptainer` used in tests.
exit 0
"""
    )
    apptainer_script.chmod(0o755)

    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{original_path}")


def test_run_fmriprep_exits_on_missing_required_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run_fmriprep_bids_filter_array_all_SW.sh errors when required values missing."""

    _setup_stub_binaries(tmp_path, monkeypatch)

    cfg = tmp_path / "config_missing.yaml"
    cfg.write_text(
        """
        fmriprep:
          bids_dir: ""
          output_dir: /some/output
          work_dir: /some/work
        paths:
          fmriprep_results_root: /some/results
          fmriprep_heuristics_csv: /some/heuristics.csv
        containers:
          fmriprep_image: /some/image.sif
          freesurfer_license: /some/license.txt
        """,
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            str(FMRIPREP_DIR / "run_fmriprep_bids_filter_array_all.sh"),
            "--config",
            str(cfg),
        ],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "[run_fmriprep] One or more required config values are missing or empty" in result.stderr


def test_run_fmriprep_errors_when_bids_root_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run_fmriprep_bids_filter_array_all.sh errors if BIDS root absent on disk."""

    _setup_stub_binaries(tmp_path, monkeypatch)

    bids_dir = tmp_path / "nonexistent_bids"
    csv_path = tmp_path / "heuristics.csv"
    csv_path.write_text("subid,v1\nS_1234,bl\n", encoding="utf-8")

    cfg = tmp_path / "config_bad_bids.yaml"
    cfg.write_text(
        """
        fmriprep:
          bids_dir: {bids_dir}
          output_dir: /some/output
          work_dir: /some/work
        paths:
          fmriprep_results_root: /some/results
          fmriprep_heuristics_csv: {csv_path}
        containers:
          fmriprep_image: /some/image.sif
          freesurfer_license: /some/license.txt
        """.format(bids_dir=bids_dir, csv_path=csv_path),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            str(FMRIPREP_DIR / "run_fmriprep_bids_filter_array_all.sh"),
            "--config",
            str(cfg),
        ],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "[run_fmriprep] BIDS root does not exist:" in result.stderr


def test_rerun_fmriprep_creates_rerun_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rerun_fmriprep_bold_create_job_array.sh computes a clean rerun subject list.

    We create a tiny fake BIDS + derivatives tree and an error report CSV, then
    verify the expected text files are written and contain at least one subject.
    """

    _setup_stub_binaries(tmp_path, monkeypatch)

    bids_root = tmp_path / "bids"
    deriv_root = tmp_path / "derivatives"
    results_root = tmp_path / "results"
    (bids_root / "sub-ADNI1234" / "ses-bl" / "func").mkdir(parents=True)
    (bids_root / "sub-ADNI1234" / "ses-bl" / "func" / "sub-ADNI1234_ses-bl_task-rest_bold.nii.gz").write_text("", encoding="utf-8")

    # No preproc BOLD in derivatives, so subject should qualify for rerun.
    (deriv_root).mkdir(parents=True)
    (results_root / "scripts" / "reports").mkdir(parents=True)
    report = results_root / "scripts" / "reports" / "fmriprep_error_report_ALL.csv"
    report.write_text(
        "source,file,subject,session,category,detail\n"
        "log,x,sub-ADNI1234,bl,no BOLD for subject,some detail\n",
        encoding="utf-8",
    )

    cfg = tmp_path / "config_rerun.yaml"
    cfg.write_text(
        """
        fmriprep:
          bids_dir: {bids}
          output_dir: {deriv}
        paths:
          fmriprep_results_root: {results}
        """.format(bids=bids_root, deriv=deriv_root, results=results_root),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            str(FMRIPREP_DIR / "rerun_fmriprep_bold_create_job_array.sh"),
            "--config",
            str(cfg),
        ],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    outdir = results_root / "scripts"
    affected = outdir / "subs_needing_rerun_from_report.txt"
    affected_valid = outdir / "affected_and_valid.txt"
    rerun_list = outdir / "job_array_input_RERUN_subjects.txt"

    assert affected.exists()
    assert affected_valid.exists()
    assert rerun_list.exists()

    contents = rerun_list.read_text(encoding="utf-8").strip().splitlines()
    assert "sub-ADNI1234" in contents
