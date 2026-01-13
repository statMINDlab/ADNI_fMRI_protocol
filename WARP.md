# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Repository purpose and scope

This project implements a reproducible pipeline for ADNI 2 / GO / 3 resting-state fMRI, from LONI downloads through DICOM→NIfTI+BIDS (Clinica), MRIQC, fMRIPrep, and multiple QC stages. The end product is preprocessed rs-fMRI in fs-LR 91k (plus MNI, fsnative, fsaverage5) along with inclusion/exclusion tables for downstream analyses.

ADNI 1 is excluded (no rs-fMRI) and ADNI 4 is currently out of scope (Clinica support pending).

The top-level README describes the protocol as 8 steps, each with its own subdirectory `s1_…`–`s8_…` and README. Many steps have both manual (LONI web UI, QC decisions) and scripted components.

## Key commands and entry points

### Configuration

- Central config: `config/config_adni.yaml`
  - Defines ADNI phases/modalities, all important data paths (raw zips, DICOM tree, Clinica BIDS, derivatives), container locations, and Slurm defaults.
  - Most scripts and the `Makefile` assume you customize this file rather than hardcoding paths.

### Make targets (high-level orchestration)

The `Makefile` is a thin wrapper over step-specific scripts, parameterized by `CONFIG` (defaults to `config/config_adni.yaml`). These targets assume that referenced `run_*.sh` scripts exist and are executable.

- Run all automated steps (3–8):
  - `make all`
- Individual steps:
  - `make step1` – prints instructions; step is fully manual (account setup, DUA), see `s1_setup_account/README.md`.
  - `make step2` or `make download` – prints instructions; step is manual in the LONI IDA UI, see `s2_download/README.md`.
  - `make step3` or `make organize` – calls `bash s3_organize/run_s3_organize.sh --config config/config_adni.yaml` to unzip, organize, and QC the download.
  - `make step4` or `make clinica` – calls `bash s4_clinica/run_clinica_adni2bids.sh --config config/config_adni.yaml` to run Clinica ADNI→BIDS conversion.
  - `make step5` or `make post_clinica_qc` – calls `bash s5_post_clinica_qc/run_post_clinica_qc.sh --config config/config_adni.yaml` for post-Clinica QC.
  - `make step6` or `make mriqc` – calls `bash s6_mriqc/run_mriqc_array.sh --config config/config_adni.yaml` to run MRIQC (participant/group); assumes Slurm or equivalent.
  - `make step7` or `make fmriprep` – calls `bash s7_fmriprep/run_fmriprep_array.sh --config config/config_adni.yaml` to run fMRIPrep via Slurm/containers.
  - `make step8` or `make final_qc` – calls `bash s8_final_qc/run_final_qc.sh --config config/config_adni.yaml` to perform final QC and generate inclusion/exclusion tables.
- Helpers:
  - `make clean_workdirs` – deletes hardcoded MRIQC and fMRIPrep work dirs under `/scratch/adni/...` (edit paths before using).
  - `make status` – placeholder that could be wired to a future `utils/print_pipeline_status.py`.

### Environment and dependencies

- Primary analysis environment: `env/env_adni.yml` (Python 3.11, scientific stack, PyYAML, pytest). Create and activate this before running most Python utilities, tests, or QC code.
- Clinica environment: `env/env_clinica.yml` (Python 3.10, `dcm2niix`, `clinica`). Use this when installing and running Clinica for Step 4 if you prefer isolating Clinica dependencies from the main analysis environment.
- Post-Clinica QC analysis has its own Python dependencies listed in `s5_post_clinica_qc/analysis/requirements.txt` (pandas, numpy, pydicom, nibabel, tqdm, plotly). Install these into the active environment before running the analysis scripts.

### Config helper and Python utilities

- Central config helper: `utils/config_tools.py`.
  - From Python: `from utils.config_tools import load_config, get_value`; `cfg = load_config()` (uses `$ADNI_CONFIG` if set, otherwise `config/config_adni.yaml`), then `get_value(cfg, "fmriprep.bids_dir")`.
  - From shell: `python -m utils.config_tools paths.raw_dicom_dir` or `python -m utils.config_tools fmriprep.bids_dir --config /path/to/config.yaml`. Scalars are printed as plain text; lists/dicts as JSON.
  - Most Slurm and shell wrappers in `s3_…`, `s4_…`, `s5_…`, `s6_…`, and `s7_…` call this module instead of hardcoding paths.
