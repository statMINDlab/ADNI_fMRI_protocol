"""Tests for utils.config_tools.

These tests cover:
1. load_config correctly loading a valid YAML configuration file.
2. get_value retrieving a nested value via dotted key path.
3. load_config raising FileNotFoundError when the file does not exist.
4. get_value raising KeyError for a missing key path.
5. The CLI printing a scalar value for a given key path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Ensure the repository root (parent of the 'utils' package) is on sys.path so that
# 'utils.config_tools' can be imported reliably, regardless of how pytest is invoked.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.config_tools import get_value, load_config


@pytest.fixture
def tmp_config_file(tmp_path: Path) -> Path:
    """Create a temporary YAML config file for tests that need one."""

    cfg_content = """
    paths:
      raw_dicom_dir: /data/dicom
    fmriprep:
      bids_dir: /data/bids
    scalar_value: 123
    """

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(cfg_content)
    return cfg_path


def test_load_config_loads_valid_yaml(tmp_config_file: Path) -> None:
    """load_config correctly loads a valid YAML configuration file."""

    cfg = load_config(tmp_config_file)

    assert isinstance(cfg, dict)
    assert cfg["paths"]["raw_dicom_dir"] == "/data/dicom"
    assert cfg["fmriprep"]["bids_dir"] == "/data/bids"
    assert cfg["scalar_value"] == 123


def test_get_value_retrieves_nested_value(tmp_config_file: Path) -> None:
    """get_value retrieves a nested value using a dotted key path."""

    cfg = load_config(tmp_config_file)
    value = get_value(cfg, "fmriprep.bids_dir")

    assert value == "/data/bids"


def test_load_config_raises_file_not_found(tmp_path: Path) -> None:
    """load_config raises FileNotFoundError when the config file is missing."""

    missing_path = tmp_path / "does_not_exist.yaml"

    with pytest.raises(FileNotFoundError):
        load_config(missing_path)


def test_get_value_raises_key_error_for_missing_path() -> None:
    """get_value raises KeyError if the key path does not exist in the config."""

    cfg = {"paths": {"raw_dicom_dir": "/data/dicom"}}

    with pytest.raises(KeyError):
        get_value(cfg, "paths.nonexistent_key")


def test_cli_outputs_scalar_value(tmp_config_file: Path) -> None:
    """CLI prints a scalar value for the given key path and exits with code 0."""

    # The repo root is two levels up from this test file: utils/tests/test_config_tools.py
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "utils.config_tools",
            "scalar_value",
            "--config",
            str(tmp_config_file),
        ],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    # CLI should print the scalar directly, not JSON-encoded
    assert result.stdout.strip() == "123"
    # stderr should be empty for the success case
    assert result.stderr.strip() == ""
