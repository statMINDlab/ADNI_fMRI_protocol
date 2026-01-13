# Step 8.) Final QC

This final step combines outputs from MRIQC and fMRIPrep to make inclusion/exclusion decisions for downstream analyses.

Typical tasks in this step include:

- Reviewing MRIQC group reports for obvious outliers or systematic issues.
- Inspecting fMRIPrep HTML reports for a subset of subjects, focusing on registration quality, susceptibility distortion correction, and surface reconstruction.
- Applying quantitative QC thresholds (for example, on motion, temporal SNR, or other image-quality metrics).
- Generating final inclusion/exclusion tables (for example, `included_sessions.tsv`) referenced in `config/config_adni.yaml` under `qc.*`.

The exact QC criteria will depend on your scientific goals. We recommend documenting your thresholds and decisions in a lab-specific notebook or markdown document alongside this directory so others can reproduce your final sample selection.

In addition to manual review, this directory contains small Python utilities that implement a reproducible, scriptable final-QC pipeline.

## 8.1) Summarize motion from fMRIPrep confounds

Script: `s8_final_qc/summarize_motion_from_confounds.py`

This script walks the fMRIPrep derivatives tree, reads all BOLD confounds TSVs, and computes framewise displacement and DVARS summaries at both run and timepoint level.

Inputs:

- fMRIPrep derivatives directory containing `sub-*/ses-*/func/*_desc-confounds_timeseries.tsv`.

Outputs (tab-separated, written under `--output-dir`):

- `motion_summary.tsv` – one row per `(sub, ses, task, run)` with:
  - `n_volumes`, `mean_fd_p`, `median_fd_p`, `max_fd_p`,
  - `prop_fd_p_over_thresh`, `n_fd_p_over_thresh`,
  - `mean_dvars`.
- `motion_timeseries.tsv` – per-volume metrics with:
  - `FD_P`, `DVARS`, and a binary `FD_P_over_thresh` flag.

Example usage:

```bash
python s8_final_qc/summarize_motion_from_confounds.py \
  --derivatives-dir /path/to/derivatives/fmriprep \
  --output-dir s8_final_qc
```

## 8.2) Extract Euler numbers from FreeSurfer

Script: `s8_final_qc/extract_euler_from_freesurfer.py`

This script traverses a FreeSurfer `SUBJECTS_DIR` tree, parses `recon-all.log` (or, if needed, calls `mris_euler_number`), and computes per-subject, per-session Euler numbers.

Inputs:

- `--freesurfer-dir` – FreeSurfer `SUBJECTS_DIR` used by fMRIPrep (e.g., `.../derivatives/sourcedata/freesurfer`).

Outputs:

- `euler_summary.tsv` – TSV with columns:
  - `fs_subject` – original FreeSurfer subject name.
  - `sub` – BIDS subject ID (e.g., `sub-ADNI941S7074`).
  - `ses` – BIDS session ID (e.g., `ses-M000`), or `NA` if not present.
  - `site` – 3-digit site code parsed from the subject ID.
  - `lh_en`, `rh_en`, `avg_en` – left/right/average Euler numbers.

Example usage:

```bash
python s8_final_qc/extract_euler_from_freesurfer.py \
  --freesurfer-dir /path/to/derivatives/sourcedata/freesurfer \
  --output-tsv s8_final_qc/euler_summary.tsv
```

Note: this script expects FreeSurfer utilities (e.g., `mris_euler_number`) to be available in the environment if log parsing alone is insufficient.

## 8.3) Finalize inclusion / exclusion

Script: `s8_final_qc/finalize_inclusion.py`

This script combines motion metrics, Euler-based QC, and optional MRIQC outlier flags to derive a final inclusion/exclusion decision per BOLD run.

Inputs:

- `--motion-summary` – path to `motion_summary.tsv` from `summarize_motion_from_confounds.py`.
- `--euler-summary` – path to `euler_summary.tsv` from `extract_euler_from_freesurfer.py`.
- `--iqm-outliers` (optional) – MRIQC outlier TSV with columns `[sub, ses, exclude_mriqc]`.
- `--fd-mean-thresh` – mean FD_P threshold (default: `0.5` mm).
- `--fd-prop-thresh` – proportion threshold for FD_P over cutoff (default: `0.30`).
- `--output-dir` – directory to write final inclusion/exclusion tables.

Logic (high level):

- Compute subject-level Euler outliers in a site-specific manner, flagging subjects where the transformed Euler metric exceeds a site-wise threshold.
- For each `(sub, ses, task, run)` row in the motion summary:
  - Exclude if `mean_fd_p > fd_mean_thresh`.
  - Exclude if `prop_fd_p_over_thresh > fd_prop_thresh`.
  - Exclude if subject is a sitewise Euler outlier.
  - Exclude if MRIQC flagged the session (`exclude_mriqc == 1`).
- Aggregate reasons into a semicolon-separated `exclude_reason` field.

Outputs (tab-separated, written under `--output-dir`):

- `included_sessions.tsv` – rows with `exclude == 0` and their associated metrics.
- `excluded_sessions.tsv` – rows with `exclude == 1` and an `exclude_reason` column describing why.

Example usage:

```bash
python s8_final_qc/finalize_inclusion.py \
  --motion-summary s8_final_qc/motion_summary.tsv \
  --euler-summary s8_final_qc/euler_summary.tsv \
  --iqm-outliers s8_final_qc/all_IQMs_with_QC_flags.csv \
  --fd-mean-thresh 0.5 \
  --fd-prop-thresh 0.30 \
  --output-dir s8_final_qc
```

The resulting `included_sessions.tsv` and `excluded_sessions.tsv` should be referenced under `qc.*` in `config/config_adni.yaml` and can be used as the canonical inclusion tables for downstream analyses.
