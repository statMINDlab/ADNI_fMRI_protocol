#!/usr/bin/env python
"""Run session-level QC heuristics and write standardized outputs.

This script is a CLI wrapper around `SessionFilterPipeline` that:
- Runs all configured heuristic phases on the anchor+metadata CSV.
- Prints a table of heuristics grouped by phase.
- Writes three TSV outputs:
  * missing_t1w.tsv      – rows dropped by the T1w-existence heuristic.
  * missing_data.tsv     – rows dropped by the NIfTI/JSON-existence heuristic.
  * final_heuristics.tsv – final per-session table used by downstream MRIQC/fMRIPrep.

The intent is that config paths in `config/config_adni.yaml` can point to these
outputs for use by later pipeline steps.
"""

import argparse
import os
import sys
from pathlib import Path

# Allow running this script directly (so that "scripts" can be imported)
HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE / "scripts"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scripts.session_pipeline import SessionFilterPipeline


# Keep this in sync with `SessionFilterPipeline.display_phase_summary`
NAME_MAP = {
    "filter_missing_data": "Missing Data",
    "filter_missing_data_adnidap": "BIDS",
    "filter_missing_t1w": "T1w Image Missing",
    "filter_invalid_repetition_time": "RepetitionTime (TR)",
    "filter_out_bad_coils": "CoilString",
    "filter_low_scan_depth": "ScanDepth (dim3×pixdim3)",
    "filter_low_percent_phase_fov": "PercentPhaseFOV",
    "filter_short_duration": "Scan Duration",
}

DESC_MAP = {
    "RepetitionTime (TR)": "Sessions where TR falls outside [0.5–1.0] or [2.9–3.1] seconds.",
    "CoilString": "Sessions that use Q-BODY or BODY coils.",
    "ScanDepth (dim3×pixdim3)": "Scan Depth (dim₃ × pixdim₃) is outside the range [155, 180].",
    "PercentPhaseFOV": "A session with an unusually low value of ≤ 72.",
    "BIDS": "Sessions flagged due to known errors in Clinica BIDS conversion.",
    "Missing Data": "Sessions where required NIfTI or JSON files are missing after Clinica conversion.",
    "T1w Image Missing": "Session does not have a T1-weighted image.",
    "Scan Duration": "Sessions where total scan duration (TR × volumes) is less than 5 minutes.",
}


def print_heuristics_table(pipeline: SessionFilterPipeline) -> None:
    """Print a simple text table of heuristics grouped by phase.

    Columns: Phase, Heuristic code, Pretty name, Description.
    """

    header = ["Phase", "Heuristic", "Name", "Description"]
    rows = []

    for phase, heuristics in sorted(pipeline.phase_map.items()):
        for _, code_name in heuristics:
            pretty = NAME_MAP.get(code_name, code_name)
            desc = DESC_MAP.get(pretty, "")
            rows.append((phase, code_name, pretty, desc))

    # Compute simple column widths for pretty printing
    col_widths = [len(h) for h in header]
    for phase, code, pretty, desc in rows:
        col_widths[0] = max(col_widths[0], len(str(phase)))
        col_widths[1] = max(col_widths[1], len(code))
        col_widths[2] = max(col_widths[2], len(pretty))
        col_widths[3] = max(col_widths[3], len(desc))

    def fmt_row(cols):
        return " | ".join(str(c).ljust(w) for c, w in zip(cols, col_widths, strict=False))

    print("Heuristics by phase:\n")
    print(fmt_row(header))
    print("-+-".join("-" * w for w in col_widths))
    for row in rows:
        print(fmt_row(row))
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run session-level QC heuristics")
    parser.add_argument(
        "--input-csv",
        required=True,
        help="Path to anchor+metadata CSV from create_mastersheet.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where TSV outputs will be written.",
    )
    parser.add_argument(
        "--fmriprep-subjects-csv",
        default=None,
        help=(
            "Optional path for a per-subject sessions CSV of the form "
            "[Subject_ID,sessions]. If not provided, this file is not written."
        ),
    )
    parser.add_argument(
        "--phase-limit",
        type=int,
        default=2,
        help="Highest phase index to run (default: 2).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_csv = Path(args.input_csv)
    output_dir = Path(args.output_dir)
    fmriprep_subjects_csv = Path(args.fmriprep_subjects_csv) if args.fmriprep_subjects_csv else None

    if not input_csv.is_file():
        raise SystemExit(f"Input CSV does not exist: {input_csv}")

    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline = SessionFilterPipeline(str(input_csv))

    # Print heuristics table (based on configured phase_map)
    print_heuristics_table(pipeline)

    # Run the actual filtering
    pipeline.run(phase_limit=args.phase_limit, verbose=True)

    # 1) Rows dropped for missing T1w
    missing_t1 = pipeline.dropped_dfs.get("filter_missing_t1w")
    if missing_t1 is not None:
        missing_t1_path = output_dir / "missing_t1w.tsv"
        missing_t1.to_csv(missing_t1_path, sep="\t", index=False)
        print(f"Wrote missing T1w table to: {missing_t1_path}")
    else:
        print("[warn] No entries for filter_missing_t1w; not writing missing_t1w.tsv")

    # 2) Rows dropped for missing NIfTI/JSON
    missing_data = pipeline.dropped_dfs.get("filter_missing_data")
    if missing_data is not None:
        missing_data_path = output_dir / "missing_data.tsv"
        missing_data.to_csv(missing_data_path, sep="\t", index=False)
        print(f"Wrote missing data table to: {missing_data_path}")
    else:
        print("[warn] No entries for filter_missing_data; not writing missing_data.tsv")

    # 3) Final per-session/subject table for MRIQC & fMRIPrep
    final_path = output_dir / "final_heuristics.tsv"
    pipeline.df_current.to_csv(final_path, sep="\t", index=False)
    print(f"Wrote final heuristics table to: {final_path}")

    # 4) Optional per-subject sessions CSV for fMRIPrep
    if fmriprep_subjects_csv is not None:
        df = pipeline.df_current.copy()

        def clean_viscode(v: str) -> str:
            v = str(v).upper()
            if v.startswith("M"):
                num = v[1:]
                return "M" + num.zfill(3)
            return v

        grouped = (
            df.groupby("Subject_ID")["VISCODE"]
            .unique()
            .apply(lambda arr: sorted(clean_viscode(v) for v in arr))
            .reset_index()
        )
        grouped["sessions"] = grouped["VISCODE"].apply(lambda lst: " ".join(lst))
        out = grouped[["Subject_ID", "sessions"]]

        fmriprep_subjects_csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(fmriprep_subjects_csv, index=False)
        print(f"Wrote fMRIPrep per-subject sessions CSV to: {fmriprep_subjects_csv}")


if __name__ == "__main__":  # pragma: no cover
    main()
