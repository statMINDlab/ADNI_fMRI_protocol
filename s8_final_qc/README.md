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
- `--iqm-outliers` (optional) – MRIQC QC table with `[sub, ses]` plus an exclusion
  flag. Accepts an `exclude_mriqc` column, or derives it from the
  `adni_outlier_pipeline.R` outputs `excluded_any` / `qc_status_any`, so the
  Step-6 QC table can be used directly.
- `--valid-sessions` (optional) – table with `[sub, ses]` listing the sessions
  that legitimately reached final QC (e.g. the sequential fMRIPrep survivors from
  `collect_sample_sizes.py --dump-stage fmriprep`). Motion-summary rows not in
  this list are **dropped from both output tables**, because they were excluded
  at an earlier stage rather than at final QC. Use this to keep the final tables
  sequentially consistent when the pipeline was not run strictly in order.
- `--fd-mean-thresh` – mean FD_P threshold (default: `0.5` mm).
- `--fd-prop-thresh` – proportion threshold for FD_P over cutoff (default: `0.30`).
- `--output-dir` – directory to write final inclusion/exclusion tables.

Logic (high level):

- Compute subject-level Euler outliers in a site-specific manner, flagging subjects where the transformed Euler metric exceeds a site-wise threshold.
- If `--valid-sessions` is given, restrict the motion summary to those sessions first.
- For each `(sub, ses, task, run)` row in the motion summary:
  - Exclude if `mean_fd_p > fd_mean_thresh`.
  - Exclude if `prop_fd_p_over_thresh > fd_prop_thresh`.
  - Exclude if subject is a sitewise Euler outlier.
  - Exclude if MRIQC flagged the session (`exclude_mriqc == 1`).
- Aggregate reasons into a semicolon-separated `exclude_reason` field.

> Sequential note: when `--valid-sessions` restricts the universe to the
> post-MRIQC survivors, no remaining session is an MRIQC outlier, so the final
> exclusions are Euler + motion only — matching the "Final QC = Euler number,
> motion" stage in the sample-size table (§8.4). MRIQC exclusions are then
> attributed to the Post-MRIQC QC stage, not Final QC.

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

## 8.4) Pipeline sample-size table

The "how many subjects/sessions are kept and dropped at each stage" table (for
the README, the manuscript, or slides) is produced by two small scripts that
share one manifest, `s8_final_qc/sample_size_stages.tsv` (config `sample_size.*`):

- **`collect_sample_sizes.py`** derives the per-stage counts *from the real
  pipeline outputs* and writes them into the manifest.
- **`make_sample_size_table.py`** renders the manifest as Markdown / HTML / CSV.

### Deriving the counts (`collect_sample_sizes.py`)

Each stage is represented as a **set of `(sub, ses)` BIDS ids**, so subjects and
sessions kept are the size of that set and the "Dropped" counts are set
differences. A subject is counted as dropped at the stage where their last
surviving session disappears.

| Stage | id-set source |
| --- | --- |
| Start | every session in the Step-5 mastersheet (`sample_size.mastersheet_csv`) |
| BIDS via Clinica | Step-5 `SessionFilterPipeline` phase-0 survivors (BIDS errors, missing NIfTI/JSON, missing T1w) |
| Post-Clinica QC | Step-5 pipeline final survivors (TR / scan-depth / duration / FOV / coil) |
| MRIQC | Step-5 survivors **that have MRIQC output** — the drop is exactly "in Step-5 output but not in MRIQC" (`mriqc_iqms_table`) |
| Post-MRIQC QC | MRIQC rows with `mriqc_exclude_col == 0` |
| fMRIPrep | sessions fMRIPrep completed (`fmriprep_sessions_table`, e.g. `motion_summary.tsv`) |
| Final QC | `final_inclusion_table` (`included_sessions.tsv`) |

```bash
# Derive counts from the pipeline outputs and update the manifest:
python s8_final_qc/collect_sample_sizes.py --config config/config_adni.yaml

# Preview without writing the manifest:
python s8_final_qc/collect_sample_sizes.py --print-only
```

Run this with the `env_adni` environment active (it imports the Step-5 pipeline).
For an exact monotonic cascade, the mastersheet, MRIQC, fMRIPrep, and inclusion
tables should all come from the **same data run**; the script prints a note for
each session that a downstream table gains relative to the previous stage (a sign
the inputs are from different snapshots).

### Rendering the table (`make_sample_size_table.py`)

Reads the manifest and writes the table. The `Dropped (Sub/Ses)` column is derived
as the drop from the previous stage, so it is always internally consistent. You
can also hand-edit the manifest (or set a row's `count_from` to a `sub`/`ses`
table to auto-count just that row) if you are not using the collector.

```bash
# Markdown to stdout (paste into a README):
python s8_final_qc/make_sample_size_table.py

# Styled HTML you can screenshot for a paper/slide:
python s8_final_qc/make_sample_size_table.py --format html --output s8_final_qc/sample_size_table.html

# CSV:
python s8_final_qc/make_sample_size_table.py --format csv --output s8_final_qc/sample_size_table.csv
```