- Environment variable `ADNI_CONFIG` can be set to point scripts and tests at an alternate YAML without editing code.

### Step-specific scripts and one-off commands

These are the main non-Makefile entry points that future agents are likely to use or modify.

#### Step 3 (organize DICOMs)

- `s3_organize/create_dicom_dir_csv.sh`
  - Loops over the unzipped DICOM directory tree and writes a `dicom_dirs.csv` index of subject / scan / date directories.
  - Assumes you `cd` into the root of the unzipped DICOM tree and edit the hardcoded `cd /path/to/unzipped/dicom/directories/` line.
- `s3_organize/dicom_dowload_qc.ipynb`
  - Jupyter notebook to compare unzipped dicom directories against LONI CSVs and isolate modalities of interest (T1w, T2w, rs-fMRI).

#### Step 4 (Clinica on HPC)

- `s4_clinica/create_slurm_script_per_sub.sh`
  - Given a text file `adni_subs.txt` with one subject ID per line and a base Slurm template `adni_clinica.slurm`, creates per-subject Slurm scripts by copying and sed-rewriting job names, log names, and subject lists.
  - Paths inside are currently hardcoded to `/N/project/statadni/...` and will likely need editing for a different cluster.
- `s4_clinica/adni_submit_slurm.sh`
  - Submits all per-subject Clinica jobs listed in `adni_subs.txt` via `sbatch`.
- `s4_clinica/merge_individual_clinica.sh`
  - Merges individual Clinica BIDS outputs (`BIDS_individual/`) into a single shared `BIDS_all/` directory and concatenates Clinica `conversion_info/v0/*_paths.tsv` across subjects.
  - Heavily path-dependent and assumes a pre-existing `/N/project/statadni/...` layout.

#### Step 5 (post-Clinica QC data assembly)

All code for assembling QC master tables lives under `s5_post_clinica_qc/analysis/create_mastersheet/`.

- Entry point: `s5_post_clinica_qc/analysis/create_mastersheet/main.py`
  - Run from that directory after installing `requirements.txt`.
  - Builds an "anchor" table joining Clinica `fmri_paths.tsv` metadata to filesystem paths; parses DICOM headers and BIDS NIfTI+JSON headers; and augments with structural MRI summary metrics. Outputs CSVs under `s5_post_clinica_qc/analysis/create_mastersheet/data/`.
- Core components:
  - `parsers/path_strategies/*.py`
    - `DefaultFlatStrategy` assumes a single Clinica `conversion_info` root containing versioned `v*/fmri_paths.tsv`, and infers BIDS NIfTI/JSON paths based on ADNI subject/session conventions.
    - `PerSubjectStrategy` handles cases where each subject has its own `conversion_info` directory under multiple `sourcedata` trees.
  - `parsers/anchors.AnchorTable`
    - Uses a `PathStrategy` to load and deduplicate multiple Clinica `fmri_paths.tsv` versions per subject/session; caches a consolidated `anchor_df.csv` and hash for change detection.
  - `parsers/dicom_parser.DICOMMetadata`
    - Reads one representative DICOM per directory with `pydicom` (metadata only, no pixel data) and exposes a `dicom_*`-prefixed dictionary.
  - `parsers/nifti_parser.NiftiParser`
    - Loads NIfTI headers via nibabel and associated BIDS JSON, normalizes them to serializable types, and prefixes keys as `nifti_*` / `json_*`.
  - `config/dicom_fields.py`
    - Controls which DICOM metadata fields are extracted (`dcm_keep_fields`) vs an extended list (`dcm_all_fields`).
  - `parsers/structural_probe.StructuralProbe`
    - Given the merged DICOM+NIfTI table, walks back from each `NIfTI_path` to the session directory, searches modality-specific subfolders (default `anat/`), and records presence plus basic header metrics (dims, voxel sizes) for modalities like `T1w` and `FLAIR`.

