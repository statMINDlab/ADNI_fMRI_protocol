# Step 7.) fMRIPrep

This step runs [fMRIPrep](https://fmriprep.org/en/stable/index.html) on all rs-fMRI series that passed the MRIQC and earlier QC stages.

As with MRIQC, all paths and most Slurm settings are configured via `config/config_adni.yaml` and read at runtime using `utils.config_tools`.

## 7.1) Participant-level fMRIPrep (array jobs)

The main driver script is `s7_fmriprep/run_fmriprep_bids_filter_array_all_SW.sh` (or a local variant). At a high level, it:

1. Resolves the BIDS input directory, fMRIPrep derivatives directory, work directory, TemplateFlow cache directory, and container image path from `config/config_adni.yaml` (for example, `fmriprep.bids_dir`, `fmriprep.output_dir`, `fmriprep.work_dir`, `paths.templateflow_cache`, `containers.fmriprep_image`).
2. Ensures the required directories exist and writes a minimal `dataset_description.json` into the BIDS root if needed.
3. Uses the fMRIPrep Apptainer/Singularity image specified in the config.
4. Reads the subject/session heuristic CSV produced in Step 5 (for example, `paths.fmriprep_heuristics_csv`) and constructs a list of subjects to run.
5. Splits the subject list into chunks and writes one Slurm job-array script per chunk. Each array task:
   - creates a dedicated work directory and FreeSurfer subject directory,
   - runs fMRIPrep with the configured arguments (output spaces including fs-LR 91k, MNI, fsnative, fsaverage5; syn-based SDC; etc.),
   - cleans up the work directory and marks the subject as done on success.

You can generate the job arrays by running the driver script directly, or via the `Makefile` target:

```bash
make fmriprep
```

Inspect and adjust the generated `fmriprep_array_*.slurm` scripts as needed for your cluster (account, partition, wall time, memory, CPUs), then submit the ones you want to run with `sbatch`.

To check configuration and array layout without loading Apptainer or writing job scripts, use the driver in dry-run mode:

```bash
bash s7_fmriprep/run_fmriprep_bids_filter_array_all_SW.sh --config config/config_adni.yaml --dry-run
```

This prints, for each CSV chunk, which `fmriprep_array_*.slurm` script would be created and how many array entries it would contain.

## 7.2) Error analysis and reruns

Large-scale fMRIPrep runs often fail for a subset of subjects due to missing data, resource limits, or configuration issues. This repository includes utilities to help with that loop:

- `s7_fmriprep/fmriprep_error_report.py` scans Slurm logs and crash files, classifies common failure modes, and writes a CSV summary.
- `s7_fmriprep/rerun_fmriprep_bold_create_job_array.sh` reads that CSV and the BIDS/fMRIPrep trees to build a clean list of subjects that:
  - had BOLD-related failures,
  - do have BOLD data on disk,
  - do not already have preprocessed BOLD outputs.

You can then generate a rerun job array targeting only those subjects.

Now, continue on to Step 8 (`s8_final_qc/README.md`).
