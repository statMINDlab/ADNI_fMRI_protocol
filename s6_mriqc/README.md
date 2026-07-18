# Step 6.) MRIQC

This step runs [MRIQC](https://mriqc.readthedocs.io/en/latest/index.html) on all rs-fMRI series that passed the post-Clinica QC in Step 5.

All paths and resource settings are read from `config/config_adni.yaml` via `utils.config_tools`. In particular, the following keys are used:

- `mriqc.bids_dir` – BIDS root input directory.
- `mriqc.output_dir` – MRIQC derivatives root (mounted as `/out`).
- `mriqc.work_dir` – MRIQC work directory (mounted as `/work`).
- `paths.mriqc_results_root` – root for scripts, logs, temporary workdirs, and `*.done` flags.
- `paths.fmriprep_heuristics_csv` – CSV with subject/session heuristics from Step 5.
- `containers.mriqc_image` – Apptainer/Singularity image path for MRIQC.

## 6.1) Participant-level MRIQC (array jobs)

The main driver script is `s6_mriqc/adni_mriqc.slurm`. It:

1. Parses an optional `--config` argument (defaulting to `config/config_adni.yaml`).
2. Resolves the BIDS root, MRIQC output and work directories, results-root, heuristics CSV, and MRIQC container image via `python -m utils.config_tools ...`.
3. Performs basic validation:
   - required config values must be non-empty,
   - the BIDS root must exist,
   - the heuristics CSV must exist.
4. Ensures results directories exist under `paths.mriqc_results_root`.
5. If `containers.mriqc_image` is set but the image file does not exist, attempts to build it via:
   - `apptainer build <image_path> docker://nipreps/mriqc:<version>`.
6. Parses the heuristics CSV to construct a list of subject IDs (one per row that passes QC and is not yet marked as done).
7. Splits the subject list into chunks of at most 499 entries and writes one job-array input file per chunk.
8. For each chunk, writes an MRIQC job-array Slurm script that you submit separately, where each array task:
   - loads `apptainer`,
   - picks the subject ID for the current `SLURM_ARRAY_TASK_ID`,
   - creates a temporary work directory under `paths.mriqc_results_root`,
   - runs MRIQC in participant mode for that subject,
   - marks the subject as done and cleans up the work directory on success.

You can run the driver script manually as:

```bash
bash s6_mriqc/adni_mriqc.slurm --config config/config_adni.yaml
```

(Adjust Slurm account, partition, and resource requests inside the generated `mriqc_array_*.slurm` scripts as needed for your cluster, or expose them via additional config keys.)

To inspect what would be run without touching Apptainer or generating job scripts, use the dry-run mode:

```bash
bash s6_mriqc/adni_mriqc.slurm --config config/config_adni.yaml --dry-run
```

This prints, for each CSV chunk, which `mriqc_array_*.slurm` script would be created and how many array entries it would contain.

## 6.2) Group-level MRIQC

After participant-level MRIQC has completed, you can run group-level MRIQC to aggregate metrics and generate group reports.

The script `s6_mriqc/mriqc_group.slurm`:

1. Loads `apptainer`.
2. Resolves `mriqc.bids_dir`, `mriqc.output_dir`, and `containers.mriqc_image` using `python -m utils.config_tools ...`.
3. Verifies that all three values are non-empty.
4. Runs MRIQC in group mode:

```bash
sbatch s6_mriqc/mriqc_group.slurm
```

You can perform a dry-run of the group-level step (no Apptainer call) by setting `MRIQC_DRY_RUN=1` in the submission environment, for example:

```bash
sbatch --export=ALL,ADNI_CONFIG=config/config_adni.yaml,MRIQC_DRY_RUN=1 s6_mriqc/mriqc_group.slurm
```

The group-level outputs (when not in dry-run) are written under `mriqc.output_dir` as configured in `config/config_adni.yaml`.

## 6.3) Post-MRIQC outlier detection

`s6_mriqc/adni_outlier_pipeline.R` performs the robust, automated outlier
detection on the MRIQC image-quality metrics (IQMs) and produces the per-session
QC flags used to include/exclude sessions, plus the supplemental QC figures.
(It replaces the earlier `outlier_mriqc.R` and `reverse_scale_IQMs.R` scripts:
the tail-aware threshold below handles "lower-is-worse" metrics directly, so the
separate reverse-scaling step is no longer needed.)

**Requires R** with the packages `tidyverse`, `rrobot` (`SHASH_out()` /
`normal_to_SHASH()`), `ggrain`, `shadowtext`, and `patchwork`.

### Inputs

Two wide MRIQC group tables, one row per session, one column per IQM, with the
id columns `participant_id` and `ses_id`:

- `mriqc.group_bold_tsv` – BOLD IQMs (default `.../results/mriqc/group_bold_full.tsv`).
- `mriqc.group_t1w_tsv` – T1w IQMs (default `.../results/mriqc/group_T1w_full.tsv`).

These are the aggregated MRIQC metrics (from the group-level step / MRIQC's
`group_*.tsv`). Like the rest of the pipeline, the paths are read from
`config/config_adni.yaml` (via `utils.config_tools`); each can be overridden on
the command line (see *Running* below). Outputs are written to the directory in
`paths.mriqc_results_root` (override with `--out-dir`).

### Method

For each IQM, a Sinh-Arcsinh (SHASH) distribution is fit to the finite values via
`rrobot::SHASH_out()`, and the threshold is taken at the ±4 standardized SHASH
cut on the original data scale (`compute_thresh()`). Each metric is fit on the
appropriate tail:

- **Upper tail** (flag high values): T1w `cjv`, `efc`, `fwhm_avg`; BOLD `aor`,
  `aqi`, `efc`, `fd_mean`, `dvars_std`, `fwhm_avg`.
- **Lower tail** (flag low values): T1w `cnr`, `snr_total`, `tpm_overlap_{csf,gm,wm}`;
  BOLD `snr`, `tsnr`.

A session is flagged for a group (`excluded_<group>`) if it is an outlier on
**any** metric in that group; these are combined into `excluded_any` /
`qc_status_any` (`included` / `excluded`).

### Outputs

- **`all_IQMs_with_QC_flags_clean.tsv`** – one row per session (`sub`, `ses`),
  all IQM values, per-group `excluded_*` booleans, and `excluded_any` /
  `qc_status_any`. This is the per-session inclusion table consumed downstream
  (see Step 8).
- **`supplemental_outlier_examples.csv`** – two example outlier sessions per
  metric (one random, one nearest the threshold), for the supplemental figures.
- **`T1w_IQMs_rainclouds.pdf`** / **`BOLD_IQMs_rainclouds.pdf`** – the raincloud
  figures. On them: grey = within threshold, red = outlier for that metric, blue
  = a chosen example session.
- `s6_mriqc/example_outliers/` holds the report SVGs (carpet plots / recon-all
  surfaces) for the chosen example sessions alongside their CSV.

All four outputs are written into the output directory
(`paths.mriqc_results_root`, or `--out-dir`).

### Running

Paths come from `config/config_adni.yaml`, so with the config filled in the
script runs start-to-finish headless:

```bash
Rscript s6_mriqc/adni_outlier_pipeline.R --config config/config_adni.yaml
```

Any path can be overridden without editing the config:

```bash
Rscript s6_mriqc/adni_outlier_pipeline.R \
  --bold-tsv /path/to/group_bold_full.tsv \
  --t1w-tsv  /path/to/group_T1w_full.tsv \
  --out-dir  /path/to/outputs
```

The script also previews each raincloud panel, so it can equally be sourced
interactively in RStudio (set the same arguments, or the config defaults, first).

Now, continue on to Step 7 (`s7_fmriprep/README.md`).
