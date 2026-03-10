#!/usr/bin/env python

import argparse
import os
import glob
import re
import subprocess
import numpy as np
import pandas as pd


def parse_sub_ses(fs_subject_name):
    """
    Parse something like 'sub-ADNI941S7074_ses-M000' into:
      sub = 'sub-ADNI941S7074'
      ses = 'ses-M000'

    If no ses is present, ses will be None.
    """
    parts = fs_subject_name.split("_")
    sub = None
    ses = None
    for p in parts:
        if p.startswith("sub-"):
            sub = p
        elif p.startswith("ses-"):
            ses = p
    if sub is None:
        sub = fs_subject_name
    return sub, ses


def parse_euler_from_log(log_file):
    """
    Parse Euler numbers from a recon-all.log file using the pattern:

      ... orig.nofix lheno <lh_value>, rheno <rh_value> ...

    Returns (lh_en, rh_en) as floats, or (None, None) if not found.
    """
    eno_line = None
    with open(log_file, "r") as f:
        for line in f:
            if re.search(r"orig\.nofix lheno", line):
                eno_line = line

    if eno_line is None:
        return None, None

    parts = eno_line.split()
    try:
        lh = float(parts[3].rstrip(","))  # remove trailing comma
        rh = float(parts[6])
    except (IndexError, ValueError):
        return None, None

    return lh, rh


def compute_euler_with_mris(fs_subject_dir):
    """
    Fallback: run mris_euler_number on lh.orig.nofix and rh.orig.nofix,
    following your original logic.
    Returns (lh_en, rh_en) as floats, or (None, None) if it fails.
    """
    lh_surf = os.path.join(fs_subject_dir, "surf", "lh.orig.nofix")
    rh_surf = os.path.join(fs_subject_dir, "surf", "rh.orig.nofix")

    if not (os.path.exists(lh_surf) and os.path.exists(rh_surf)):
        return None, None

    try:
        # Left hemisphere
        bash_cmd_l = f"mris_euler_number {lh_surf} > temp_l.txt 2>&1"
        subprocess.run(bash_cmd_l, shell=True, check=True, stdout=subprocess.PIPE)
        with open("temp_l.txt", mode="r", encoding="utf-8-sig") as f:
            lines = f.readlines()
        words = []
        for line in lines:
            line = line.strip()
            words.append([item.strip() for item in line.split(" ") if item.strip()])
        eno_l = np.float32(words[0][12])

        # Right hemisphere
        bash_cmd_r = f"mris_euler_number {rh_surf} > temp_r.txt 2>&1"
        subprocess.run(bash_cmd_r, shell=True, check=True, stdout=subprocess.PIPE)
        with open("temp_r.txt", mode="r", encoding="utf-8-sig") as f:
            lines = f.readlines()
        words = []
        for line in lines:
            line = line.strip()
            words.append([item.strip() for item in line.split(" ") if item.strip()])
        eno_r = np.float32(words[0][12])

    except Exception:
        return None, None
    finally:
        for tmp in ("temp_l.txt", "temp_r.txt"):
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    return float(eno_l), float(eno_r)


def retrieve_eulernum_from_tree(freesurfer_dir):
    """
    Walk a Freesurfer SUBJECTS_DIR tree, find all recon-all.log files, and
    extract Euler numbers per FS subject (subject/session).
    """
    log_pattern = os.path.join(freesurfer_dir, "**", "scripts", "recon-all.log")
    log_files = glob.glob(log_pattern, recursive=True)

    subjects = {}
    for lf in log_files:
        # recon-all.log is in .../<fs_subject>/scripts/recon-all.log
        fs_subject_dir = os.path.dirname(os.path.dirname(lf))
        fs_subject_name = os.path.basename(fs_subject_dir)
        subjects[fs_subject_name] = fs_subject_dir

    if not subjects:
        # Fallback: treat any dir under freesurfer_dir as a subject
        for temp in os.listdir(freesurfer_dir):
            full = os.path.join(freesurfer_dir, temp)
            if os.path.isdir(full):
                subjects[temp] = full

    subjects_list = sorted(subjects.keys())
    df = pd.DataFrame(index=subjects_list, columns=["lh_en", "rh_en", "avg_en"])
    missing_subjects = []

    for s, fs_sub in enumerate(subjects_list):
        sub_dir = subjects[fs_sub]
        log_file = os.path.join(sub_dir, "scripts", "recon-all.log")

        if os.path.exists(sub_dir):
            if os.path.exists(log_file):
                lh_en, rh_en = parse_euler_from_log(log_file)
                if lh_en is None or rh_en is None:
                    print(f"{s}: {fs_sub} log parse failed, trying mris_euler_number...")
                    lh_en, rh_en = compute_euler_with_mris(sub_dir)
            else:
                print(f"{s}: {fs_sub} missing log, trying mris_euler_number...")
                lh_en, rh_en = compute_euler_with_mris(sub_dir)

            if lh_en is not None and rh_en is not None:
                avg_en = (lh_en + rh_en) / 2.0
                df.at[fs_sub, "lh_en"] = lh_en
                df.at[fs_sub, "rh_en"] = rh_en
                df.at[fs_sub, "avg_en"] = avg_en
                print(f"{s}: {fs_sub} processed. avg_en = {avg_en}")
            else:
                missing_subjects.append(fs_sub)
                print(f"{s}: QC failed for {fs_sub}.")
        else:
            missing_subjects.append(fs_sub)
            print(f"{s}: {fs_sub} directory missing.")

    df = df.dropna()
    return df, missing_subjects


def main():
    parser = argparse.ArgumentParser(
        description="Extract Euler Characteristic from FreeSurfer recon-all logs."
    )
    parser.add_argument(
        "--freesurfer-dir",
        required=True,
        help="FreeSurfer SUBJECTS_DIR (e.g. .../derivatives/sourcedata/freesurfer)",
    )
    parser.add_argument(
        "--output-tsv",
        required=True,
        help="Output TSV path (e.g. euler_summary.tsv)",
    )
    args = parser.parse_args()

    df, missing = retrieve_eulernum_from_tree(args.freesurfer_dir)

    # Add fs_subject name as column, parse sub & ses
    df = df.copy()
    df["fs_subject"] = df.index
    subs = []
    sess = []
    for fs_sub in df["fs_subject"]:
        sub, ses = parse_sub_ses(fs_sub)
        subs.append(sub)
        sess.append(ses)
    df["sub"] = subs
    df["ses"] = sess

    # ---- ADD SITE COLUMN HERE (your code) ----
    # example: sub = 'sub-ADNI941S7074' -> sub_temp '941S7074' -> site '941'
    df["sub_temp"] = df["sub"].str.replace("sub-ADNI", "", regex=False)
    df["site"] = df["sub_temp"].astype(str).str[:3]
    df = df.drop(columns=["sub_temp"])

    # Reorder for clarity
    df = df[["fs_subject", "sub", "ses", "site", "lh_en", "rh_en", "avg_en"]]

    df.to_csv(args.output_tsv, sep="\t", index=False)
    print(f"\nWrote Euler summary for {len(df)} rows to {args.output_tsv}")

    if missing:
        print(f"\nEuler extraction failed for {len(missing)} FS subjects:")
        for m in missing:
            print(f"  - {m}")


if __name__ == "__main__":
    main()
