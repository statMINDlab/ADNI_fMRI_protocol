"""Insert SliceTiming into Philips BOLD sidecars after Clinica BIDS conversion.

Background
----------
dcm2niix (and therefore Clinica) frequently cannot recover slice-acquisition
timing from Philips DICOMs, so the BOLD JSON sidecars it writes for Philips
scans have no ``SliceTiming`` field. Without it, fMRIPrep cannot perform
slice-time correction.

ADNI distributes the true per-slice acquisition times in the Mayo fMRI QC table
(``MAYOADIRL_MRI_FMRI_NFQ_*.csv``, config key ``paths.adni_fmri_metadata_csv``).
Its ``SLICETIMING`` column stores each slice's *absolute* acquisition clock time
(seconds-of-day, underscore separated). BIDS ``SliceTiming`` wants times relative
to the start of each volume, so we subtract the minimum of the array.

This step runs after ``s4_clinica`` (once the merged BIDS tree exists) and before
``s5_post_clinica_qc``. It only touches scans whose sidecar ``Manufacturer``
matches ``slice_timing.manufacturers`` and (by default) that lack SliceTiming.

Matching
--------
Each Philips ``*_bold.json`` is matched to an ADNI metadata row by:
  * subject: the numeric RID parsed from ``sub-ADNI<site>S<rid>`` == metadata ``RID``
  * session: the BIDS ``ses-<label>`` == metadata ``VISCODE2`` mapped to a session
             label (``bl`` -> ``M000``, ``m<NN>`` -> ``M0NN``)
  * series number (tiebreaker when a session has more than one candidate)
A match is only accepted if the slice count and TR are consistent with the
sidecar, otherwise it is reported as ``validation_failed`` and left untouched.

Usage
-----
    python s4b_slice_timing/insert_philips_slicetiming.py --config config/config_adni.yaml
    python s4b_slice_timing/insert_philips_slicetiming.py --dry-run   # report only

Nothing is written in ``--dry-run`` mode; the report TSV is always written.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Ensure repo root is importable so ``utils.config_tools`` resolves regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.config_tools import load_config, get_value  # noqa: E402


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def parse_abs_slice_timing(raw: str) -> List[float]:
    """Parse an underscore-separated ADNI SLICETIMING string into relative times.

    The ADNI values are absolute acquisition clock times; BIDS wants times
    relative to the earliest-acquired slice, so we subtract the minimum.
    Raises ValueError if the string is empty or non-numeric.
    """

    parts = [p for p in str(raw).strip().split("_") if p != ""]
    if not parts:
        raise ValueError("empty SLICETIMING")
    abs_times = [float(p) for p in parts]
    origin = min(abs_times)
    return [round(t - origin, 6) for t in abs_times]


def acquisition_pattern(rel_times: List[float], preview: int = 3) -> str:
    """Return the 1-indexed slice acquisition order as e.g. ``(1, 3, 5, ...)``.

    Slice index 0 is the first slice along the acquisition axis; the returned
    order lists which slice (1-indexed) was acquired 1st, 2nd, 3rd, ...
    """

    order = sorted(range(len(rel_times)), key=lambda i: rel_times[i])
    head = ", ".join(str(i + 1) for i in order[:preview])
    return f"({head}, ...)"


_SESSION_RE = re.compile(r"^m(\d+)$", re.IGNORECASE)


def viscode_to_session(viscode2: str) -> Optional[str]:
    """Map an ADNI VISCODE2 to a Clinica BIDS session label (without ``ses-``)."""

    v = str(viscode2).strip().lower()
    if v in ("bl", "m0", "m00", "m000"):
        return "M000"
    m = _SESSION_RE.match(v)
    if m:
        return f"M{int(m.group(1)):03d}"
    return None  # screening / unknown codes are not represented in the BIDS tree


_RID_RE = re.compile(r"S(\d+)\b")


def subject_to_rid(sub_label: str) -> Optional[int]:
    """Parse the numeric RID from a BIDS subject label like ``sub-ADNI002S0413``."""

    m = _RID_RE.search(str(sub_label))
    return int(m.group(1)) if m else None


def path_subject_session(json_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(sub-label, ses-label)`` inferred from a sidecar path."""

    sub = ses = None
    # Only look at directory components; the filename also starts with "sub-".
    for part in json_path.parent.parts:
        if part.startswith("sub-"):
            sub = part
        elif part.startswith("ses-"):
            ses = part
    return sub, ses


