"""Derive the per-stage subject/session counts for the pipeline sample-size table.

Instead of hand-counting, this walks the real pipeline outputs and represents
each stage as a *set of (sub, ses) BIDS ids*. Subjects and sessions kept at a
stage are just the size of that set (unique subjects / unique sessions), and the
"dropped" counts are set differences from the previous stage. A subject is
counted as dropped at the stage where their last surviving session disappears.

Stages and their sources (config section ``sample_size``):

  | Stage            | id-set                                                       |
  |------------------|--------------------------------------------------------------|
  | Start            | every session in the Step 5 mastersheet (``mastersheet_csv``) |
  | BIDS via Clinica | mastersheet survivors after the s5 phase-0 heuristics         |
  |                  | (BIDS-conversion errors, missing NIfTI/JSON, missing T1w)     |
  | Post-Clinica QC  | s5 final survivors (TR / scan-depth / duration / FOV / coil)  |
  | MRIQC            | previous ∩ sessions that have MRIQC IQMs (``mriqc_iqms_table``)|
  | Post-MRIQC QC    | previous ∩ MRIQC rows with ``mriqc_exclude_col`` == 0          |
  | fMRIPrep         | previous ∩ ``fmriprep_sessions_table`` (fMRIPrep completed)    |
  | Final QC         | previous ∩ ``final_inclusion_table``                          |

Each stage is chain-intersected with all previous stages (``enforce_sequential``),
so the cascade is strictly sequential/monotonic even if the pipeline was not run
in order: a session that reached, say, fMRIPrep without passing post-MRIQC QC is
removed from fMRIPrep (and later) counts. How many such sessions are removed at
each stage is reported to stderr.

The counts are written into the manifest (``sample_size.manifest``) that
``make_sample_size_table.py`` renders, and the Markdown table is printed.

Usage
-----
    python s8_final_qc/collect_sample_sizes.py --config config/config_adni.yaml
    python s8_final_qc/collect_sample_sizes.py --print-only        # don't write manifest

Requires the ``env_adni`` environment (pandas; the s5 pipeline import pulls in
plotly). Override any input path with the matching ``--*`` flag.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Reuse the renderer's Stage model + Markdown output so both tools agree.
sys.path.insert(0, str(REPO_ROOT / "s8_final_qc"))
from make_sample_size_table import Stage, render_markdown, HEADERS  # noqa: E402

BidsId = Tuple[str, str]  # (sub, ses)


# --------------------------------------------------------------------------- #
# Stage definitions (labels/folders/descriptions match the manuscript table)
# --------------------------------------------------------------------------- #
STAGE_META = [
    ("start",        "Unzip & organize DICOMs",  "s3_organize/",        "Clean directory tree; check integrity"),
    ("clinica",      "BIDS-convert via Clinica", "s4_clinica/",         "NIfTI + JSON + sidecars"),
    ("postclinica",  "Post-Clinica QC",          "s5_post_clinica_qc/", "TR/coverage/duration checks"),
    ("mriqc",        "MRIQC",                    "s6_mriqc/",           "All IQMs present"),
    ("postmriqc",    "Post-MRIQC QC",            "s6_mriqc/",           "Robust outlier detection"),
    ("fmriprep",     "fMRIPrep",                 "s7_fmriprep/",        "Volumetric, surface, grayordinates outputs"),
    ("final",        "Final QC",                 "s8_final_qc/",        "Euler number, motion, >=5 min usable data"),
]


# --------------------------------------------------------------------------- #
# ID normalization
# --------------------------------------------------------------------------- #
_VIS_RE = re.compile(r"^m(\d+)$", re.IGNORECASE)


def viscode_to_session(viscode: str) -> str:
    """ADNI VISCODE (e.g. ``bl``, ``m6``, ``m144``) -> BIDS session label."""
    v = str(viscode).strip().lower()
    if v in ("bl", "m0", "m00", "m000"):
        return "ses-M000"
    m = _VIS_RE.match(v)
    return f"ses-M{int(m.group(1)):03d}" if m else "ses-" + v.upper()


def subject_viscode_to_bids(subject_id: str, viscode: str) -> BidsId:
    """s5 ``Subject_ID`` (``002_S_0413``) + VISCODE -> (``sub-ADNI002S0413``, ``ses-M060``)."""
    return "sub-ADNI" + str(subject_id).replace("_", ""), viscode_to_session(viscode)


def n_subjects(ids: Set[BidsId]) -> int:
    return len({sub for sub, _ in ids})


# --------------------------------------------------------------------------- #
# Loading id-sets from the various pipeline outputs
# --------------------------------------------------------------------------- #
def ids_from_bids_table(path: Path, sub_col: str = "sub", ses_col: str = "ses") -> Set[BidsId]:
    """Read a table whose subject/session columns are already BIDS labels."""
    import pandas as pd
    delim = "\t" if path.suffix.lower() in (".tsv", ".tab") else ","
    df = pd.read_csv(path, sep=delim, low_memory=False)
    for col in (sub_col, ses_col):
        if col not in df.columns:
            raise ValueError(f"{path} has no '{col}' column (columns: {list(df.columns)[:20]})")
    return set(zip(df[sub_col].astype(str), df[ses_col].astype(str), strict=False))


def _ids_from_pipeline_df(df) -> Set[BidsId]:
    return {subject_viscode_to_bids(r.Subject_ID, r.VISCODE) for r in df.itertuples()}


def mriqc_exclude_series(mq, exclude_col: str):
    """Return a 0/1 exclude Series from an MRIQC QC-flags table, or None.

    Accepts the configured ``exclude_col`` directly, or derives it from the
    ``adni_outlier_pipeline.R`` outputs ``excluded_any`` / ``qc_status_any``.
    """
    col = exclude_col if exclude_col in mq.columns else (
        "excluded_any" if "excluded_any" in mq.columns else None)
    if col is not None:
        return mq[col].map(
            lambda v: 1 if str(v).strip().lower() in ("1", "true", "yes", "excluded") else 0)
    if "qc_status_any" in mq.columns:
        return (mq["qc_status_any"].astype(str).str.strip().str.lower() == "excluded").astype(int)
    return None


def run_s5_pipeline(mastersheet_csv: Path):
    """Import and run the Step-5 SessionFilterPipeline on the mastersheet."""
    report_dir = REPO_ROOT / "s5_post_clinica_qc" / "create_report"
    for p in (report_dir, report_dir / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        from scripts.session_pipeline import SessionFilterPipeline
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Could not import the Step-5 SessionFilterPipeline "
            f"({type(e).__name__}: {e}). Run inside the env_adni environment.") from e
    pipeline = SessionFilterPipeline(str(mastersheet_csv))
    pipeline.run(phase_limit=2, verbose=False)
    return pipeline


# --------------------------------------------------------------------------- #
# Build the ordered, monotonic cascade of id-sets
# --------------------------------------------------------------------------- #
def enforce_sequential(raw: Dict[str, Set[BidsId]]) -> "Dict[str, Set[BidsId]]":
    """Chain-intersect stages so each is a strict subset of every earlier stage.

    A session survives to a stage only if it survived all previous stages. This
    reconciles pipelines that were not run strictly in order: e.g. a session that
    reached fMRIPrep without passing post-MRIQC QC is removed from the fMRIPrep
    (and final) counts here, because it should never have advanced. How many such
    "leaked" sessions are removed at each stage is reported to stderr.
    """
    order = [k for k, *_ in STAGE_META]
    effective: Dict[str, Set[BidsId]] = {}
    running: Optional[Set[BidsId]] = None
    for key in order:
        cur = raw[key]
        if running is None:
            running = set(cur)
        else:
            leaked = cur - running
            running = cur & running
            if leaked:
                print(f"[collect_sample_sizes] {key}: removed {len(leaked)} session(s) present "
                      f"in the {key} table but not surviving an earlier stage "
                      f"(sequential alignment).", file=sys.stderr)
        effective[key] = set(running)
    return effective


def collect_idsets(paths: Dict[str, Path], mriqc_exclude_col: str) -> "Dict[str, Set[BidsId]]":
    """Return {stage_key: set of (sub, ses)} for every stage.

    Upstream stages come from the Step-5 pipeline. The MRIQC stage is the
    Step-5 survivors that *have* MRIQC output (so its drop is exactly the
    "in Step 5 output but not in MRIQC" set). Later stages are each read
    authoritatively from their own step's table (post-MRIQC QC kept rows,
    fMRIPrep completions, final inclusion) rather than re-intersected, so the
    counts match each step's own output.
    """
    import pandas as pd

    pipeline = run_s5_pipeline(paths["mastersheet_csv"])
    start = _ids_from_pipeline_df(pipeline.df_original)
    after_clinica = _ids_from_pipeline_df(pipeline.phase_checkpoints[0])
    after_postclinica = _ids_from_pipeline_df(pipeline.df_current)

    # MRIQC: sessions with IQMs, and the subset kept after post-MRIQC QC.
    mq = pd.read_csv(paths["mriqc_iqms_table"], low_memory=False)
    mriqc_ids = set(zip(mq["sub"].astype(str), mq["ses"].astype(str), strict=False))
    excl = mriqc_exclude_series(mq, mriqc_exclude_col)
    if excl is not None:
        kept = mq[excl == 0]
        mriqc_kept_ids = set(zip(kept["sub"].astype(str), kept["ses"].astype(str), strict=False))
    else:
        print(f"[collect_sample_sizes] warning: no MRIQC exclude column "
              f"('{mriqc_exclude_col}'/'excluded_any'/'qc_status_any') in table; "
              f"treating all MRIQC sessions as kept.", file=sys.stderr)
        mriqc_kept_ids = mriqc_ids

    # MRIQC-completed within the Step-5 cohort (drop = failed to run MRIQC).
    after_mriqc = after_postclinica & mriqc_ids
    failed_mriqc = after_postclinica - mriqc_ids
    if failed_mriqc:
        print(f"[collect_sample_sizes] {len(failed_mriqc)} session(s) / "
              f"{n_subjects(after_postclinica) - n_subjects(after_mriqc)} subject(s) in the "
              f"Step-5 output have no MRIQC result (failed to run MRIQC).", file=sys.stderr)

    after_fmriprep = ids_from_bids_table(paths["fmriprep_sessions_table"])
    after_final = ids_from_bids_table(paths["final_inclusion_table"])

    # Raw per-stage id-sets (each read from its own step's output). These may not
    # be nested, so enforce_sequential() chain-intersects them into a strict,
    # sequentially-aligned cascade before the counts are derived.
    raw = {
        "start": start,
        "clinica": after_clinica,
        "postclinica": after_postclinica,
        "mriqc": mriqc_ids,          # all sessions with IQMs; intersected with the cohort below
        "postmriqc": mriqc_kept_ids,
        "fmriprep": after_fmriprep,
        "final": after_final,
    }
    return enforce_sequential(raw)


def build_stages(idsets: Dict[str, Set[BidsId]]) -> List[Stage]:
    """Turn the id-sets into Stage objects (with derived drop counts)."""
    stages: List[Stage] = []
    for key, label, folder, desc in STAGE_META:
        ids = idsets[key]
        stages.append(Stage(label, folder, desc, n_subjects(ids), len(ids)))
    for prev, cur in zip(stages, stages[1:], strict=False):
        cur.dropped_subjects = prev.subjects - cur.subjects
        cur.dropped_sessions = prev.sessions - cur.sessions
    return stages


# --------------------------------------------------------------------------- #
# Manifest output
# --------------------------------------------------------------------------- #
MANIFEST_COLUMNS = ["stage", "folder", "description", "count_from", "subjects", "sessions"]


def write_manifest(stages: List[Stage], manifest: Path) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, delimiter="\t")
        w.writeheader()
        for s in stages:
            w.writerow({"stage": s.label, "folder": s.folder, "description": s.description,
                        "count_from": "", "subjects": s.subjects, "sessions": s.sessions})


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _resolve(cfg: dict, key: str, override: Optional[str]) -> Path:
    if override:
        p = Path(override)
    else:
        from utils.config_tools import get_value
        p = Path(get_value(cfg, f"sample_size.{key}"))
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--config", dest="config_path", default=None)
    p.add_argument("--mastersheet-csv", default=None)
    p.add_argument("--mriqc-iqms-table", default=None)
    p.add_argument("--fmriprep-sessions-table", default=None)
    p.add_argument("--final-inclusion-table", default=None)
    p.add_argument("--manifest", default=None)
    p.add_argument("--print-only", action="store_true",
                   help="Print the table without writing the manifest.")
    p.add_argument("--dump-stage", default=None,
                   choices=[k for k, *_ in STAGE_META],
                   help="Also write the sequential (sub, ses) id-set of this stage to --dump-out.")
    p.add_argument("--dump-out", default=None,
                   help="Path for the --dump-stage TSV (columns: sub, ses).")
    return p.parse_args(argv)


def write_idset(ids: Set[BidsId], path: Path) -> None:
    """Write a stage's (sub, ses) id-set as a sorted TSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["sub", "ses"])
        for sub, ses in sorted(ids):
            w.writerow([sub, ses])


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    from utils.config_tools import load_config, get_value
    cfg = load_config(args.config_path)

    try:
        paths = {
            "mastersheet_csv": _resolve(cfg, "mastersheet_csv", args.mastersheet_csv),
            "mriqc_iqms_table": _resolve(cfg, "mriqc_iqms_table", args.mriqc_iqms_table),
            "fmriprep_sessions_table": _resolve(cfg, "fmriprep_sessions_table", args.fmriprep_sessions_table),
            "final_inclusion_table": _resolve(cfg, "final_inclusion_table", args.final_inclusion_table),
        }
        for name, path in paths.items():
            if not path.is_file():
                raise FileNotFoundError(f"{name} not found: {path}")

        try:
            mriqc_exclude_col = get_value(cfg, "sample_size.mriqc_exclude_col")
        except KeyError:
            mriqc_exclude_col = "exclude_mriqc"

        idsets = collect_idsets(paths, mriqc_exclude_col)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"[collect_sample_sizes] {e}", file=sys.stderr)
        return 1

    if args.dump_stage:
        if not args.dump_out:
            print("[collect_sample_sizes] --dump-stage requires --dump-out", file=sys.stderr)
            return 1
        out = Path(args.dump_out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        write_idset(idsets[args.dump_stage], out)
        print(f"[collect_sample_sizes] wrote {len(idsets[args.dump_stage])} '{args.dump_stage}' "
              f"sessions -> {out}", file=sys.stderr)

    stages = build_stages(idsets)

    if not args.print_only:
        manifest = _resolve(cfg, "manifest", args.manifest)
        write_manifest(stages, manifest)
        print(f"[collect_sample_sizes] wrote manifest -> {manifest}", file=sys.stderr)

    sys.stdout.write(render_markdown(stages, bold_last=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
