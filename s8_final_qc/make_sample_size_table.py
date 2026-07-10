"""Render the pipeline sample-size table (subjects/sessions kept & dropped per stage).

The counts live in an editable manifest TSV (``qc.sample_size_manifest``,
default ``s8_final_qc/sample_size_stages.tsv``) with one row per pipeline stage:

    stage   folder   description   count_from   subjects   sessions

For each stage the remaining subject/session counts come from either:
  * ``count_from`` -- a path to a sessions table (e.g. included_sessions.tsv) with
    ``sub`` and ``ses`` columns, from which unique subjects and sessions are
    counted automatically; or
  * the manual ``subjects``/``sessions`` values, when ``count_from`` is empty.

The "Dropped (Sub/Ses)" column is *derived* as the drop from the previous stage,
so the table is always internally consistent (remaining_prev - remaining_now).

Usage
-----
    python s8_final_qc/make_sample_size_table.py                 # Markdown to stdout
    python s8_final_qc/make_sample_size_table.py --format html --output table.html
    python s8_final_qc/make_sample_size_table.py --format csv --output sample_sizes.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_MANIFEST = REPO_ROOT / "s8_final_qc" / "sample_size_stages.tsv"
HEADERS = ["Pipeline Stage", "GitHub Folder", "Description",
           "Dropped (Sub/Ses)", "Subjects/Sessions"]


class Stage:
    def __init__(self, label: str, folder: str, description: str,
                 subjects: int, sessions: int) -> None:
        self.label = label
        self.folder = folder
        self.description = description
        self.subjects = subjects
        self.sessions = sessions
        # Filled in once the full ordered list is known.
        self.dropped_subjects: Optional[int] = None
        self.dropped_sessions: Optional[int] = None

    @property
    def remaining_str(self) -> str:
        return f"{self.subjects}/{self.sessions}"

    @property
    def dropped_str(self) -> str:
        if self.dropped_subjects is None or self.dropped_sessions is None:
            return "-"
        return f"{self.dropped_subjects}/{self.dropped_sessions}"


def _delimiter_for(path: Path) -> str:
    return "\t" if path.suffix.lower() in (".tsv", ".tab") else ","


def count_sessions_table(path: Path, sub_col: str, ses_col: str) -> Tuple[int, int]:
    """Return (unique subjects, unique sessions) from a sessions table."""
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter=_delimiter_for(path))
        if reader.fieldnames is None or sub_col not in reader.fieldnames:
            raise ValueError(f"{path} has no '{sub_col}' column (columns: {reader.fieldnames})")
        subs = set()
        sess = set()
        has_ses = ses_col in reader.fieldnames
        for row in reader:
            sub = (row.get(sub_col) or "").strip()
            if not sub:
                continue
            subs.add(sub)
            ses = (row.get(ses_col) or "").strip() if has_ses else ""
            sess.add((sub, ses))
    return len(subs), len(sess)


def load_stages(manifest: Path, sub_col: str, ses_col: str) -> List[Stage]:
    """Read the manifest and resolve each stage's remaining counts."""
    with manifest.open(newline="") as f:
        reader = csv.DictReader(f, delimiter=_delimiter_for(manifest))
        required = {"stage", "folder", "description"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{manifest} is missing columns: {sorted(missing)}")
        rows = list(reader)

    stages: List[Stage] = []
    for i, row in enumerate(rows, start=1):
        label = (row.get("stage") or "").strip()
        if not label:
            continue
        count_from = (row.get("count_from") or "").strip()
        if count_from:
            path = Path(count_from)
            if not path.is_absolute():
                path = REPO_ROOT / path
            if not path.is_file():
                raise FileNotFoundError(
                    f"stage '{label}': count_from table not found: {path}")
            subjects, sessions = count_sessions_table(path, sub_col, ses_col)
        else:
            try:
                subjects = int(str(row.get("subjects", "")).strip())
                sessions = int(str(row.get("sessions", "")).strip())
            except ValueError as e:
                raise ValueError(
                    f"stage '{label}' (row {i}): needs numeric subjects/sessions "
                    f"or a count_from table ({e})") from e
        stages.append(Stage(label, (row.get("folder") or "").strip(),
                            (row.get("description") or "").strip(), subjects, sessions))

    _compute_drops(stages)
    return stages


def _compute_drops(stages: List[Stage]) -> None:
    for prev, cur in zip(stages, stages[1:], strict=False):
        cur.dropped_subjects = prev.subjects - cur.subjects
        cur.dropped_sessions = prev.sessions - cur.sessions
        if cur.dropped_subjects < 0 or cur.dropped_sessions < 0:
            print(
                f"[make_sample_size_table] WARNING: '{cur.label}' has more "
                f"subjects/sessions than the previous stage "
                f"({prev.remaining_str} -> {cur.remaining_str}); check the manifest.",
                file=sys.stderr,
            )


# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #
def render_markdown(stages: List[Stage], bold_last: bool = True) -> str:
    lines = ["| " + " | ".join(HEADERS) + " |",
             "|" + "|".join([" --- "] * len(HEADERS)) + "|"]
    for idx, s in enumerate(stages):
        last = bold_last and idx == len(stages) - 1
        stage = f"**{s.label}**" if last else s.label
        remaining = f"**{s.remaining_str}**" if last else s.remaining_str
        folder = f"`{s.folder}`" if s.folder else ""
        lines.append("| " + " | ".join(
            [stage, folder, s.description, s.dropped_str, remaining]) + " |")
    return "\n".join(lines) + "\n"


def render_csv(stages: List[Stage]) -> str:
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    for s in stages:
        w.writerow([s.label, s.folder, s.description, s.dropped_str, s.remaining_str])
    return buf.getvalue()


def render_html(stages: List[Stage], bold_last: bool = True,
                title: str = "Sample size by pipeline stage") -> str:
    def esc(x: str) -> str:
        return html.escape(x, quote=True)

    rows_html = []
    for idx, s in enumerate(stages):
        last = bold_last and idx == len(stages) - 1
        cls = ' class="final"' if last else ""
        folder = f"<code>{esc(s.folder)}</code>" if s.folder else ""
        rows_html.append(
            f"    <tr{cls}>"
            f"<td>{esc(s.label)}</td>"
            f"<td>{folder}</td>"
            f"<td>{esc(s.description)}</td>"
            f"<td class='num'>{esc(s.dropped_str)}</td>"
            f"<td class='num'>{esc(s.remaining_str)}</td>"
            f"</tr>"
        )
    head = "".join(f"<th>{esc(h)}</th>" for h in HEADERS)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
          margin: 2rem; color: #111; }}
  table {{ border-collapse: collapse; font-size: 15px; }}
  caption {{ text-align: left; font-weight: 600; margin-bottom: .6rem; font-size: 16px; }}
  th, td {{ border: 1px solid #222; padding: 8px 12px; text-align: left; vertical-align: top; }}
  thead th {{ background: #f0f2f5; font-weight: 700; }}
  td.num, th.num {{ text-align: right; white-space: nowrap; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }}
  tr.final td {{ font-weight: 700; background: #fafafa; }}
</style>
</head>
<body>
<table>
  <caption>{esc(title)}</caption>
  <thead><tr>{head}</tr></thead>
  <tbody>
{chr(10).join(rows_html)}
  </tbody>
</table>
</body>
</html>
"""


RENDERERS = {"md": render_markdown, "markdown": render_markdown,
             "csv": render_csv, "html": render_html}


def _default_manifest() -> Path:
    """Resolve the manifest path from config if available, else the repo default."""
    try:
        from utils.config_tools import load_config, get_value
        cfg = load_config()
        return Path(get_value(cfg, "sample_size.manifest"))
    except Exception:
        return DEFAULT_MANIFEST


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--manifest", default=None,
                   help="Path to the stage manifest TSV (default: qc.sample_size_manifest).")
    p.add_argument("--format", choices=["md", "markdown", "csv", "html"], default="md")
    p.add_argument("--output", default=None, help="Write to this file instead of stdout.")
    p.add_argument("--title", default="Sample size by pipeline stage",
                   help="Caption/title for --format html.")
    p.add_argument("--sub-col", default="sub", help="Subject column in count_from tables.")
    p.add_argument("--ses-col", default="ses", help="Session column in count_from tables.")
    p.add_argument("--no-bold-last", action="store_true",
                   help="Do not bold the final row.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    manifest = Path(args.manifest) if args.manifest else _default_manifest()
    if not manifest.is_absolute():
        manifest = REPO_ROOT / manifest
    if not manifest.is_file():
        print(f"[make_sample_size_table] manifest not found: {manifest}", file=sys.stderr)
        return 1

    try:
        stages = load_stages(manifest, args.sub_col, args.ses_col)
    except (FileNotFoundError, ValueError) as e:
        print(f"[make_sample_size_table] {e}", file=sys.stderr)
        return 1
    if not stages:
        print(f"[make_sample_size_table] no stages found in {manifest}", file=sys.stderr)
        return 1

    renderer = RENDERERS[args.format]
    if renderer is render_markdown:
        text = render_markdown(stages, bold_last=not args.no_bold_last)
    elif renderer is render_html:
        text = render_html(stages, bold_last=not args.no_bold_last, title=args.title)
    else:
        text = render_csv(stages)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[make_sample_size_table] wrote {args.format} for {len(stages)} stages -> {out}",
              file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