# --------------------------------------------------------------------------- #
# Metadata index
# --------------------------------------------------------------------------- #
class MetadataRecord:
    """One ADNI fMRI-metadata row reduced to what this step needs."""

    __slots__ = ("rid", "session", "series_number", "tr_s", "rel_times",
                 "n_slices", "pattern")

    def __init__(self, rid: int, session: str, series_number: str, tr_s: float,
                 rel_times: List[float], pattern: str) -> None:
        self.rid = rid
        self.session = session
        self.series_number = series_number
        self.tr_s = tr_s
        self.rel_times = rel_times
        self.n_slices = len(rel_times)
        self.pattern = pattern


def _manufacturer_matches(value: str, needles: Iterable[str]) -> bool:
    v = str(value).lower()
    return any(str(n).lower() in v for n in needles)


def load_metadata_index(
    csv_path: Path, manufacturers: Iterable[str]
) -> Dict[Tuple[int, str], List[MetadataRecord]]:
    """Build ``{(rid, session): [MetadataRecord, ...]}`` for target manufacturers.

    Rows that are not from a target manufacturer, whose VISCODE2 has no BIDS
    session equivalent, or whose SLICETIMING is unparseable are skipped.
    """

    index: Dict[Tuple[int, str], List[MetadataRecord]] = {}
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        required = {"RID", "VISCODE2", "MANUFACTURER", "REPETITIONTIME", "SLICETIMING"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{csv_path} is missing required columns: {sorted(missing)}"
            )
        for row in reader:
            if not _manufacturer_matches(row.get("MANUFACTURER", ""), manufacturers):
                continue
            try:
                rid = int(str(row["RID"]).strip())
            except (ValueError, KeyError):
                continue
            session = viscode_to_session(row.get("VISCODE2", ""))
            if session is None:
                continue
            try:
                rel = parse_abs_slice_timing(row.get("SLICETIMING", ""))
            except ValueError:
                continue
            try:
                tr_s = float(row.get("REPETITIONTIME", "")) / 1000.0
            except ValueError:
                tr_s = float("nan")
            rec = MetadataRecord(
                rid=rid,
                session=session,
                series_number=str(row.get("SERIESNUMBER", "")).strip(),
                tr_s=tr_s,
                rel_times=rel,
                pattern=acquisition_pattern(rel),
            )
            index.setdefault((rid, session), []).append(rec)
    return index


# --------------------------------------------------------------------------- #
# Sidecar handling
# --------------------------------------------------------------------------- #
def _nii_for(json_path: Path) -> Optional[Path]:
    for ext in (".nii.gz", ".nii"):
        cand = json_path.with_name(json_path.stem + ext)
        if cand.exists():
            return cand
    return None


def nifti_n_slices(nii_path: Path) -> Optional[int]:
    """Return the slice count (3rd dim) of a NIfTI, or None if unreadable."""

    try:
        import nibabel as nib  # local import: keep nibabel optional
    except Exception:
        return None
    try:
        shape = nib.load(str(nii_path)).shape
        return int(shape[2]) if len(shape) >= 3 else None
    except Exception:
        return None


def choose_record(
    candidates: List[MetadataRecord],
    series_number: Optional[str],
    n_slices: Optional[int],
    tr_s: Optional[float],
    tr_tol: float,
) -> Tuple[Optional[MetadataRecord], str]:
    """Pick the single matching record from candidates, or explain why not."""

    if not candidates:
        return None, "unmatched"

    pool = candidates
    # Prefer an exact series-number match when the sidecar provides one.
    if series_number:
        exact = [c for c in pool if c.series_number == str(series_number)]
        if len(exact) == 1:
            return exact[0], "matched_series"
        if exact:
            pool = exact

    # Narrow by slice count and TR when available.
    if n_slices is not None:
        by_slices = [c for c in pool if c.n_slices == n_slices]
        if by_slices:
            pool = by_slices
    if tr_s is not None:
        by_tr = [c for c in pool if _tr_close(c.tr_s, tr_s, tr_tol)]
        if by_tr:
            pool = by_tr

    if len(pool) == 1:
        return pool[0], "matched"
    return None, "ambiguous"


def _tr_close(a: float, b: float, tol: float) -> bool:
    try:
        return abs(a - b) <= tol
    except (TypeError, ValueError):
        return False


