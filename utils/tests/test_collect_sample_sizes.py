"""Tests for s8_final_qc/collect_sample_sizes.py (pure logic; no s5 pipeline import)."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "s8_final_qc" / "collect_sample_sizes.py"

_spec = importlib.util.spec_from_file_location("collect_sample_sizes", MODULE_PATH)
csz = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csz)  # type: ignore[union-attr]


def test_id_normalization() -> None:
    assert csz.viscode_to_session("bl") == "ses-M000"
    assert csz.viscode_to_session("m6") == "ses-M006"
    assert csz.viscode_to_session("m144") == "ses-M144"
    assert csz.subject_viscode_to_bids("002_S_0413", "m60") == ("sub-ADNI002S0413", "ses-M060")


def test_n_subjects() -> None:
    ids = {("sub-1", "ses-A"), ("sub-1", "ses-B"), ("sub-2", "ses-A")}
    assert csz.n_subjects(ids) == 2


def test_build_stages_computes_subset_drops() -> None:
    # Nested id-sets: each stage a subset of the previous.
    idsets = {
        "start":       {("s1", "a"), ("s1", "b"), ("s2", "a"), ("s3", "a")},
        "clinica":     {("s1", "a"), ("s1", "b"), ("s2", "a")},        # dropped s3 (1 subj, 1 ses)
        "postclinica": {("s1", "a"), ("s1", "b")},                     # dropped s2 (1 subj, 1 ses)
        "mriqc":       {("s1", "a")},                                  # dropped s1/b (0 subj, 1 ses)
        "postmriqc":   {("s1", "a")},
        "fmriprep":    {("s1", "a")},
        "final":       {("s1", "a")},
    }
    stages = csz.build_stages(idsets)
    assert [(s.subjects, s.sessions) for s in stages][:4] == [(3, 4), (2, 3), (1, 2), (1, 1)]
    assert stages[0].dropped_str == "-"
    assert stages[1].dropped_str == "1/1"   # start -> clinica (subject s3 fully dropped)
    assert stages[2].dropped_str == "1/1"   # clinica -> postclinica (subject s2 fully dropped)
    assert stages[3].dropped_str == "0/1"   # postclinica -> mriqc (s1 keeps a session; one session lost)


def test_enforce_sequential_makes_cascade_monotonic() -> None:
    # fMRIPrep/final tables contain a "leaked" session ("s9","z") that never
    # survived post-MRIQC; enforce_sequential must drop it from those stages.
    raw = {
        "start":       {("s1", "a"), ("s1", "b"), ("s2", "a")},
        "clinica":     {("s1", "a"), ("s1", "b"), ("s2", "a")},
        "postclinica": {("s1", "a"), ("s1", "b")},
        "mriqc":       {("s1", "a"), ("s1", "b")},
        "postmriqc":   {("s1", "a")},
        "fmriprep":    {("s1", "a"), ("s9", "z")},   # ("s9","z") leaked in
        "final":       {("s1", "a"), ("s9", "z")},   # leaked here too
    }
    eff = csz.enforce_sequential(raw)

    # Each stage is a subset of the previous.
    order = [k for k, *_ in csz.STAGE_META]
    for prev, cur in zip(order, order[1:], strict=False):
        assert eff[cur] <= eff[prev], f"{cur} not a subset of {prev}"

    # The leaked session is gone; only the truly-surviving session remains.
    assert ("s9", "z") not in eff["fmriprep"]
    assert eff["fmriprep"] == {("s1", "a")}
    assert eff["final"] == {("s1", "a")}


def test_ids_from_bids_table_tsv_and_csv(tmp_path: Path) -> None:
    tsv = tmp_path / "sessions.tsv"
    with tsv.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["sub", "ses", "extra"])
        w.writerow(["sub-ADNI001S0001", "ses-M000", "x"])
        w.writerow(["sub-ADNI001S0001", "ses-M006", "y"])
    ids = csz.ids_from_bids_table(tsv)
    assert ids == {("sub-ADNI001S0001", "ses-M000"), ("sub-ADNI001S0001", "ses-M006")}


def test_write_manifest_roundtrips_and_renders(tmp_path: Path) -> None:
    idsets = {k: {("s1", "a")} for k, *_ in csz.STAGE_META}
    idsets["start"] = {("s1", "a"), ("s2", "a")}
    stages = csz.build_stages(idsets)
    manifest = tmp_path / "m.tsv"
    csz.write_manifest(stages, manifest)

    rows = list(csv.DictReader(manifest.open(newline=""), delimiter="\t"))
    assert rows[0]["stage"] == "Unzip & organize DICOMs"
    assert rows[0]["sessions"] == "2"

    # The renderer used by the whole toolchain should accept the written manifest.
    from importlib import import_module
    import sys
    sys.path.insert(0, str(REPO_ROOT / "s8_final_qc"))
    mst = import_module("make_sample_size_table")
    loaded = mst.load_stages(manifest, "sub", "ses")
    assert loaded[0].sessions == 2
