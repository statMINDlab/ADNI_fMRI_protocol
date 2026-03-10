"""Tests for MRIQC Slurm helper scripts.

This module adds lightweight integration-style tests for:
- `s6_mriqc/adni_mriqc.slurm`
- `s6_mriqc/mriqc_group.slurm`

The tests exercise argument parsing and config handling via the
`utils.config_tools` CLI while stubbing out external dependencies such as
`module load apptainer` and the `apptainer` binary itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Repository and script locations
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "s6_mriqc"


def _setup_stub_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, apptainer_log: Path | None = None
) -> None:
    """Create stub `module` and `apptainer` commands on PATH.

    The real scripts rely on the `module` command (for `module load apptainer`)
    and the `apptainer` binary. In the unit tests we replace these with
    lightweight stubs so the scripts can run in any environment.

    If ``apptainer_log`` is provided, all arguments passed to the `apptainer`
    stub will be appended to that file (one invocation per line).
    """

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    module_script = bin_dir / "module"
    module_script.write_text("""#!/usr/bin/env bash
# No-op stub for `module` used in tests.
exit 0
""")
    module_script.chmod(0o755)

    apptainer_script = bin_dir / "apptainer"
    if apptainer_log is not None:
        apptainer_script.write_text(
            f"""#!/usr/bin/env bash
# Stub for `apptainer` used in tests.
printf '%s\n' "$*" >>"{apptainer_log}"
exit 0
"""
        )
    else:
        apptainer_script.write_text(
            """#!/usr/bin/env bash
# No-op stub for `apptainer` used in tests.
exit 0
"""
        )
    apptainer_script.chmod(0o755)

    # Prepend stub bin directory to PATH for the duration of the test.
    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{original_path}")


def test_adni_mriqc_uses_explicit_config_over_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """adni_mriqc.slurm honors the --config argument even if ADNI_CONFIG is set.

    We provide an invalid ADNI_CONFIG (which would fail if used) and a valid
    explicit config via --config. Successful execution implies that the script
    used the explicit config path when resolving values via utils.config_tools.
    """

    _setup_stub_binaries(tmp_path, monkeypatch)

    # ADNI_CONFIG points to a non-existent/invalid file that must NOT be used
    bad_env_cfg = tmp_path / "bad_env_config.yaml"
    monkeypatch.setenv("ADNI_CONFIG", str(bad_env_cfg))

    # Create directories and files referenced by the explicit config
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()
    deriv_root = tmp_path / "derivatives"
    work_root = tmp_path / "work"
    results_root = tmp_path / "results"
    heuristics_csv = tmp_path / "heuristics.csv"
    heuristics_csv.write_text("subid,v1,extra\nS_1234,bl,x\n", encoding="utf-8")
    img_path = tmp_path / "images" / "mriqc.sif"

    explicit_cfg = tmp_path / "explicit_config.yaml"
    explicit_cfg.write_text(
        """
        mriqc:
          bids_dir: {bids_dir}
          output_dir: {deriv_root}
          work_dir: {work_root}
        paths:
          mriqc_results_root: {results_root}
        qc:
          heuristics_final_table: {heuristics_csv}
        containers:
          mriqc_image: {img_path}
        """.format(
            bids_dir=bids_dir,
            deriv_root=deriv_root,
            work_root=work_root,
            results_root=results_root,
            heuristics_csv=heuristics_csv,
            img_path=img_path,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "adni_mriqc.slurm"), "--config", str(explicit_cfg)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    # The script should have created the scripts directory under the configured
    # results_root, demonstrating that it used our explicit config values.
    assert (results_root / "scripts").is_dir()


def test_adni_mriqc_errors_on_missing_required_config_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adni_mriqc.slurm exits with an error if a required config value is empty.

    Here we set mriqc.bids_dir to an empty string while providing non-empty
    placeholders for the other required values.
    """

    _setup_stub_binaries(tmp_path, monkeypatch)

    cfg_path = tmp_path / "config_missing_bids.yaml"
    cfg_path.write_text(
        """
        mriqc:
          bids_dir: ""
          output_dir: /some/output
          work_dir: /some/work
        paths:
          mriqc_results_root: /some/results
        qc:
          heuristics_final_table: /some/heuristics.csv
        containers:
          mriqc_image: /some/image.sif
        """,
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "adni_mriqc.slurm"), "--config", str(cfg_path)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "[adni_mriqc] One or more required config values are missing or empty" in result.stderr


