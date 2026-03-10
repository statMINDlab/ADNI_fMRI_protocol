#!/usr/bin/env python

import argparse
import os
import pandas as pd
import numpy as np


def compute_sitewise_euler_exclusion(euler_df):
    """
    Site-specific Euler-based exclusion.

    Expects columns:
      - 'sub'  : subject ID (e.g., 'sub-ADNI941S7074')
      - 'site' : site code (e.g., '941')
      - 'avg_en' : average Euler number (negative values)

    Returns:
      - euler_flags: pd.Series indexed by sub, True if subject should be excluded.
      - removed_subjects: list of subs to exclude.
    """
    tmp = (
        euler_df
        .groupby("sub", as_index=True)
        .agg({"avg_en": "mean", "site": "first"})
        .copy()
    )

    euler_nums = tmp["avg_en"].to_numpy(dtype=np.float32)
    site_series = tmp["site"].astype(str).copy()
    subjects = tmp.index.to_numpy()

    # Map site strings to integer indices
    site_ids = site_series.copy()
    for i, s in enumerate(site_ids.unique()):
        site_ids.loc[site_ids == s] = i
    sites = site_ids.to_numpy(dtype=np.int32)

    transformed = np.full_like(euler_nums, np.nan, dtype=np.float32)
    for site in np.unique(sites):
        mask = sites == site
        vals = euler_nums[mask]

        # only use negative Euler values
        neg_mask = vals < 0
        safe_vals = np.full_like(vals, np.nan, dtype=np.float32)
        safe_vals[neg_mask] = np.sqrt(-vals[neg_mask])

        med = np.nanmedian(safe_vals)
        transformed[mask] = safe_vals - med

    good_mask = np.logical_or(transformed <= 5, np.isnan(transformed))
    bad_mask = np.logical_not(good_mask)

    removed_subjects = list(subjects[bad_mask])

    euler_flags = pd.Series(False, index=subjects, name="exclude_euler")
    euler_flags.loc[removed_subjects] = True

    print(f"{len(removed_subjects)} subjects removed based on sitewise Euler.")
    return euler_flags, removed_subjects


def main():
    parser = argparse.ArgumentParser(
        description="Combine motion + sitewise Euler + MRIQC to derive final inclusion/exclusion."
    )
    parser.add_argument(
        "--motion-summary",
        required=True,
        help="Path to motion_summary.tsv from summarize_motion_from_confounds.py",
    )
    parser.add_argument(
        "--euler-summary",
        required=True,
        help="Path to euler_summary.tsv from extract_euler_from_freesurfer_logs.py",
    )
    parser.add_argument(
        "--iqm-outliers",
        default=None,
        help="Optional MRIQC outlier TSV with at least columns [sub, ses, exclude_mriqc].",
    )
    parser.add_argument(
        "--fd-mean-thresh",
        type=float,
        default=0.5,
        help="Exclude runs with mean FD_P above this threshold (default: 0.5 mm).",
    )
    parser.add_argument(
        "--fd-prop-thresh",
        type=float,
        default=0.30,
        help="Exclude runs with > this proportion of frames above FD_P threshold (default: 0.30).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to save included_sessions.tsv and excluded_sessions.tsv",
    )
    args = parser.parse_args()

    motion = pd.read_csv(args.motion_summary, sep="\t")
    euler = pd.read_csv(args.euler_summary, sep="\t")

    # Compute sitewise Euler exclusion at subject level
    euler_flags, euler_removed = compute_sitewise_euler_exclusion(euler)

    # Merge Euler avg_en + site onto motion (for reference), and add subject-level Euler exclusion
    merged = motion.merge(
        euler[["sub", "ses", "site", "avg_en"]],
        on=["sub", "ses"],
        how="left",
    )
    merged["exclude_euler"] = merged["sub"].map(euler_flags).fillna(False).astype(int)

    # Optional MRIQC exclusions
    if args.iqm_outliers is not None and os.path.exists(args.iqm_outliers):
        iqm = pd.read_csv(args.iqm_outliers)
        if "exclude_mriqc" not in iqm.columns:
            raise ValueError("MRIQC outliers file must have 'exclude_mriqc' column.")
        merged = merged.merge(
            iqm[["sub", "ses", "exclude_mriqc"]],
            on=["sub", "ses"],
            how="left",
        )
        merged["exclude_mriqc"] = merged["exclude_mriqc"].fillna(0).astype(int)
    else:
        merged["exclude_mriqc"] = 0

    # Apply motion + Euler + MRIQC exclusion rules
    reasons = []
    exclude_flags = []

    for _, row in merged.iterrows():
        row_reasons = []

        if row["mean_fd_p"] > args.fd_mean_thresh:
            row_reasons.append(f"mean_fd_p>{args.fd_mean_thresh}")

        if row["prop_fd_p_over_thresh"] > args.fd_prop_thresh:
            row_reasons.append(f"prop_fd_p_over_thresh>{args.fd_prop_thresh}")

        if row["exclude_euler"] == 1:
            row_reasons.append("euler_site_outlier")

        if row["exclude_mriqc"] == 1:
            row_reasons.append("mriqc_outlier")

        if row_reasons:
            exclude_flags.append(1)
            reasons.append(";".join(row_reasons))
        else:
            exclude_flags.append(0)
            reasons.append("")

    merged["exclude"] = exclude_flags
    merged["exclude_reason"] = reasons

    os.makedirs(args.output_dir, exist_ok=True)

    included = merged[merged["exclude"] == 0].copy()
    excluded = merged[merged["exclude"] == 1].copy()

    included_path = os.path.join(args.output_dir, "included_sessions.tsv")
    excluded_path = os.path.join(args.output_dir, "excluded_sessions.tsv")

    included.to_csv(included_path, sep="\t", index=False)
    excluded.to_csv(excluded_path, sep="\t", index=False)

    print(f"Wrote {len(included)} included rows to {included_path}")
    print(f"Wrote {len(excluded)} excluded rows to {excluded_path}")


if __name__ == "__main__":
    main()
