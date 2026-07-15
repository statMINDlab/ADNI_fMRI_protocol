"""Tests for fMRIPrep Slurm helper scripts.

These mirror the MRIQC script tests but target:
- s7_fmriprep/run_fmriprep_bids_filter_array_all.sh
- s7_fmriprep/rerun_fmriprep_bold_create_job_array.sh
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FMRIPREP_DIR = REPO_ROOT / "s7_fmriprep"

_mbf_spec = importlib.util.spec_from_file_location(
    "make_bids_filters", FMRIPREP_DIR / "make_bids_filters.py")
mbf = importlib.util.module_from_spec(_mbf_spec)
_mbf_spec.loader.exec_module(mbf)  # type: ignore[union-attr]


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
    """run_fmriprep_bids_filter_array_all.sh errors when required values missing."""

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


def _list_mode_config(tmp_path: Path) -> tuple:
    """A minimal valid config for the subject-list path (no CSV needed)."""
    bids = tmp_path / "bids"
    (bids / "sub-ADNI002S0413" / "ses-M000" / "func").mkdir(parents=True)
    results = tmp_path / "results"
    cfg = tmp_path / "config_list.yaml"
    cfg.write_text(
        """
        fmriprep:
          bids_dir: {bids}
          output_dir: {out}
          work_dir: {work}
        paths:
          fmriprep_results_root: {results}
          fmriprep_heuristics_csv: ""
        containers:
          fmriprep_image: ""
          freesurfer_license: ""
        """.format(bids=bids, out=tmp_path / "out", work=tmp_path / "work", results=results),
        encoding="utf-8",
    )
    return cfg, results


def _queued_subjects(results: Path) -> list:
    """Read the subject ids the driver wrote to its job-array input files."""
    subs = []
    for f in sorted((results / "scripts").glob("job_array_input_part_*")):
        subs += [ln.strip() for ln in f.read_text().splitlines() if ln.strip()]
    return subs


def test_run_fmriprep_inline_subjects_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--subjects builds the array from the CLI list (mixed spellings), no CSV needed."""
    _setup_stub_binaries(tmp_path, monkeypatch)
    cfg, results = _list_mode_config(tmp_path)

    result = subprocess.run(
        ["bash", str(FMRIPREP_DIR / "run_fmriprep_bids_filter_array_all.sh"),
         "--config", str(cfg),
         "--subjects", "002_S_0413 sub-ADNI130S1234 ADNI077S0999",
         "--dry-run"],
        cwd=str(REPO_ROOT), check=False, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert set(_queued_subjects(results)) == {
        "sub-ADNI002S0413", "sub-ADNI130S1234", "sub-ADNI077S0999"}


def test_run_fmriprep_subject_list_and_ignore_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--subject-list reads a file; .done subjects are skipped unless --ignore-done."""
    _setup_stub_binaries(tmp_path, monkeypatch)
    cfg, results = _list_mode_config(tmp_path)

    sub_file = tmp_path / "subs.txt"
    sub_file.write_text("# rerun these\n002_S_0413\n130_S_1234\n", encoding="utf-8")

    # Mark 002_S_0413 as already done.
    donedir = results / "scripts" / "done"
    donedir.mkdir(parents=True)
    (donedir / "sub-ADNI002S0413.done").write_text("", encoding="utf-8")

    base = ["bash", str(FMRIPREP_DIR / "run_fmriprep_bids_filter_array_all.sh"),
            "--config", str(cfg), "--subject-list", str(sub_file), "--dry-run"]

    # Without --ignore-done: the done subject is skipped.
    r1 = subprocess.run(base, cwd=str(REPO_ROOT), check=False, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    assert _queued_subjects(results) == ["sub-ADNI130S1234"]

    # With --ignore-done: both are queued.
    r2 = subprocess.run(base + ["--ignore-done"], cwd=str(REPO_ROOT), check=False,
                        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    assert set(_queued_subjects(results)) == {"sub-ADNI002S0413", "sub-ADNI130S1234"}


def _write_sessions_csv(path: Path, rows) -> None:
    """rows: (SUBJECT_ID, VISCODE); mirrors the ADNI Philips-sessions export."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["VISCODE", "SCANDATE", "SERIES_ID", "IMAGE_ID", "SUBJECT_ID"])
        for sub, vis in rows:
            w.writerow([vis, "2012-05-15", "150694", "304790", sub])


def test_make_bids_filters_writes_per_subject_json(tmp_path: Path) -> None:
    sess = tmp_path / "sessions.csv"
    _write_sessions_csv(sess, [("002_S_0413", "m72"), ("002_S_0413", "m84"),
                               ("006_S_0498", "bl")])
    subj = mbf.load_subject_sessions(sess)
    assert subj == {"sub-ADNI002S0413": {"M072", "M084"}, "sub-ADNI006S0498": {"M000"}}

    fdir = tmp_path / "filters"
    subs = mbf.write_filters(subj, fdir, task="rest")
    assert subs == ["sub-ADNI002S0413", "sub-ADNI006S0498"]
    flt = json.loads((fdir / "sub-ADNI002S0413_filter.json").read_text())
    assert flt["bold"]["session"] == ["M072", "M084"]
    assert flt["bold"]["task"] == "rest"
    assert flt["t1w"]["session"] == ["M072", "M084"]


def test_make_bids_filters_bad_columns_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        mbf.load_subject_sessions(bad)


def test_run_fmriprep_sessions_csv_generates_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--sessions-csv writes per-subject filters and the array passes them to fMRIPrep."""
    _setup_stub_binaries(tmp_path, monkeypatch)
    cfg, results = _list_mode_config(tmp_path)
    sess = tmp_path / "sessions.csv"
    _write_sessions_csv(sess, [("002_S_0413", "m72"), ("002_S_0413", "m84")])

    result = subprocess.run(
        ["bash", str(FMRIPREP_DIR / "run_fmriprep_bids_filter_array_all.sh"),
         "--config", str(cfg), "--sessions-csv", str(sess), "--ignore-done"],
        cwd=str(REPO_ROOT), check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    flt = json.loads(
        (results / "scripts" / "filters" / "sub-ADNI002S0413_filter.json").read_text())
    assert flt["bold"]["session"] == ["M072", "M084"]

    assert _queued_subjects(results) == ["sub-ADNI002S0413"]
    slurms = list((results / "scripts").glob("fmriprep_array_*.slurm"))
    assert slurms, "no array script generated"
    text = slurms[0].read_text()
    assert "--bids-filter-file /filters/${subid}_filter.json" in text
    assert "/filters:ro" in text


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