def process_sidecar(
    json_path: Path,
    index: Dict[Tuple[int, str], List[MetadataRecord]],
    opts: "Options",
) -> Dict[str, Any]:
    """Match one sidecar and (unless dry-run) write SliceTiming. Returns a report row."""

    sub, ses = path_subject_session(json_path)
    rec_row: Dict[str, Any] = {
        "participant": sub or "",
        "session": ses or "",
        "json_path": str(json_path),
        "manufacturer": "",
        "status": "",
        "series_number": "",
        "n_slices": "",
        "tr_s": "",
        "slice_pattern": "",
        "flagged": "",
        "message": "",
    }

    try:
        with json_path.open() as f:
            data = json.load(f)
    except Exception as e:  # unreadable/invalid JSON
        rec_row["status"] = "error"
        rec_row["message"] = f"could not read sidecar: {e}"
        return rec_row

    manufacturer = str(data.get("Manufacturer", ""))
    rec_row["manufacturer"] = manufacturer
    if not _manufacturer_matches(manufacturer, opts.manufacturers):
        rec_row["status"] = "skipped_not_target"
        return rec_row

    existing = data.get("SliceTiming")
    if opts.skip_if_present and existing:
        rec_row["status"] = "skipped_present"
        return rec_row

    rid = subject_to_rid(sub or "")
    session = viscode_to_session(ses.replace("ses-", "")) if ses else None
    if rid is None or session is None:
        rec_row["status"] = "unmatched"
        rec_row["message"] = "could not derive RID/session from path"
        return rec_row

    nii = _nii_for(json_path)
    n_slices = nifti_n_slices(nii) if nii else None
    tr_json = data.get("RepetitionTime")
    tr_json = float(tr_json) if isinstance(tr_json, (int, float)) else None

    record, why = choose_record(
        index.get((rid, session), []),
        series_number=str(data.get("SeriesNumber", "")).strip() or None,
        n_slices=n_slices,
        tr_s=tr_json,
        tr_tol=opts.tr_tolerance_s,
    )
    if record is None:
        rec_row["status"] = why
        return rec_row

    rec_row["series_number"] = record.series_number
    rec_row["n_slices"] = record.n_slices
    rec_row["tr_s"] = record.tr_s
    rec_row["slice_pattern"] = record.pattern
    flagged = record.pattern != opts.standard_slice_pattern
    rec_row["flagged"] = "yes" if flagged else "no"

    # Validate against the sidecar/NIfTI before trusting the match.
    if n_slices is not None and n_slices != record.n_slices:
        rec_row["status"] = "validation_failed"
        rec_row["message"] = f"NIfTI has {n_slices} slices, metadata has {record.n_slices}"
        return rec_row
    if tr_json is not None and not _tr_close(record.tr_s, tr_json, opts.tr_tolerance_s):
        rec_row["status"] = "validation_failed"
        rec_row["message"] = f"sidecar TR {tr_json}s vs metadata TR {record.tr_s}s"
        return rec_row

    if flagged and not opts.write_flagged:
        rec_row["status"] = "skipped_flagged"
        rec_row["message"] = f"non-standard pattern {record.pattern}; write_flagged=false"
        return rec_row

    if opts.dry_run:
        rec_row["status"] = "would_write_flagged" if flagged else "would_write"
        return rec_row

    if opts.backup_json:
        backup = json_path.with_suffix(json_path.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(json_path, backup)

    data["SliceTiming"] = record.rel_times
    with json_path.open("w") as f:
        json.dump(data, f, indent=4)
        f.write("\n")

    rec_row["status"] = "written_flagged" if flagged else "written"
    return rec_row


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
class Options:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        st = cfg.get("slice_timing", {}) or {}
        self.manufacturers = st.get("manufacturers", ["Philips"])
        self.standard_slice_pattern = st.get("standard_slice_pattern", "(1, 3, 5, ...)")
        self.write_flagged = bool(st.get("write_flagged", True))
        self.skip_if_present = bool(st.get("skip_if_present", True))
        self.backup_json = bool(st.get("backup_json", True))
        self.tr_tolerance_s = float(st.get("tr_tolerance_s", 0.1))
        # Which sidecars to touch, relative to the BIDS root. Defaults to the
        # resting-state BOLD JSON only (ADNI fMRI is resting state).
        self.bold_json_glob = st.get("bold_json_glob", "sub-*/**/func/*task-rest_bold.json")
        self.dry_run = False


REPORT_COLUMNS = [
    "participant", "session", "json_path", "manufacturer", "status",
    "series_number", "n_slices", "tr_s", "slice_pattern", "flagged", "message",
]


def find_bold_sidecars(bids_dir: Path, pattern: str) -> List[Path]:
    return sorted(bids_dir.glob(pattern))


def normalize_subject(token: str) -> str:
    """Reduce a subject token to a comparison key, accepting many spellings.

    ``002_S_0413``, ``sub-ADNI002S0413``, ``ADNI002S0413`` and ``002S0413`` all
    normalize to ``002S0413``.
    """

    s = re.sub(r"[^A-Za-z0-9]", "", str(token)).upper()
    for prefix in ("SUB", "ADNI"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def load_subject_filter(
    subjects: Optional[Iterable[str]], subject_list: Optional[str]
) -> Optional[set]:
    """Build a set of normalized subject keys from inline ids and/or a list file.

    Returns None when no subject restriction was requested (process everything).
    Blank lines and ``#`` comments in the list file are ignored.
    """

    tokens: List[str] = list(subjects or [])
    if subject_list:
        for line in Path(subject_list).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                tokens.append(line)
    if not tokens:
        return None
    return {normalize_subject(t) for t in tokens}


# Column names (lowercased) accepted for the subject and visit fields of a
# subject+session list such as philips_sessions.csv.
_SUBJECT_COLS = ("subject_id", "subject", "ptid", "rid", "sub")
_VISIT_COLS = ("viscode2", "viscode", "visit", "session", "ses")


def _session_label(value: str) -> Optional[str]:
    """Map a visit code (``bl``, ``m72``, ``M072``, ``ses-M072``) to ``M072``."""

    v = re.sub(r"(?i)^ses-", "", str(value).strip())
    return viscode_to_session(v)


def load_session_filter(sessions_csv: Optional[str]) -> Optional[set]:
    """Build a set of ``(subject_key, session_label)`` pairs from a CSV.

    The CSV needs a subject column (SUBJECT_ID / PTID / RID / SUBJECT) and a visit
    column (VISCODE / VISCODE2 / SESSION), e.g. the ADNI Philips-sessions export.
    Returns None when no path is given (no session restriction).
    """

    if not sessions_csv:
        return None
    path = Path(sessions_csv)
    if not path.is_file():
        raise FileNotFoundError(f"Sessions CSV not found: {path}")
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        low = {c.lower(): c for c in fields}
        sub_col = next((low[c] for c in _SUBJECT_COLS if c in low), None)
        vis_col = next((low[c] for c in _VISIT_COLS if c in low), None)
        if sub_col is None or vis_col is None:
            raise ValueError(
                f"{path}: need a subject column {_SUBJECT_COLS} and a visit column "
                f"{_VISIT_COLS}; found {fields}"
            )
        pairs: set = set()
        for row in reader:
            subj = normalize_subject(row.get(sub_col, ""))
            ses = _session_label(row.get(vis_col, ""))
            if subj and ses:
                pairs.add((subj, ses))
    return pairs or None


def write_report(rows: List[Dict[str, Any]], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS, delimiter="\t")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in REPORT_COLUMNS})


