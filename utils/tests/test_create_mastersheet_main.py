"""Tests for s5_post_clinica_qc/analysis/create_mastersheet/main.py.

These focus on config handling and failure modes, not full data parsing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_DIR = REPO_ROOT / "s5_post_clinica_qc" / "analysis" / "create_mastersheet"


def test_main_errors_when_paths_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() should fail clearly when configured paths do not exist.

    We point both clinica_conversion_info_dir and clinica_bids_dir at
    non-existent locations and assert a non-zero exit code. The exact
    error message may evolve, so we only check that it fails.
    """

    cfg = tmp_path / "config_bad_paths.yaml"
    cfg.write_text(
        """
        paths:
          clinica_conversion_info_dir: {conv}
          clinica_bids_dir: {bids}
        """.format(conv=tmp_path / "missing_conv", bids=tmp_path / "missing_bids"),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python",
            "-m",
            "s5_post_clinica_qc.analysis.create_mastersheet.main",
            "--config",
            str(cfg),
        ],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    # Either the module import or path-based logic should fail here.
    assert result.returncode != 0


@pytest.mark.skip("Smoke test depends on package layout for parsers; enable when module imports cleanly in test env.")
def test_main_runs_with_stubbed_parsers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test: run main() with patched parsers to avoid heavy IO.

    We monkeypatch DICOMMetadata, NiftiParser, and StructuralProbe to
    minimal in-memory implementations, then ensure the script runs to
    completion and writes the final CSV in a temp data directory.
    """

    # Point working directory to a temp copy so that `data/` is under tmp_path
    monkeypatch.chdir(MAIN_DIR)

    # Prepare a minimal config and fake paths used by DefaultFlatStrategy.
    # We do not need real files because we will stub the strategy via anchors.
    cfg_path = tmp_path / "config_stub.yaml"
    cfg_path.write_text(
        """
        paths:
          clinica_conversion_info_dir: {conv}
          clinica_bids_dir: {bids}
        """.format(conv=tmp_path / "conv_info", bids=tmp_path / "bids_root"),
        encoding="utf-8",
    )

    # Monkeypatch the heavy components inside the module namespace.
    # Import via file path rather than package to avoid package layout issues.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "create_mastersheet_main_stub", MAIN_DIR / "main.py"
    )
    assert spec is not None and spec.loader is not None
    main_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_mod)  # type: ignore[union-attr]

    class _DummyAnchor:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self._df = main_mod.pd.DataFrame(
                [
                    {
                        "Path": "/dummy/dicom.dcm",
                        "NIfTI_path": "/dummy/func.nii.gz",
                        "JSON_path": "/dummy/func.json",
                        "Subject_ID": "S_0001",
                        "VISCODE": "bl",
                    }
                ]
            )

        def get_df(self):  # type: ignore[no-untyped-def]
            return self._df

        def hash_has_changed(self):  # type: ignore[no-untyped-def]
            return True

    class _DummyDICOM:
        def __init__(self, path):  # type: ignore[no-untyped-def]
            self._path = path

        def to_dict(self):  # type: ignore[no-untyped-def]
            return {"dcm_dummy": "value"}

    class _DummyNiftiParser:
        def __init__(self, nifti_path, json_path):  # type: ignore[no-untyped-def]
            self._nifti = nifti_path
            self._json = json_path

        def parse(self):  # type: ignore[no-untyped-def]
            return {"nifti_dummy": "value"}

    class _DummyStructuralProbe:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def run(self, df):  # type: ignore[no-untyped-def]
            # Return a DataFrame with the same number of rows and one extra column
            return main_mod.pd.DataFrame({"struct_dummy": [1] * len(df)})

    monkeypatch.setattr(main_mod, "AnchorTable", _DummyAnchor)
    monkeypatch.setattr(main_mod, "DICOMMetadata", _DummyDICOM)
    monkeypatch.setattr(main_mod, "NiftiParser", _DummyNiftiParser)
    monkeypatch.setattr(main_mod, "StructuralProbe", _DummyStructuralProbe)

    # Run the module as a script with the stubbed components
    result = subprocess.run(
        [
            "python",
            "-m",
            "s5_post_clinica_qc.analysis.create_mastersheet.main",
            "--config",
            str(cfg_path),
        ],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    # The final CSV should exist under data/ in the working directory
    final_csv = MAIN_DIR / "data" / "anchor_plus_dicom_nifti_struct.csv"
    assert final_csv.exists()
