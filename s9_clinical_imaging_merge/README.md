# Step 9.) Merge imaging sessions with clinical data

This step joins the final included imaging sessions (from Step 8) to the ADNI
clinical assessments and visualizes the result. For every imaging session it
finds the nearest clinical visit, attaches that visit's cognitive scores and
diagnosis, and writes a merged table plus three interactive figures used to
sanity-check the imaging↔clinical alignment for downstream analyses.

This is a downstream analysis/reporting step (it produces the merged table and
the manuscript figures); it is not part of the preprocessing that feeds fMRIPrep.

**Requires Python** with `pandas`, `numpy`, and `plotly`.

## What it does

`adni_swimlane_clinical.py`:

1. Loads the imaging sessions and ensures every session has a usable calendar
   date (sessions with no `Scan_Date` are imputed from the subject's nearest
   dated scan using the ADNI month offset, ~30.44 days/month, and flagged).
2. Loads and unifies the clinical tables (ADAS-Cog, MMSE, CDR, MoCA, DXSUM) into
   one row per subject × visit date.
3. **Nearest-neighbour matches** each imaging session to the closest clinical
   visit within `--max-days` (default 180). Within a subject, sessions are
   matched in date order and each clinical visit is used at most once; clinical
   visits that are not the nearest match to any scan are dropped.
4. Writes the merged session table and three Plotly HTML figures.

## Inputs

- `--imaging` (**required**) – the Step-8 inclusion table enriched with scan
  date and diagnosis (`included_sessions_merged.csv`). It must contain the
  columns `Subject_ID`, `ses` (BIDS `ses-M0NN`), `Scan_Date`, and `DIAGNOSIS`
  (`1`/`2`/`3` → `CN`/`MCI`/`AD`). Build it from `s8_final_qc/included_sessions.tsv`
  with `build_imaging_input.py`, which adds `Subject_ID`/`Scan_Date` from the
  Step-5 mastersheet and `DIAGNOSIS` from the DXSUM visit nearest each scan:

  ```bash
  python s9_clinical_imaging_merge/build_imaging_input.py \
    --included    s8_final_qc/included_sessions.tsv \
    --mastersheet /path/to/anchor_plus_dicom_nifti_struct.csv \
    --dxsum       /path/to/DXSUM.csv \
    --output      s9_clinical_imaging_merge/included_sessions_merged.csv
  ```
- ADNI clinical CSVs downloaded from the LONI IDA *Study Data* area, each keyed
  by `PTID` + `VISCODE2` (pass any subset):

  | flag | file | date column | score columns used |
  | --- | --- | --- | --- |
  | `--adas`  | ADAS-Cog | `VISDATE`  | `TOTSCORE`, `TOTAL13` |
  | `--mmse`  | MMSE     | `VISDATE`  | `MMSCORE` |
  | `--cdr`   | CDR      | `VISDATE`  | `CDGLOBAL`, `CDRSB` |
  | `--moca`  | MoCA     | `VISDATE`  | `MOCA` |
  | `--dxsum` | DXSUM    | `EXAMDATE` | `DIAGNOSIS` (clinical dx at the visit) |

## Outputs

- `--save-merged` → **`merged_sessions.csv`** – one row per imaging session with
  its matched clinical visit: `RID, sub, ses, img_month, scan_date, dx,
  date_imputed, clin_date, clin_days_diff, matched`, the score columns
  (`MMSCORE, CDGLOBAL, CDRSB, TOTSCORE, TOTAL13, MOCA`), and the clinical
  diagnosis `clin_dx`.
- `--output` → **`adni_swimlane_clinical.html`** – swimlane on a calendar-date
  axis: one row per subject (sorted by final diagnosis group, then first scan),
  imaging visits as circles, matched clinical visits as diamonds, a dotted
  connector for the gap, and CN/MCI/AD group filter buttons.
- `--hist-output` → **`adni_gap_histogram.html`** – distribution of the signed
  imaging↔clinical gap (clinical date − scan date), one panel per dx group.
- `--combined-output` → **`adni_combined_figure.html`** – a single figure with
  the swimlane (A), the gap histogram (B), and a per-group gap statistics table (C).

Imputed-date sessions are excluded from the gap histogram/statistics (their gap
is an estimate, not real scheduling).

## Usage

```bash
python s9_clinical_imaging_merge/adni_swimlane_clinical.py \
  --imaging included_sessions_merged.csv \
  --adas  ADAS_18Jul2026.csv \
  --mmse  MMSE_18Jul2026.csv \
  --cdr   CDR_18Jul2026.csv \
  --dxsum DXSUM_18Jul2026.csv \
  --moca  MOCA_18Jul2026.csv \
  --save-merged     merged_sessions.csv \
  --output          adni_swimlane_clinical.html \
  --hist-output     adni_gap_histogram.html \
  --combined-output adni_combined_figure.html
```

Useful knobs: `--max-days` (matching window, default 180) and `--binsize`
(histogram bin width in days, default 7). The console also prints per-group gap
statistics (median / p75 / p95 / max, % same-day, % within one week).
