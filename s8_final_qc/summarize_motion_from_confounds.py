#!/usr/bin/env python

import argparse
import os
import glob
import pandas as pd
import numpy as np

def parse_bids_from_confounds(path):
    """
    Extract sub, ses, task, run from a confounds TSV filename.
    Assumes filenames like:
      sub-XXX_ses-YYY_task-rest_run-01_desc-confounds_timeseries.tsv
    """
    fname = os.path.basename(path)
    tokens = fname.split("_")
    info = {"sub": None, "ses": None, "task": None, "run": None}
    for t in tokens:
        if t.startswith("sub-"):
            info["sub"] = t
        elif t.startswith("ses-"):
            info["ses"] = t
        elif t.startswith("task-"):
            info["task"] = t
        elif t.startswith("run-"):
            info["run"] = t
    return info

def compute_fd_power_from_params(df, trans_cols, rot_cols, radius=50.0):
    """
    Compute Power FD (FD_P) from motion parameters:
    FD_i = sum(|Δtrans|) + R * sum(|Δrot|),
    where rotations are in radians and R is in mm.
    """
    # Ensure all needed columns exist
    for c in trans_cols + rot_cols:
        if c not in df.columns:
            raise ValueError(f"Missing motion column '{c}' in confounds file.")

    trans = df[trans_cols].values
    rots = df[rot_cols].values  # radians

    # differences across time (prepend zeros for first frame)
    d_trans = np.vstack([np.zeros((1, 3)), np.diff(trans, axis=0)])
    d_rots = np.vstack([np.zeros((1, 3)), np.diff(rots, axis=0)])

    fd = np.abs(d_trans).sum(axis=1) + radius * np.abs(d_rots).sum(axis=1)
    return fd

def process_confounds(confounds_path, fd_thresh):
    info = parse_bids_from_confounds(confounds_path)

    df = pd.read_csv(confounds_path, sep="\t")

    # FD_P: prefer the fMRIPrep column, otherwise compute it
    if "framewise_displacement" in df.columns:
        fd_p = df["framewise_displacement"].fillna(0.0).values
    else:
        fd_p = compute_fd_power_from_params(
            df,
            trans_cols=["trans_x", "trans_y", "trans_z"],
            rot_cols=["rot_x", "rot_y", "rot_z"],
        )

    # DVARS: prefer std_dvars, fall back to dvars, else NaN
    if "std_dvars" in df.columns:
        dvars = df["std_dvars"].values
    elif "dvars" in df.columns:
        dvars = df["dvars"].values
    else:
        dvars = np.full_like(fd_p, np.nan, dtype=float)

    n_tp = len(fd_p)
    over_thresh = fd_p > fd_thresh
    prop_over = over_thresh.mean()

    # Basic summary metrics
    motion_summary = {
        "sub": info["sub"],
        "ses": info["ses"],
        "task": info["task"],
        "run": info["run"],
        "n_volumes": n_tp,
        "mean_fd_p": float(np.nanmean(fd_p)),
        "median_fd_p": float(np.nanmedian(fd_p)),
        "max_fd_p": float(np.nanmax(fd_p)),
        "prop_fd_p_over_thresh": float(prop_over),
        "n_fd_p_over_thresh": int(over_thresh.sum()),
        "mean_dvars": float(np.nanmean(dvars)),
    }

    # Per-timepoint table
    idx = np.arange(n_tp)
    ts_df = pd.DataFrame({
        "sub": info["sub"],
        "ses": info["ses"],
        "task": info["task"],
        "run": info["run"],
        "t": idx,
        "FD_P": fd_p,
        "DVARS": dvars,
        "FD_P_over_thresh": over_thresh.astype(int),
    })

    return motion_summary, ts_df


def main():
    parser = argparse.ArgumentParser(
        description="Summarize motion from fMRIPrep confounds files."
    )
    parser.add_argument(
        "--derivatives-dir",
        required=True,
        help="Path to fMRIPrep derivatives directory (the one that contains sub-*/ses-*/func/).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write motion_summary.tsv and motion_timeseries.tsv",
    )
    parser.add_argument(
        "--fd-thresh",
        type=float,
        default=0.5,
        help="FD_P threshold (mm) for flagging high-motion frames (default: 0.5).",
    )
    args = parser.parse_args()

    confounds_glob = os.path.join(
        args.derivatives_dir,
        "sub-*",
        "ses-*",
        "func",
        "*_desc-confounds_timeseries.tsv",
    )
    confound_files = sorted(glob.glob(confounds_glob))

    if not confound_files:
        raise RuntimeError(f"No confounds files found with pattern: {confounds_glob}")

    os.makedirs(args.output_dir, exist_ok=True)

    summary_rows = []
    ts_rows = []

    for cf in confound_files:
        try:
            summary, ts_df = process_confounds(cf, fd_thresh=args.fd_thresh)
        except Exception as e:
            print(f"[WARN] Skipping {cf} due to error: {e}")
            continue

        summary_rows.append(summary)
        ts_rows.append(ts_df)

    motion_summary = pd.DataFrame(summary_rows)
    motion_timeseries = pd.concat(ts_rows, ignore_index=True)

    summary_path = os.path.join(args.output_dir, "motion_summary.tsv")
    timeseries_path = os.path.join(args.output_dir, "motion_timeseries.tsv")

    motion_summary.to_csv(summary_path, sep="\t", index=False)
    motion_timeseries.to_csv(timeseries_path, sep="\t", index=False)

    print(f"Wrote motion summary to {summary_path}")
    print(f"Wrote motion timeseries to {timeseries_path}")


if __name__ == "__main__":
    main()
