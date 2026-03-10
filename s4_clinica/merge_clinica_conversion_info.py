#!/usr/bin/env python3
"""
merge_modalities.py

Merge modality TSV files across subdirectories.

Usage:
    python merge_modalities.py \
        --root conversion_info \
        --out merged_outputs \
        --modalities t1_paths.tsv flair_paths.tsv fmap_paths.tsv fmri_paths.tsv dti_paths.tsv

If --out is not provided, merged files are written in the root directory.
"""

import argparse
import csv
from pathlib import Path
from typing import List
import pandas as pd
import sys

def find_subdirs(root: Path) -> List[Path]:
    # Only immediate children that are directories and look like v*
    subdirs = [p for p in sorted(root.iterdir()) if p.is_dir() and p.name.startswith("v")]
    return subdirs

def read_header_tsv(tsv_path: Path) -> List[str]:
    # Read only the header line safely; return [] if file doesn't exist or has no header
    try:
        with tsv_path.open("r", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            for row in reader:
                # skip empty lines until we find header row
                if not row:
                    continue
                return [c for c in row]
    except FileNotFoundError:
        return []
    except StopIteration:
        return []
    except Exception as e:
        print(f"Warning: couldn't read header from {tsv_path}: {e}", file=sys.stderr)
        return []

def build_master_columns(files: List[Path]) -> List[str]:
    master = []
    seen = set()
    for f in files:
        hdr = read_header_tsv(f)
        if not hdr:
            continue
        for c in hdr:
            if c not in seen:
                seen.add(c)
                master.append(c)
    return master

def merge_modality_files(root: Path, outdir: Path, modality_fname: str, subdirs: List[Path]):
    files = [sd / modality_fname for sd in subdirs if (sd / modality_fname).exists()]
    if not files:
        print(f"No files found for modality '{modality_fname}'. Skipping.")
        return

    print(f"Found {len(files)} files for {modality_fname}. Scanning headers to build master column list...")

    master_cols = build_master_columns(files)
    if not master_cols:
        print(f"No headers found for {modality_fname}. Skipping.")
        return

    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / modality_fname.replace(".tsv", f"_merged.tsv")
    first_write = True

    print(f"Master columns for {modality_fname}: {master_cols}")
    # Second pass: read each file with pandas, reindex, write or append
    for f in files:
        try:
            # Read TSV; if file might be huge, consider chunksize
            df = pd.read_csv(f, sep="\t", dtype=str, na_filter=False)  # keep everything as str, replace NaN with ''
        except pd.errors.EmptyDataError:
            print(f"Warning: {f} is empty. Skipping.")
            continue
        except Exception as e:
            print(f"Warning: failed reading {f}: {e}. Skipping.")
            continue

        # Ensure columns are strings; if the file has no columns (empty) skip
        if df.columns.size == 0:
            print(f"Warning: {f} has no columns. Skipping.")
            continue

        # Reindex to master columns; missing columns will be created with empty strings
        df = df.reindex(columns=master_cols, fill_value="")

        # Write (header only first time)
        if first_write:
            df.to_csv(out_path, sep="\t", index=False, header=True, mode="w")
            first_write = False
            print(f"Wrote header and {len(df)} rows from {f} to {out_path}")
        else:
            df.to_csv(out_path, sep="\t", index=False, header=False, mode="a")
            print(f"Appended {len(df)} rows from {f} to {out_path}")

    print(f"Done merging modality '{modality_fname}'. Output: {out_path}\n")

def main():
    parser = argparse.ArgumentParser(description="Merge modality TSVs across v* subdirectories.")
    parser.add_argument("--root", required=True, help="Root directory containing v* subdirectories (e.g. conversion_info)")
    parser.add_argument("--out", default=None, help="Output directory for merged TSVs. Defaults to root.")
    parser.add_argument("--modalities", nargs="+", required=False,
                        default=["t1_paths.tsv", "flair_paths.tsv", "fmap_paths.tsv", "fmri_paths.tsv", "dti_paths.tsv"],
                        help="List of modality filenames to merge.")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists() or not root.is_dir():
        print(f"Error: root directory {root} doesn't exist or is not a directory.", file=sys.stderr)
        sys.exit(2)

    outdir = Path(args.out) if args.out else root
    subdirs = find_subdirs(root)
    if not subdirs:
        print(f"No v* subdirectories found under {root}. Nothing to do.", file=sys.stderr)
        sys.exit(0)

    print(f"Found {len(subdirs)} subdirectories to scan.")

    for modality in args.modalities:
        merge_modality_files(root, outdir, modality, subdirs)

if __name__ == "__main__":
    main()