def run(
    config_path: Optional[str] = None,
    bids_dir: Optional[str] = None,
    metadata_csv: Optional[str] = None,
    report_tsv: Optional[str] = None,
    dry_run: bool = False,
    subject_keys: Optional[set] = None,
    session_keys: Optional[set] = None,
) -> Dict[str, int]:
    """Repair Philips SliceTiming across a BIDS tree. Returns a status->count summary.

    ``subject_keys`` (from ``normalize_subject``) restricts processing to those
    subjects. ``session_keys`` (``(subject_key, session_label)`` pairs, e.g. from
    ``load_session_filter``) restricts to specific subject/sessions. Both are ANDed
    when given; None means no restriction.
    """

    cfg = load_config(config_path)
    opts = Options(cfg)
    opts.dry_run = dry_run

    bids_path = Path(bids_dir or get_value(cfg, "paths.clinica_bids_dir"))
    if not bids_path.is_dir():
        raise FileNotFoundError(f"BIDS directory not found: {bids_path}")

    csv_path = Path(metadata_csv or get_value(cfg, "paths.adni_fmri_metadata_csv"))
    if not csv_path.is_file():
        raise FileNotFoundError(f"ADNI fMRI metadata CSV not found: {csv_path}")

    if report_tsv is None:
        try:
            report_tsv = get_value(cfg, "slice_timing.report_tsv")
        except KeyError:
            report_tsv = "s4b_slice_timing/slice_timing_report.tsv"
    report_path = Path(report_tsv)
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path

    index = load_metadata_index(csv_path, opts.manufacturers)
    sidecars = find_bold_sidecars(bids_path, opts.bold_json_glob)

    if subject_keys is not None:
        matched: set = set()
        kept: List[Path] = []
        for js in sidecars:
            sub, _ = path_subject_session(js)
            key = normalize_subject(sub or "")
            if key in subject_keys:
                kept.append(js)
                matched.add(key)
        missing = subject_keys - matched
        if missing:
            print(f"  [warn] {len(missing)} requested subject(s) had no matching "
                  f"sidecar: {', '.join(sorted(missing))}")
        sidecars = kept

    if session_keys is not None:
        matched_pairs: set = set()
        kept = []
        for js in sidecars:
            sub, ses = path_subject_session(js)
            pair = (normalize_subject(sub or ""), re.sub(r"(?i)^ses-", "", ses or ""))
            if pair in session_keys:
                kept.append(js)
                matched_pairs.add(pair)
        missing_pairs = session_keys - matched_pairs
        if missing_pairs:
            preview = ", ".join(f"{s}/{v}" for s, v in sorted(missing_pairs)[:8])
            more = "" if len(missing_pairs) <= 8 else f" (+{len(missing_pairs) - 8} more)"
            print(f"  [warn] {len(missing_pairs)} requested subject/session(s) had no "
                  f"matching sidecar: {preview}{more}")
        sidecars = kept

    rows = [process_sidecar(js, index, opts) for js in sidecars]
    write_report(rows, report_path)

    summary: Dict[str, int] = {}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1

    mode = "DRY RUN — no sidecars modified" if dry_run else "sidecars updated in place"
    print(f"[insert_philips_slicetiming] {mode}")
    print(f"  BIDS dir : {bids_path}")
    print(f"  metadata : {csv_path} ({len(index)} target subject/session groups)")
    notes = []
    if subject_keys is not None:
        notes.append(f"{len(subject_keys)} subject(s)")
    if session_keys is not None:
        notes.append(f"{len(session_keys)} subject/session(s)")
    subj_note = f", restricted to {' & '.join(notes)}" if notes else ""
    print(f"  sidecars : {len(sidecars)} resting-state BOLD JSONs scanned ({opts.bold_json_glob}{subj_note})")
    for status in sorted(summary):
        print(f"    {status}: {summary[status]}")
    print(f"  report   : {report_path}")
    return summary


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--config", dest="config_path", default=None,
                   help="Path to YAML config (default: $ADNI_CONFIG or config/config_adni.yaml).")
    p.add_argument("--bids-dir", default=None,
                   help="Override paths.clinica_bids_dir.")
    p.add_argument("--metadata-csv", default=None,
                   help="Override paths.adni_fmri_metadata_csv.")
    p.add_argument("--report-tsv", default=None,
                   help="Override slice_timing.report_tsv.")
    p.add_argument("--subjects", nargs="+", default=None, metavar="SUBJECT",
                   help="Only process these subjects (e.g. 002_S_0413 sub-ADNI130S1234). "
                        "Accepts ADNI ids or BIDS labels.")
    p.add_argument("--subject-list", default=None,
                   help="File with one subject id per line to restrict processing to.")
    p.add_argument("--sessions-csv", default=None,
                   help="CSV with subject + visit columns (e.g. SUBJECT_ID, VISCODE) to "
                        "restrict processing to specific subject/sessions.")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would change without modifying any sidecars.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        subject_keys = load_subject_filter(args.subjects, args.subject_list)
        session_keys = load_session_filter(args.sessions_csv)
        run(
            config_path=args.config_path,
            bids_dir=args.bids_dir,
            metadata_csv=args.metadata_csv,
            report_tsv=args.report_tsv,
            dry_run=args.dry_run,
            subject_keys=subject_keys,
            session_keys=session_keys,
        )
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"[insert_philips_slicetiming] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