def test_adni_mriqc_errors_when_bids_dir_missing_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adni_mriqc.slurm exits with an error if the configured BIDS root is absent."""

    _setup_stub_binaries(tmp_path, monkeypatch)

    bids_dir = tmp_path / "nonexistent_bids"  # Intentionally not created
    heuristics_csv = tmp_path / "heuristics.csv"
    heuristics_csv.write_text("subid,v1\nS_1234,bl\n", encoding="utf-8")

    cfg_path = tmp_path / "config_bad_bids.yaml"
    cfg_path.write_text(
        """
        mriqc:
          bids_dir: {bids_dir}
          output_dir: /some/output
          work_dir: /some/work
        paths:
          mriqc_results_root: /some/results
        qc:
          heuristics_final_table: {heuristics_csv}
        containers:
          mriqc_image: /some/image.sif
        """.format(bids_dir=bids_dir, heuristics_csv=heuristics_csv),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "adni_mriqc.slurm"), "--config", str(cfg_path)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "[adni_mriqc] BIDS root does not exist:" in result.stderr


def test_adni_mriqc_attempts_to_build_image_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adni_mriqc.slurm calls `apptainer build` when the MRIQC image is absent.

    We configure a valid set of directories and a non-existent image path, then
    assert that the stub `apptainer` binary was invoked with a `build` command
    targeting that path.
    """

    apptainer_log = tmp_path / "apptainer_calls.txt"
    _setup_stub_binaries(tmp_path, monkeypatch, apptainer_log=apptainer_log)

    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()
    deriv_root = tmp_path / "derivatives"
    work_root = tmp_path / "work"
    results_root = tmp_path / "results"
    heuristics_csv = tmp_path / "heuristics.csv"
    heuristics_csv.write_text("subid,v1,extra\nS_1234,bl,x\n", encoding="utf-8")
    img_path = tmp_path / "images" / "mriqc.sif"  # File does not exist yet

    cfg_path = tmp_path / "config_build_image.yaml"
    cfg_path.write_text(
        """
        mriqc:
          bids_dir: {bids_dir}
          output_dir: {deriv_root}
          work_dir: {work_root}
        paths:
          mriqc_results_root: {results_root}
        qc:
          heuristics_final_table: {heuristics_csv}
        containers:
          mriqc_image: {img_path}
        """.format(
            bids_dir=bids_dir,
            deriv_root=deriv_root,
            work_root=work_root,
            results_root=results_root,
            heuristics_csv=heuristics_csv,
            img_path=img_path,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "adni_mriqc.slurm"), "--config", str(cfg_path)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    # The stub apptainer should have been called at least once; inspect the
    # recorded invocation to confirm a build was requested for img_path.
    assert apptainer_log.exists(), "apptainer stub was not invoked"
    lines = [ln.strip() for ln in apptainer_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, "apptainer stub log is empty"

    # Only a single `build` call is expected from the top-level script.
    build_args = lines[0].split()
    assert build_args[0] == "build"
    assert build_args[1] == str(img_path)
    assert build_args[2].startswith("docker://nipreps/mriqc:"), build_args


def test_mriqc_group_errors_on_missing_required_config_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mriqc_group.slurm exits with an error if a required value is empty.

    We configure mriqc.bids_dir as an empty string via ADNI_CONFIG and verify
    that the script emits the expected error message and non-zero exit code.
    """

    _setup_stub_binaries(tmp_path, monkeypatch)

    cfg_path = tmp_path / "group_config_missing_bids.yaml"
    cfg_path.write_text(
        """
        mriqc:
          bids_dir: ""
          output_dir: /some/output
        containers:
          mriqc_image: /some/image.sif
        """,
        encoding="utf-8",
    )

    # Ensure utils.config_tools resolves this config via the ADNI_CONFIG
    monkeypatch.setenv("ADNI_CONFIG", str(cfg_path))

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "mriqc_group.slurm")],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "[mriqc_group] One or more required config values are missing or empty" in result.stderr
