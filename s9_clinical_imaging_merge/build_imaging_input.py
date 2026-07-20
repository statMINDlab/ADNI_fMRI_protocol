#!/usr/bin/env python
"""Build the enriched imaging input for the Step-9 swimlane from Step-8 output.

`adni_swimlane_clinical.py --imaging` expects an `included_sessions_merged.csv`
that is the Step-8 `included_sessions.tsv` plus three columns it needs but that
the final-QC table does not carry: `Subject_ID`, `Scan_Date`, and `DIAGNOSIS`
(the diagnosis at the imaging visit). This script adds them:

  * `Subject_ID` / `VISCODE` are derived from the BIDS `sub` / `ses` labels
    (`sub-ADNI002S0413` -> `002_S_0413`, `ses-M060` -> `m60`, `ses-M000` -> `bl`).
  * `Scan_Date` is taken from the Step-5 mastersheet on `(Subject_ID, VISCODE)`.
  * `DIAGNOSIS` is the ADNI DXSUM diagnosis at the visit nearest the scan date
    (nearest `EXAMDATE` per subject), which fills sessions an exact visit-code
    join would miss.

Usage:
    python s9_clinical_imaging_merge/build_imaging_input.py \\
        --included    s8_final_qc/included_sessions.tsv \\
        --mastersheet /path/to/anchor_plus_dicom_nifti_struct.csv \\
        --dxsum       /path/to/DXSUM.csv \\
        --output      s9_clinical_imaging_merge/included_sessions_merged.csv

Requirements: pandas, numpy.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def sub_to_subject_id(sub: str) -> str | None:
    s = re.sub(r"[^A-Za-z0-9]", "", str(sub)).upper().removeprefix("SUB").removeprefix("ADNI")
    m = re.match(r"(\d+)S(\d+)$", s)
    return f"{m.group(1)}_S_{m.group(2)}" if m else None


def sub_to_rid(sub: str) -> int | None:
    m = re.search(r"S(\d+)\b", str(sub))
    return int(m.group(1)) if m else None


def ses_to_viscode(ses: str) -> str | None:
    """ses-M000 -> bl; ses-M060 -> m60; ses-M006 -> m06 (mastersheet VISCODE form)."""
    m = re.search(r"M(\d+)", str(ses))
    if not m:
        return None
    n = int(m.group(1))
    return "bl" if n == 0 else f"m{n:02d}"


def _read(path: str) -> pd.DataFrame:
    sep = "\t" if Path(path).suffix.lower() in (".tsv", ".tab") else ","
    return pd.read_csv(path, sep=sep, low_memory=False)


def add_scan_date(df: pd.DataFrame, mastersheet_csv: str) -> pd.DataFrame:
    ms = _read(mastersheet_csv)[["Subject_ID", "VISCODE", "Scan_Date"]]
    ms = ms.dropna(subset=["Subject_ID", "VISCODE"]).drop_duplicates(["Subject_ID", "VISCODE"])
    lut = ms.set_index(["Subject_ID", "VISCODE"])["Scan_Date"].to_dict()
    df["Scan_Date"] = [lut.get((s, v), np.nan)
                       for s, v in zip(df["Subject_ID"], df["VISCODE"], strict=False)]
    return df


def add_diagnosis(df: pd.DataFrame, dxsum_csv: str, max_days: int | None) -> pd.DataFrame:
    dx = _read(dxsum_csv)
    dx["RID"] = pd.to_numeric(dx["RID"], errors="coerce")
    dx["EXAMDATE"] = pd.to_datetime(dx["EXAMDATE"], errors="coerce")
    dx = dx.dropna(subset=["RID", "EXAMDATE", "DIAGNOSIS"])
    by_rid = {rid: g.sort_values("EXAMDATE") for rid, g in dx.groupby(dx["RID"].astype(int))}

    scan_dt = pd.to_datetime(df["Scan_Date"], errors="coerce")

    def nearest(rid, dt):
        g = by_rid.get(rid)
        if g is None or pd.isna(dt):
            return np.nan
        deltas = (g["EXAMDATE"] - dt).abs()
        i = int(deltas.values.argmin())
        if max_days is not None and deltas.iloc[i].days > max_days:
            return np.nan
        return g["DIAGNOSIS"].iloc[i]

    df["DIAGNOSIS"] = [nearest(int(r), d) if pd.notna(r) else np.nan
                       for r, d in zip(df["RID"], scan_dt, strict=False)]
    return df


def build(included_tsv: str, mastersheet_csv: str, dxsum_csv: str,
          max_days: int | None) -> pd.DataFrame:
    df = _read(included_tsv)
    for col in ("sub", "ses"):
        if col not in df.columns:
            raise ValueError(f"{included_tsv} must have a '{col}' column.")
    df["Subject_ID"] = df["sub"].map(sub_to_subject_id)
    df["RID"] = df["sub"].map(sub_to_rid)
    df["VISCODE"] = df["ses"].map(ses_to_viscode)
    df = add_scan_date(df, mastersheet_csv)
    df = add_diagnosis(df, dxsum_csv, max_days)
    return df


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--included", required=True, help="Step-8 included_sessions.tsv")
    p.add_argument("--mastersheet", required=True,
                   help="Step-5 mastersheet (anchor_plus_dicom_nifti_struct.csv) for Scan_Date")
    p.add_argument("--dxsum", required=True, help="ADNI DXSUM CSV for DIAGNOSIS")
    p.add_argument("--output", required=True, help="Output enriched CSV")
    p.add_argument("--max-dx-days", type=int, default=None,
                   help="Optional cap (days) on the nearest DXSUM visit; default: no cap.")
    args = p.parse_args(argv)

    try:
        df = build(args.included, args.mastersheet, args.dxsum, args.max_dx_days)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"[build_imaging_input] {e}", file=sys.stderr)
        return 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"[build_imaging_input] {len(df)} sessions, "
          f"Scan_Date {int(df['Scan_Date'].notna().sum())}, "
          f"DIAGNOSIS {int(df['DIAGNOSIS'].notna().sum())} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
