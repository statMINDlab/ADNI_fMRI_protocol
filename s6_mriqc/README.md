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

or invoke it via the `Makefile` target:

```bash
make mriqc
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

Now, continue on to Step 7 (`s7_fmriprep/README.md`).
