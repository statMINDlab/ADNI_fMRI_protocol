# Troubleshooting

Common problems, organized by pipeline step, and where the repo already has
tooling or notes to help. See each step's `README.md` for full detail.

## General

- **A script can't find its inputs / writes to the wrong place.** Almost every
  path is read from `config/config_adni.yaml` via `utils.config_tools`. Check the
  resolved value with, e.g., `python -m utils.config_tools paths.clinica_bids_dir`.
  Most scripts also accept `--config /path/to/other.yaml`, and many take explicit
  `--*` path overrides.
- **`ModuleNotFoundError` / wrong Python.** Activate the `env_adni` environment
  (`env/env_adni.yml`) for the utilities, QC/analysis scripts, and tests. Step 4
  (Clinica) uses the separate `env/env_clinica.yml`.

## Step 2–3 — Download & organize

- **Downloaded files don't match the collection.** Use
  `s3_organize/dicom_dowload_qc.ipynb` to reconcile the unzipped DICOM tree
  against the LONI image-collection CSV and isolate the T1w / T2w / rs-fMRI
  series.
- **Subject directory names look wrong.** `create_dicom_dir_csv.sh` only
  inventories directories matching the ADNI `NNN_S_NNNN` convention and warns
  about (skips) the rest.

## Step 4 — Clinica (DICOM→BIDS)

- **Clinica fails to convert some DICOMs.** Known, recurring Clinica DICOM
  conversion errors are catalogued in `s4_clinica/known_clinica_DICOM_errors.csv`.
- **Paths hardcoded to another cluster.** The per-subject/merge helpers resolve
  paths from the config; edit the YAML rather than the scripts.

## Step 4b — Philips SliceTiming

- **fMRIPrep skipped slice-time correction on Philips scans.** Their BOLD
  sidecars have no `SliceTiming` because dcm2niix cannot recover it from Philips
  DICOMs. Run `s4b_slice_timing/insert_philips_slicetiming.py`; the report TSV
  lists per-scan status (`written`, `unmatched`, `validation_failed`, …).

## Step 5 — Post-Clinica QC

- **Sessions missing T1w or NIfTI/JSON.** The heuristics write
  `missing_t1w.tsv` / `missing_data.tsv` (config `qc.heuristics_missing_*`)
  identifying exactly which sessions were dropped and why.

## Step 6 — MRIQC

- **Outlier detection errors about missing R packages.** `adni_outlier_pipeline.R`
  needs `tidyverse`, `rrobot`, `ggrain`, `shadowtext`, `patchwork`.
- **`shellcheck` noise in CI.** The lint job runs at `--severity=warning`; the
  existing scripts have benign info/style notes that are not failures.

## Step 7 — fMRIPrep

- **Many subjects failed in a large run.** `s7_fmriprep/fmriprep_error_report.py`
  classifies failures (CLI misuse, FreeSurfer license, OOM/timeout, missing BOLD,
  template/BIDS issues) from Slurm logs + crashfiles into a CSV, and
  `rerun_fmriprep_bold_create_job_array.sh` builds a clean rerun list of subjects
  that have BOLD on disk but no preprocessed output.
- **Re-running only some subjects/sessions.** Use `--subject-list` / `--subjects`
  (whole subjects) or `--sessions-csv` (specific sessions) on
  `run_fmriprep_bids_filter_array_all.sh`, with `--ignore-done` to redo completed
  subjects.

## Step 8 — Final QC

- **Sample-size cascade goes up between stages / final counts don't match.** If
  the pipeline was not run strictly in order, sessions can leak into a later
  stage. `collect_sample_sizes.py` chain-intersects the stages so the cascade is
  monotonic, and `finalize_inclusion.py --valid-sessions` keeps the final tables
  sequentially consistent.

Found a problem not covered here? Please open a GitHub issue.
