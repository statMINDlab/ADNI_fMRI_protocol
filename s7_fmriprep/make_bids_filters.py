#!/usr/bin/env python
"""Write per-subject fMRIPrep BIDS filter files from a subject+session CSV.

fMRIPrep can only be scoped to specific sessions via a ``--bids-filter-file``
(there is no ``--session-label``). This helper reads a CSV listing the exact
subject/sessions to run and, for each subject, writes
``<filter_dir>/<sub-ADNIxxx>_filter.json`` restricting BOLD and anatomy to those
sessions. It prints the subject ids (one per line) to stdout so the calling
driver can build its job array.

The CSV needs a subject column (SUBJECT_ID / PTID / RID / SUBJECT) and a visit
column (VISCODE / VISCODE2); other columns are ignored, so the ADNI
Philips-sessions export works directly. Visit codes map to BIDS sessions the
usual way (``bl`` -> ``M000``, ``m72`` -> ``M072``).

Usage:
    python make_bids_filters.py --sessions-csv philips_sessions.csv --filter-dir DIR
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

SUBJECT_COLS = ("subject_id", "subject", "ptid", "rid", "sub")
VISIT_COLS = ("viscode2", "viscode", "visit", "session", "ses")


def normalize_subid(token: str) -> str:
    """``002_S_0413`` | ``sub-ADNI002S0413`` | ``ADNI002S0413`` -> ``sub-ADNI002S0413``."""
    s = re.sub(r"[^A-Za-z0-9]", "", str(token)).upper()
    for prefix in ("SUB", "ADNI"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return f"sub-ADNI{s}" if s else ""


def session_label(value: str) -> Optional[str]:
    """Map a visit code (``bl``, ``m72``, ``M072``, ``ses-M072``) to ``M072``."""
    v = re.sub(r"(?i)^ses-", "", str(value).strip()).lower()
    if v in ("bl", "m0", "m00", "m000"):
        return "M000"
    m = re.match(r"^m(\d+)$", v)
    return f"M{int(m.group(1)):03d}" if m else None


def load_subject_sessions(csv_path: Path) -> Dict[str, Set[str]]:
    """Return ``{sub-ADNIxxx: {session_label, ...}}`` from the CSV."""
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        low = {c.lower(): c for c in (reader.fieldnames or [])}
        sub_col = next((low[c] for c in SUBJECT_COLS if c in low), None)
        vis_col = next((low[c] for c in VISIT_COLS if c in low), None)
        if sub_col is None or vis_col is None:
            raise ValueError(
                f"{csv_path}: need a subject column {SUBJECT_COLS} and a visit column "
                f"{VISIT_COLS}; found {reader.fieldnames}"
            )
        out: Dict[str, Set[str]] = {}
        for row in reader:
            sub = normalize_subid(row.get(sub_col, ""))
            ses = session_label(row.get(vis_col, ""))
            if sub and ses:
                out.setdefault(sub, set()).add(ses)
    return out


def build_filter(sessions: List[str], task: str) -> dict:
    """A fMRIPrep bids-filter restricting BOLD + anatomy to ``sessions``."""
    return {
        "bold": {"datatype": "func", "suffix": "bold", "session": sessions, "task": task},
        "t1w": {"datatype": "anat", "suffix": "T1w", "session": sessions},
        "t2w": {"datatype": "anat", "suffix": "T2w", "session": sessions},
    }


def write_filters(subject_sessions: Dict[str, Set[str]], filter_dir: Path,
                  task: str) -> List[str]:
    """Write one filter JSON per subject; return the sorted subject ids."""
    filter_dir.mkdir(parents=True, exist_ok=True)
    for sub, sessions in subject_sessions.items():
        flt = build_filter(sorted(sessions), task)
        (filter_dir / f"{sub}_filter.json").write_text(
            json.dumps(flt, indent=2) + "\n", encoding="utf-8")
    return sorted(subject_sessions)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sessions-csv", required=True, help="Subject+session CSV.")
    p.add_argument("--filter-dir", required=True,
                   help="Directory to write <subid>_filter.json files into.")
    p.add_argument("--task", default="rest", help="BOLD task label (default: rest).")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    csv_path = Path(args.sessions_csv)
    if not csv_path.is_file():
        print(f"[make_bids_filters] sessions CSV not found: {csv_path}", file=sys.stderr)
        return 1
    try:
        subject_sessions = load_subject_sessions(csv_path)
    except ValueError as e:
        print(f"[make_bids_filters] {e}", file=sys.stderr)
        return 1
    if not subject_sessions:
        print("[make_bids_filters] no subject/session pairs parsed from CSV", file=sys.stderr)
        return 1
    for sub in write_filters(subject_sessions, Path(args.filter_dir), args.task):
        print(sub)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
