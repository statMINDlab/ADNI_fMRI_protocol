# Step 5.) Post-Clinica Quality Control

This step generates a quality report on the data after running Clinica. We provide insight into the heuristics we chose for including subjects based on scan parameters pulled from the DICOM and BIDS headers. The report also summarizes errors (for example, why Clinica failed for some subjects).

You first need to run the script that pulls parameters from the DICOM files and maps this information to the Clinica BIDS output.

The entry point is `create_mastersheet/main.py`. It is now fully config-driven:

1. Ensure `config/config_adni.yaml` has the correct paths for your Clinica `conversion_info` tables, BIDS root, and output locations used by the master-sheet code.
2. Install the required Python libraries into your active environment:
   - `cd s5_post_clinica_qc/analysis`
   - `pip install -r requirements.txt` (or `conda install --file requirements.txt`).
3. From `s5_post_clinica_qc/create_mastersheet/`, run:
   - `python main.py --config ../../config/config_adni.yaml`

The script will take a few minutes to run because it needs to read representative DICOMs and NIfTI+JSON headers.

Once it has finished, there will be four files in `create_mastersheet/data/`:

- `anchor_plus_dicom_nifti_struct.csv`
- `anchor_df.csv`
- `anchor_hash.txt`
- `anchor_plus_dicom.csv`


Now you can run the report code to summarize the data and decide which subjects to pass on to the next steps.

## Heuristics script and outputs

The recommended entry point for running heuristics is the script:

- `create_report/run_session_heuristics.py`

This script wraps the `SessionFilterPipeline` used in the notebook and produces three standardized outputs:

- `s5_post_clinica_qc/create_report/outputs/missing_t1w.tsv`
  - All rows dropped by the T1-weighted image existence heuristic.
- `s5_post_clinica_qc/create_report/outputs/missing_data.tsv`
  - All rows dropped because required NIfTI or JSON files are missing after Clinica conversion.
- `s5_post_clinica_qc/create_report/outputs/final_heuristics.tsv`
  - The final per-session table after all heuristics; this is what MRIQC uses (via `qc.heuristics_final_table` in `config/config_adni.yaml`).

The same script can also emit a per-subject sessions CSV used by fMRIPrep. For example:

```bash
cd s5_post_clinica_qc/create_report
python run_session_heuristics.py \
  --input-csv ../create_mastersheet/data/statadni/anchor_plus_dicom_nifti_struct.csv \
  --output-dir ./outputs \
  --fmriprep-subjects-csv /N/project/statadni/20250922_Saige/fmriprep/slurm/final_heuristics_applied_all_subjects_sessions_grouped_CLEAN.csv \
  --phase-limit 2
```

That command:

- Runs all configured heuristics (phases 0–2).
- Writes the three TSVs listed above under `./outputs/`.
- Writes a grouped `Subject_ID,sessions` CSV at the path specified by `--fmriprep-subjects-csv`.

Configuration wiring:

- `qc.heuristics_final_table` in `config/config_adni.yaml` should point to `outputs/final_heuristics.tsv` and is consumed by the MRIQC driver in `s6_mriqc/adni_mriqc.slurm`.
- `paths.fmriprep_heuristics_csv` should point to the grouped per-subject CSV and is consumed by the fMRIPrep driver in `s7_fmriprep/run_fmriprep_bids_filter_array_all.sh`.

## Notebook (optional visualization)

There is still a Jupyter notebook at `create_report/main.ipynb` that you can open to generate plots and a narrative report. The notebook uses the same underlying `SessionFilterPipeline` and heuristics but is now primarily for visualization and exploration.

Now, continue on to Step 6 (`s6_mriqc/README.md`).