The downstream QC reporting notebook and helper scripts live under `s5_post_clinica_qc/analysis/create_report/` and `s5_post_clinica_qc/post_clinica_qc.ipynb`. They consume the master CSVs above and implement heuristics to decide which sessions proceed to MRIQC/fMRIPrep and write tables referenced in `config/config_adni.yaml` under `qc.*`.

#### Step 7 (fMRIPrep orchestration and error analysis)

- `s7_fmriprep/run_fmriprep_bids_filter_array_all_SW.sh`
  - Monolithic Slurm+Apptainer driver script tailored to a specific cluster.
  - Responsibilities:
    - Sets BIDS input (`idir`), fMRIPrep derivatives output (`odir`), working directories, and CSV of subject/session heuristics.
    - Ensures required directories and TemplateFlow cache, builds or reuses a Singularity/Apptainer image from the `nipreps/fmriprep` Docker image.
    - Creates a minimal `dataset_description.json` in the BIDS root and writes a FreeSurfer license to `odir/license.txt` (you will likely want to replace this with your own license handling).
    - Parses a heuristics CSV to build a list of subject IDs, splits into chunks ≤499 for Slurm job arrays, and writes one `fmriprep_array_*.slurm` script per chunk.
    - Each Slurm script uses an array over subject IDs, allocates cores/memory/time, creates a unique Apptainer workdir and FreeSurfer subject dir, and runs fMRIPrep with a fixed set of arguments (syn-based SDC, 91k CIFTI, multiple output spaces, TemplateFlow bind mounts, `--skip-bids-validation`, etc.).
  - Submission lines (`sbatch`) are currently commented out; adjust Slurm options and uncomment/submit as appropriate for your environment.
- `s7_fmriprep/fmriprep_error_report.py`
  - Standalone Python tool to classify fMRIPrep errors from Slurm logs and crashfiles and optionally cross-check BOLD existence in the BIDS tree.
  - Key usage pattern (from the module docstring):
    - `python fmriprep_error_report.py --logs /path/to/logs --crashes /path/to/derivatives/fmriprep --bids /path/to/BIDS_root --out /path/to/report.csv`
  - Implementation details:
    - Scans log and crash files for a library of regex patterns (CLI misuse, FreeSurfer license issues, OOM/timeouts, BIDS/template problems, missing BOLD, etc.) and emits a CSV with `source`, `file`, `subject`, `session`, `category`, and `detail`.
    - Uses filesystem checks under `--bids` to refine "no BOLD" errors into categories such as "no BOLD for subject", "session has no BOLD", or "BOLD exists in other sessions but was filtered out".
- `s7_fmriprep/rerun_fmriprep_bold_create_job_array.sh`
  - Consumes the classifier’s output CSV and the BIDS tree to construct a clean list of subjects that: (a) had BOLD-related failures, (b) do have BOLD data on disk, and (c) do not already have preprocessed BOLD outputs in derivatives.
  - Writes several helper lists under `s7_fmriprep/.../results/scripts/` and prints summary counts; intended as input for a rerun job array.
- `s7_fmriprep/explore_fmriprep_errors.ipynb`
  - Notebook for manual exploration of fMRIPrep failure modes using the above CSVs.

### Quick debug runs for MRIQC and fMRIPrep

For debugging or small test runs, you can invoke the MRIQC and fMRIPrep drivers directly instead of going through the `Makefile`:

- MRIQC participant-level driver (generates job arrays based on the heuristics CSV):
  - `bash s6_mriqc/adni_mriqc.slurm --config config/config_adni.yaml`
  - Then inspect the generated `mriqc_array_*.slurm` scripts under the configured MRIQC results root and submit selected arrays with `sbatch`.
- MRIQC group-level aggregation (after participant jobs finish):
  - `sbatch s6_mriqc/mriqc_group.slurm`
- fMRIPrep participant-level driver:
  - `bash s7_fmriprep/run_fmriprep_bids_filter_array_all_SW.sh --config config/config_adni.yaml`
  - As with MRIQC, this writes one or more `fmriprep_array_*.slurm` scripts; submit only the subjects or arrays you care about while debugging.

