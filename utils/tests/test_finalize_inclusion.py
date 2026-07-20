"""Tests for s8_final_qc/finalize_inclusion.py helper logic."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "s8_final_qc" / "finalize_inclusion.py"

_spec = importlib.util.spec_from_file_location("finalize_inclusion", MODULE_PATH)
fi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fi)  # type: ignore[union-attr]


def test_mriqc_exclude_column_variants() -> None:
    assert list(fi.mriqc_exclude_column(pd.DataFrame({"exclude_mriqc": [1, 0]}))) == [1, 0]
    assert list(fi.mriqc_exclude_column(pd.DataFrame({"excluded_any": [True, False]}))) == [1, 0]
    assert list(fi.mriqc_exclude_column(
        pd.DataFrame({"qc_status_any": ["excluded", "included"]}))) == [1, 0]
    with pytest.raises(ValueError):
        fi.mriqc_exclude_column(pd.DataFrame({"foo": [1]}))


def test_sitewise_euler_handles_string_site_column() -> None:
    # Regression: assigning integer site codes used to crash on string-dtype
    # site columns; factorize must handle it. Provide an obvious outlier.
    euler = pd.DataFrame({
        "sub": [f"sub-{i}" for i in range(6)],
        "ses": ["ses-M000"] * 6,
        "site": ["002"] * 6,  # same site so the outlier deviates from the site median
        "avg_en": [-10.0, -12.0, -11.0, -9.0, -13.0, -900.0],  # last is a huge outlier
    })
    flags, removed = fi.compute_sitewise_euler_exclusion(euler)
    assert flags.dtype == bool
    assert "sub-5" in removed          # the -900 outlier is flagged
    assert "sub-0" not in removed
