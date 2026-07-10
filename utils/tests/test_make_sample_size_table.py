"""Tests for s8_final_qc/make_sample_size_table.py."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "s8_final_qc" / "make_sample_size_table.py"

_spec = importlib.util.spec_from_file_location("make_sample_size_table", MODULE_PATH)
mst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mst)  # type: ignore[union-attr]


def _write_manifest(path: Path, rows) -> None:
    cols = ["stage", "folder", "description", "count_from", "subjects", "sessions"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _sessions_tsv(path: Path, pairs) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["sub", "ses"])
        for sub, ses in pairs:
            w.writerow([sub, ses])


def test_manual_counts_and_derived_drops(tmp_path: Path) -> None:
    manifest = tmp_path / "m.tsv"
    _write_manifest(manifest, [
        {"stage": "A", "folder": "s3/", "description": "start", "subjects": "100", "sessions": "200"},
        {"stage": "B", "folder": "s4/", "description": "mid", "subjects": "90", "sessions": "180"},
        {"stage": "C", "folder": "s5/", "description": "end", "subjects": "80", "sessions": "150"},
    ])
    stages = mst.load_stages(manifest, "sub", "ses")

    assert [s.remaining_str for s in stages] == ["100/200", "90/180", "80/150"]
    # First stage has no "dropped"; later stages are deltas from the previous.
    assert stages[0].dropped_str == "-"
    assert stages[1].dropped_str == "10/20"
    assert stages[2].dropped_str == "10/30"


def test_count_from_table(tmp_path: Path) -> None:
    sess = tmp_path / "included.tsv"
    _sessions_tsv(sess, [("sub-1", "ses-A"), ("sub-1", "ses-B"), ("sub-2", "ses-A")])
    manifest = tmp_path / "m.tsv"
    _write_manifest(manifest, [
        {"stage": "Start", "folder": "s3/", "description": "d", "subjects": "5", "sessions": "9"},
        {"stage": "Final", "folder": "s8/", "description": "d", "count_from": str(sess)},
    ])
    stages = mst.load_stages(manifest, "sub", "ses")

    # 2 unique subjects, 3 unique sessions counted from the table.
    assert stages[1].subjects == 2
    assert stages[1].sessions == 3
    assert stages[1].dropped_str == "3/6"


def test_markdown_bolds_final_row(tmp_path: Path) -> None:
    manifest = tmp_path / "m.tsv"
    _write_manifest(manifest, [
        {"stage": "A", "folder": "s3/", "description": "d", "subjects": "10", "sessions": "20"},
        {"stage": "Z", "folder": "s8/", "description": "d", "subjects": "8", "sessions": "15"},
    ])
    stages = mst.load_stages(manifest, "sub", "ses")
    md = mst.render_markdown(stages, bold_last=True)

    assert "| Pipeline Stage | GitHub Folder |" in md
    assert "**Z**" in md and "**8/15**" in md
    assert "`s3/`" in md  # folder rendered as inline code


def test_html_and_csv_render(tmp_path: Path) -> None:
    manifest = tmp_path / "m.tsv"
    _write_manifest(manifest, [
        {"stage": "A", "folder": "s3/", "description": "d", "subjects": "10", "sessions": "20"},
        {"stage": "Z", "folder": "s8/", "description": "d", "subjects": "8", "sessions": "15"},
    ])
    stages = mst.load_stages(manifest, "sub", "ses")

    html = mst.render_html(stages, title="My table")
    assert "<table>" in html and "My table" in html and 'class="final"' in html

    rows = list(csv.reader(mst.render_csv(stages).splitlines()))
    assert rows[0] == mst.HEADERS
    assert rows[-1] == ["Z", "s8/", "d", "2/5", "8/15"]


def test_warns_when_counts_increase(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    manifest = tmp_path / "m.tsv"
    _write_manifest(manifest, [
        {"stage": "A", "folder": "s3/", "description": "d", "subjects": "10", "sessions": "20"},
        {"stage": "B", "folder": "s4/", "description": "d", "subjects": "12", "sessions": "25"},
    ])
    mst.load_stages(manifest, "sub", "ses")
    assert "WARNING" in capsys.readouterr().err


def test_bad_row_raises(tmp_path: Path) -> None:
    manifest = tmp_path / "m.tsv"
    _write_manifest(manifest, [
        {"stage": "A", "folder": "s3/", "description": "no counts here"},
    ])
    with pytest.raises(ValueError):
        mst.load_stages(manifest, "sub", "ses")


def test_repo_manifest_renders(tmp_path: Path) -> None:
    """The committed manifest should load and render without error."""
    manifest = REPO_ROOT / "s8_final_qc" / "sample_size_stages.tsv"
    stages = mst.load_stages(manifest, "sub", "ses")
    assert len(stages) >= 5
    assert stages[0].dropped_str == "-"
    assert mst.render_markdown(stages).startswith("| Pipeline Stage")
