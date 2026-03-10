import csv
import os
import runpy
from pathlib import Path

import pandas as pd


def _write_tiny_anchor_csv(tmp_path: Path) -> Path:
    """Write a minimal anchor+metadata CSV that exercises all heuristics.

    Columns are chosen to match what the heuristics module expects:
    - Image_ID, Subject_ID, VISCODE
    - NIfTI/JSON existence flags
    - DICOM/BIDS metadata needed for scan depth, TR, and duration.
    """

    rows = [
        # Good session that should survive all heuristics
        {
            "Image_ID": 1,
            "Subject_ID": "001_S_0001",
            "VISCODE": "m12",
            "NIfTI_exists": "TRUE",
            "JSON_exists": "TRUE",
            "T1w_exists": "TRUE",
            "nifti_dim": "[0, 0, 0, 160, 300]",  # dim3=160, n_volumes=300
            "nifti_pixdim": "[0, 0, 0, 1.0, 0]",  # pixdim3=1.0 => depth 160
            "json_RepetitionTime": 3.0,
            "json_PercentPhaseFOV": 80,
            "json_CoilString": "HEAD",
        },
        # Missing data (NIfTI_exists=FALSE)
        {
            "Image_ID": 2,
            "Subject_ID": "001_S_0002",
            "VISCODE": "m06",
            "NIfTI_exists": "FALSE",
            "JSON_exists": "TRUE",
            "T1w_exists": "TRUE",
            "nifti_dim": "[0, 0, 0, 160, 300]",
            "nifti_pixdim": "[0, 0, 0, 1.0, 0]",
            "json_RepetitionTime": 3.0,
            "json_PercentPhaseFOV": 80,
            "json_CoilString": "HEAD",
        },
        # Missing T1w
        {
            "Image_ID": 3,
            "Subject_ID": "001_S_0003",
            "VISCODE": "m24",
            "NIfTI_exists": "TRUE",
            "JSON_exists": "TRUE",
            "T1w_exists": "FALSE",
            "nifti_dim": "[0, 0, 0, 160, 300]",
            "nifti_pixdim": "[0, 0, 0, 1.0, 0]",
            "json_RepetitionTime": 3.0,
            "json_PercentPhaseFOV": 80,
            "json_CoilString": "HEAD",
        },
    ]

    cols = list(rows[0].keys())
    csv_path = tmp_path / "tiny_anchor.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def test_run_session_heuristics_creates_expected_outputs(tmp_path, monkeypatch, capsys):
    """Smoke test: run the CLI entrypoint on a tiny CSV and check outputs.

    This exercises:
    - heuristics filtering
    - writing missing_t1w.tsv, missing_data.tsv, final_heuristics.tsv
    - optional fMRIPrep per-subject sessions CSV
    """

    input_csv = _write_tiny_anchor_csv(tmp_path)
    output_dir = tmp_path / "outputs"
    fmriprep_csv = tmp_path / "fmriprep_subjects.csv"

    # Build argv as if called from the command line
    argv = [
        "run_session_heuristics.py",
        "--input-csv",
        str(input_csv),
        "--output-dir",
        str(output_dir),
        "--fmriprep-subjects-csv",
        str(fmriprep_csv),
        "--phase-limit",
        "2",
    ]

    monkeypatch.setattr("sys.argv", argv)

    # Run the script as a module so we don't depend on package layout
    runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "s5_post_clinica_qc"
            / "create_report"
            / "run_session_heuristics.py"
        ),
        run_name="__main__",
    )

    # Capture output just to ensure it ran without crashing
    captured = capsys.readouterr()
    assert "Heuristics by phase" in captured.out

    # Check that the three TSVs exist
    missing_t1 = output_dir / "missing_t1w.tsv"
    missing_data = output_dir / "missing_data.tsv"
    final_tsv = output_dir / "final_heuristics.tsv"

    assert missing_t1.is_file()
    assert missing_data.is_file()
    assert final_tsv.is_file()

    # Check that the fMRIPrep subjects CSV exists and has expected structure
    assert fmriprep_csv.is_file()
    df_subj = pd.read_csv(fmriprep_csv)
    assert set(df_subj.columns) == {"Subject_ID", "sessions"}
    # With this tiny input, the surviving subject should be 001_S_0001 with a VISCODE cleaned to M012
    assert (df_subj["Subject_ID"] == "001_S_0001").any()
    assert df_subj["sessions"].str.contains("M012").any()