### Tests

There is a pytest-based test suite under `utils/tests` that focuses on configuration wiring and HPC script behavior:

- `utils/tests/test_config_tools.py` exercises loading and querying the YAML config via `utils.config_tools`, including its CLI entry point (`python -m utils.config_tools ...`).
- `utils/tests/test_create_dicom_dir_csv.py` verifies that `s3_organize/create_dicom_dir_csv.sh` reads `paths.raw_dicom_dir` from config and writes a well-formed `dicom_dirs.csv`.
- `utils/tests/test_clinica_scripts.py` covers the Clinica helpers `s4_clinica/create_slurm_script_per_sub.sh` and `s4_clinica/merge_individual_clinica.sh`, checking both error paths (missing config values) and basic merge behavior.
- `utils/tests/test_create_mastersheet_main.py` checks that `s5_post_clinica_qc/analysis/create_mastersheet/main.py` fails clearly when configured paths are invalid (and includes a skipped smoke test stub for a full run with patched parsers).
- `utils/tests/test_run_session_heuristics.py` smoke-tests `s5_post_clinica_qc/analysis/create_report/run_session_heuristics.py`, ensuring it produces the expected TSVs and grouped per-subject CSV.
- `utils/tests/test_mriqc_scripts.py` adds lightweight integration tests for `s6_mriqc/adni_mriqc.slurm` and `s6_mriqc/mriqc_group.slurm`, using stub `module`/`apptainer` binaries to validate config handling, required-key enforcement, image-building behavior, and BIDS-root checks.
- `utils/tests/test_fmriprep_scripts.py` mirrors the MRIQC tests for `s7_fmriprep/run_fmriprep_bids_filter_array_all.sh` and `s7_fmriprep/rerun_fmriprep_bold_create_job_array.sh`, including rerun-list generation from an error report.

Typical commands from the repository root (with the `env/env_adni.yml` environment active):

- Run all tests:
  - `pytest`
  - or `make test` (wrapper around `pytest`).
- Run tests in a single file:
  - `pytest utils/tests/test_config_tools.py`
- Run a single test:
  - `pytest utils/tests/test_config_tools.py::test_cli_outputs_scalar_value`
- Lint Python and shell/Slurm scripts:
  - `make lint` (runs `ruff check .` and `shellcheck` on tracked `*.sh`/`*.slurm` files).

## High-level architecture

### Overall pipeline

The repository is organized around an 8-step pipeline, with a mixture of manual and automated operations:

1. **Account & Access (`s1_setup_account/`)**
   - Manual registration with LONI / ADNI; no code.
2. **Build & Download Collection (`s2_download/`)**
   - Manual image/study selection and download via LONI IDA, documented with screenshots.
3. **Unzip, organize, and QC download (`s3_organize/`)**
   - Shell scripts and notebooks to move downloaded archives into a consistent directory tree, unzip them, build a DICOM directory index, and reconcile against LONI CSVs.
4. **Clinica (DICOM→NIfTI+BIDS) (`s4_clinica/`)**
   - Instructions for installing `dcm2niix` and Clinica, plus Slurm helpers to create per-subject Clinica jobs, submit them in parallel, and post-hoc merge individual BIDS outputs.
5. **Post-Clinica QC (`s5_post_clinica_qc/`)**
   - Python analysis package + notebooks that:
     - Ingest Clinica `conversion_info` tables (`fmri_paths.tsv`), DICOM directories, and BIDS NIfTI/JSON files.
     - Construct a canonical "anchor" table per subject/session (one row per rs-fMRI series), with normalized ADNI subject IDs and session codes.
     - Attach DICOM header features, NIfTI+JSON metadata, and structural MRI header features.
     - Feed this combined table into a QC notebook that applies heuristics and writes subject/session lists and QC decision tables consumed by MRIQC/fMRIPrep.
6. **MRIQC (`s6_mriqc/`)**
   - README placeholder; Makefile expects a `run_mriqc_array.sh` wrapper that uses MRIQC-related config fields in `config/config_adni.yaml` and Slurm to run participant and group-level analyses.
