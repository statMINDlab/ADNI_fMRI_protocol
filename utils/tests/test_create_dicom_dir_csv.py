"""Tests for s3_organize/create_dicom_dir_csv.sh.

These tests exercise config handling and basic CSV output shape.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "s3_organize" / "create_dicom_dir_csv.sh"


def _write_config(path: Path, raw_dicom_dir: str) -> None:
    path.write_text(
        """
        paths:
          raw_dicom_dir: {raw}
        """.format(raw=raw_dicom_dir),
        encoding="utf-8",
    )


def test_create_dicom_dir_csv_errors_on_empty_config(tmp_path: Path) -> None:
    """Script exits with an error if paths.raw_dicom_dir is empty.

    When utils.config_tools cannot resolve the key, DICOM_ROOT may
    end up as an invalid directory; we only assert non-zero exit.
    """

    cfg = tmp_path / "config_empty.yaml"
    _write_config(cfg, "")

    result = subprocess.run(
        ["bash", str(SCRIPT), "--config", str(cfg)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_create_dicom_dir_csv_writes_expected_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Script walks a small fake DICOM tree and writes dicom_dirs.csv."""

    # Build fake DICOM directory tree: sub/scan/date/leaf
    root = tmp_path / "dicoms"
    leaf = root / "S_0001" / "SCAN_A" / "20200101" / "SERIES01"
    leaf.mkdir(parents=True)

    cfg = tmp_path / "config.yaml"
    _write_config(cfg, str(root))

    # Run script; it cd's into DICOM_ROOT and writes dicom_dirs.csv there
    result = subprocess.run(
        ["bash", str(SCRIPT), "--config", str(cfg)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    csv_path = root / "dicom_dirs.csv"
    assert csv_path.exists()

    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    # Header + one row
    assert lines[0] == "sub_ID,scan_name,scan_date,leaf_dir"
    assert len(lines) == 2

    fields = lines[1].split(",")
    assert fields == ["S_0001", "SCAN_A", "20200101", "SERIES01"]
