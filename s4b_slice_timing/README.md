# Step 4b.) Insert SliceTiming into Philips scans

Run this **after** Step 4 (Clinica has produced the merged BIDS tree) and
**before** Step 5 (post-Clinica QC).

## Why this step exists

`dcm2niix` (used by Clinica) usually cannot recover slice-acquisition timing
from Philips DICOMs, so the BOLD JSON sidecars it writes for Philips scans have
**no `SliceTiming` field**. Without it, fMRIPrep silently skips slice-time
correction for those runs. Roughly 1,100 of the ADNI rs-fMRI scans are Philips,
and the large majority are missing `SliceTiming`.

ADNI publishes the true per-slice acquisition times in the Mayo fMRI QC table
(`MAYOADIRL_MRI_FMRI_NFQ_*.csv`), downloadable from LONI. Its `SLICETIMING`
column holds each slice's **absolute** acquisition clock time (seconds-of-day,
underscore separated). BIDS `SliceTiming` wants times relative to the start of
each volume, so this step subtracts the minimum of each array and writes the
result into the sidecar.

## What it does

`insert_philips_slicetiming.py`:

1. Loads the ADNI metadata CSV (`paths.adni_fmri_metadata_csv`) and keeps rows
   whose `MANUFACTURER` matches `slice_timing.manufacturers` (default `Philips`).
2. Converts each `SLICETIMING` string to relative seconds and records the slice
   count and the acquisition pattern (the 1-indexed order the slices were
   acquired, e.g. `(1, 3, 5, ...)`).
3. Walks the BIDS tree for the resting-state BOLD sidecars
   (`slice_timing.bold_json_glob`, default `sub-*/**/func/*task-rest_bold.json`),
   and for each Philips sidecar that is missing `SliceTiming`, finds the matching
   metadata row and writes `SliceTiming` into that JSON in place (keeping a
   `.json.bak` backup by default).
4. Writes a per-scan report TSV (`slice_timing.report_tsv`).

### Matching

Each sidecar is matched to a metadata row by:

- **subject** — the numeric RID parsed from `sub-ADNI<site>S<rid>` equals the
  metadata `RID`;
- **session** — the BIDS `ses-<label>` equals `VISCODE2` mapped to a session
  (`bl` → `M000`, `m<NN>` → `M0NN`); ADNI screening codes such as `scmri` have no
  BIDS session and are ignored;
- **series number** — used as a tiebreaker when a session has more than one
  candidate.

A match is only accepted when the slice count (from the NIfTI, if `nibabel` is
installed) and the TR (from the sidecar, within `slice_timing.tr_tolerance_s`)
agree with the metadata row. Otherwise the scan is reported as
`validation_failed` and left untouched.

### Standard vs. flagged patterns

The standard ADNI Philips rs-fMRI order is `(1, 3, 5, ...)` (even-then-odd
interleave, 48 slices, TR 3 s). A small number of scans use a different
interleave (e.g. `(1, 8, 15, ...)`, `(1, 7, 13, ...)`). Their timing is still
valid, so by default they are written but marked `flagged=yes` in the report for
manual review. Set `slice_timing.write_flagged: false` to leave flagged scans
untouched instead.

## Usage

```bash
# Report only — nothing is modified:
python s4b_slice_timing/insert_philips_slicetiming.py --config config/config_adni.yaml --dry-run

# Write SliceTiming into the sidecars:
python s4b_slice_timing/insert_philips_slicetiming.py --config config/config_adni.yaml
```

Overrides (handy for spot checks): `--bids-dir`, `--metadata-csv`, `--report-tsv`.

### Run on specific subjects only (no config edits)

Pass the BIDS tree, the slice-timing file, and a subject list directly — nothing
in `config/config_adni.yaml` needs to change:

```bash
# inline subjects (ADNI ids or BIDS labels are both accepted):
python s4b_slice_timing/insert_philips_slicetiming.py \
  --bids-dir /path/to/rawdata \
  --metadata-csv /path/to/MAYOADIRL_MRI_FMRI_NFQ_04Oct2025.csv \
  --subjects 002_S_0413 130_S_1234

# or a file with one subject per line:
python s4b_slice_timing/insert_philips_slicetiming.py \
  --bids-dir /path/to/rawdata \
  --metadata-csv /path/to/MAYOADIRL_MRI_FMRI_NFQ_04Oct2025.csv \
  --subject-list injected_subjects.txt
```

`--subjects`/`--subject-list` accept `002_S_0413`, `sub-ADNI002S0413`, or
`ADNI002S0413` interchangeably. The written scans are recorded (status
`written`) in the report TSV, which you can turn into the subject list for a
targeted fMRIPrep re-run (see `s7_fmriprep/README.md`).

## Report statuses

| status | meaning |
| --- | --- |
| `written` / `written_flagged` | SliceTiming inserted (flagged = non-standard pattern) |
| `would_write` / `would_write_flagged` | `--dry-run`: would insert |
| `skipped_present` | sidecar already had SliceTiming (`skip_if_present`) |
| `skipped_not_target` | sidecar Manufacturer is not in `slice_timing.manufacturers` |
| `skipped_flagged` | non-standard pattern and `write_flagged: false` |
| `unmatched` / `ambiguous` | no single metadata row for this subject/session |
| `validation_failed` | metadata slice count or TR disagreed with the sidecar |
| `error` | sidecar could not be read |

## Configuration

All settings live under `slice_timing:` in `config/config_adni.yaml`, and the
input paths are `paths.adni_fmri_metadata_csv` and `paths.clinica_bids_dir`.

When done, continue to Step 5 (`s5_post_clinica_qc/README.md`).