7. **fMRIPrep (`s7_fmriprep/`)**
   - Cluster-specific job-array orchestration scripts and error-analysis utilities, with Apptainer/Singularity used to run nipreps/fMRIPrep containers against the BIDS dataset and write derivatives to a configured `output_dir`.
8. **Final QC (`s8_final_qc/`)**
   - Documentation placeholder and integration point for making final inclusion/exclusion decisions based on MRIQC metrics, fMRIPrep reports, and earlier QC outputs; expected to produce `included_sessions.tsv` and related tables referenced under `qc.*` in `config/config_adni.yaml`.

### Configuration-driven design

- `config/config_adni.yaml` is the single source of truth for:
  - **ADNI selection** (phases, modalities, study CSVs).
  - **Filesystem layout** (raw downloads, Clinica BIDS, MRIQC/fMRIPrep derivatives, logs/QC tables, work directories).
  - **Containers and licenses** (paths to MRIQC/fMRIPrep images, FreeSurfer license).
  - **HPC scheduler defaults** (account, partition, time/memory/CPU for MRIQC and fMRIPrep arrays).
  - **Downstream QC tables** (paths to post-Clinica and MRIQC QC tables and final inclusion/exclusion TSVs).
- Helper module `utils/config_tools.py` is used throughout the shell and Slurm wrappers to read this YAML, either via direct import in Python or via `python -m utils.config_tools ...` from bash; many scripts also honor `$ADNI_CONFIG` for pointing at alternate configs.

Future changes to paths or resource settings should generally flow through this YAML, with wrapper scripts reading from it rather than hardcoding cluster-specific paths.

### Post-Clinica analysis code structure

Within `s5_post_clinica_qc/analysis/create_mastersheet/` the code is organized as a small library to be reused or extended:

- **Path strategies** abstract over how Clinica `conversion_info` is stored (`default_flat` vs `per_subject`).
- **AnchorTable** loads, deduplicates, and augments Clinica path tables, caching both the derived CSV and a hash to avoid unnecessary recomputation.
- **Parsers** for DICOM and NIfTI/JSON encapsulate IO and metadata normalization, emitting flat dictionaries suitable for DataFrame construction.
- **StructuralProbe** is intentionally modality-agnostic and only depends on BIDS naming and folder layout; it can be reused if new structural modalities or metrics are added.

When extending the QC feature set (e.g., new DICOM fields, new MRI-derived metrics), prefer to add fields in `config/dicom_fields.py` and/or extend `StructuralProbe` rather than scattering ad hoc parsing logic.

### Error-analysis and rerun loop for fMRIPrep

The `s7_fmriprep` directory encodes a feedback loop for handling large-scale fMRIPrep runs:

1. Launch a large job array over subjects using a containerized fMRIPrep script (e.g., `run_fmriprep_bids_filter_array_all_SW.sh` or a derivative using `config/config_adni.yaml`).
2. Collect Slurm logs and fMRIPrep crashfiles.
3. Run `fmriprep_error_report.py` to categorize failures and produce a CSV of issues by subject/session.
4. Use `rerun_fmriprep_bold_create_job_array.sh` to compute a clean set of subjects that both have BOLD on disk and lack preprocessed outputs, and to generate rerun input lists.
5. Submit rerun job arrays targeting only those problematic subjects.

This loop is central to scaling fMRIPrep across many ADNI sessions while systematically identifying missing data, configuration errors, or resource problems.

## Notes for future agents

- The codebase assumes access to an HPC scheduler (primarily Slurm) and container runtime (Apptainer/Singularity). When adapting scripts for a different environment, pay attention to:
  - Bind-mounted paths (`--bind` flags) matching `config/config_adni.yaml`.
  - Workdir and derivatives paths being writable and large enough for intermediate files.
  - FreeSurfer license management: avoid hardcoding license contents in new scripts; bind an external license file instead.
- When modifying or adding pipeline steps, keep the 8-step structure and the central role of `config/config_adni.yaml` in mind so that new components can be orchestrated via the `Makefile` and/or future wrappers.
