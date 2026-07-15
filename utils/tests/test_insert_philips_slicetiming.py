"""Tests for s4b_slice_timing/insert_philips_slicetiming.py.

These build a small synthetic BIDS tree and ADNI fMRI-metadata CSV, then check
matching, absolute->relative SliceTiming conversion, pattern flagging, dry-run,
and the various skip/unmatched statuses. No real neuroimaging data is required
(no NIfTI files, so nibabel is not needed).
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from typing import Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "s4b_slice_timing" / "insert_philips_slicetiming.py"

_spec = importlib.util.spec_from_file_location("insert_philips_slicetiming", MODULE_PATH)
stc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stc)  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
STANDARD_PATTERN = "(1, 3, 5, ...)"

# Even-then-odd interleave over 6 slices, TR=1.2s (per-slice 0.2s).
# Acquisition order 0,2,4,1,3,5 -> per-index relative times below -> "(1, 3, 5, ...)".
STD_REL = [0.0, 0.6, 0.2, 0.8, 0.4, 1.0]
# Sequential ascending -> "(1, 2, 3, ...)" -> non-standard / flagged.
SEQ_REL = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def _abs_string(rel: List[float], base: float = 100.0) -> str:
    """Turn per-index relative times into an ADNI-style absolute SLICETIMING string."""
    return "_".join(str(round(base + t, 6)) for t in rel)


def _write_json(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")


def _bold_json_path(bids: Path, sub: str, ses: str) -> Path:
    return bids / f"sub-{sub}" / f"ses-{ses}" / "func" / f"sub-{sub}_ses-{ses}_task-rest_bold.json"


def _write_metadata_csv(path: Path, rows: List[Dict]) -> None:
    cols = ["RID", "VISCODE2", "MANUFACTURER", "MANUFACTURERSMODELNAME",
            "REPETITIONTIME", "SERIESNUMBER", "SLICETIMING"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_config(path: Path, **overrides) -> None:
    st = {
        "manufacturers": ["Philips"],
        "standard_slice_pattern": STANDARD_PATTERN,
        "write_flagged": True,
        "skip_if_present": True,
        "backup_json": True,
        "tr_tolerance_s": 0.1,
    }
    st.update(overrides)
    lines = ["slice_timing:"]
    for k, v in st.items():
        if isinstance(v, list):
            lines.append(f"  {k}: [{', '.join(repr(x) for x in v)}]")
        elif isinstance(v, bool):
            lines.append(f"  {k}: {'true' if v else 'false'}")
        elif isinstance(v, str):
            lines.append(f'  {k}: "{v}"')
        else:
            lines.append(f"  {k}: {v}")
    lines += ["paths:", "  clinica_bids_dir: /unused", "  adni_fmri_metadata_csv: /unused"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _base_setup(tmp_path: Path, **cfg_overrides):
    """Create a config, BIDS tree, and metadata CSV. Return (cfg, bids, csv, report)."""
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, **cfg_overrides)
    bids = tmp_path / "rawdata"
    csv_path = tmp_path / "fmri_meta.csv"
    report = tmp_path / "report.tsv"
    return cfg, bids, csv_path, report


def _run(cfg, bids, csv_path, report, dry_run=False):
    return stc.run(
        config_path=str(cfg),
        bids_dir=str(bids),
        metadata_csv=str(csv_path),
        report_tsv=str(report),
        dry_run=dry_run,
    )


def _report_rows(report: Path) -> List[Dict[str, str]]:
    with report.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


# --------------------------------------------------------------------------- #
# Unit-level checks
# --------------------------------------------------------------------------- #
def test_parse_and_pattern() -> None:
    rel = stc.parse_abs_slice_timing(_abs_string(STD_REL))
    assert rel == STD_REL
    assert stc.acquisition_pattern(rel) == STANDARD_PATTERN
    assert stc.acquisition_pattern(SEQ_REL) == "(1, 2, 3, ...)"


def test_viscode_and_rid() -> None:
    assert stc.viscode_to_session("bl") == "M000"
    assert stc.viscode_to_session("m6") == "M006"
    assert stc.viscode_to_session("m144") == "M144"
    assert stc.viscode_to_session("scmri") is None
    assert stc.subject_to_rid("sub-ADNI002S0413") == 413


# --------------------------------------------------------------------------- #
# End-to-end behaviour
# --------------------------------------------------------------------------- #
def test_writes_slicetiming_for_matched_philips(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    js = _bold_json_path(bids, "ADNI002S0413", "M000")
    _write_json(js, {"Manufacturer": "Philips Medical Systems",
                     "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [{
        "RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips_Medical_Systems",
        "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
        "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}])

    summary = _run(cfg, bids, csv_path, report)

    assert summary.get("written") == 1
    data = json.loads(js.read_text())
    assert data["SliceTiming"] == STD_REL
    # Original preserved as a .bak backup.
    assert js.with_suffix(".json.bak").exists()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    js = _bold_json_path(bids, "ADNI002S0413", "M000")
    _write_json(js, {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [{
        "RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips",
        "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
        "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}])

    summary = _run(cfg, bids, csv_path, report, dry_run=True)

    assert summary.get("would_write") == 1
    assert "SliceTiming" not in json.loads(js.read_text())
    assert not js.with_suffix(".json.bak").exists()
    assert report.exists()  # report is written even on dry runs


def test_flagged_pattern_written_but_marked(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    js = _bold_json_path(bids, "ADNI002S0413", "M000")
    _write_json(js, {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [{
        "RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips",
        "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
        "SERIESNUMBER": "5", "SLICETIMING": _abs_string(SEQ_REL)}])

    summary = _run(cfg, bids, csv_path, report)

    assert summary.get("written_flagged") == 1
    assert json.loads(js.read_text())["SliceTiming"] == SEQ_REL
    row = _report_rows(report)[0]
    assert row["flagged"] == "yes"
    assert row["slice_pattern"] == "(1, 2, 3, ...)"


def test_flagged_skipped_when_write_flagged_false(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path, write_flagged=False)
    js = _bold_json_path(bids, "ADNI002S0413", "M000")
    _write_json(js, {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [{
        "RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips",
        "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
        "SERIESNUMBER": "5", "SLICETIMING": _abs_string(SEQ_REL)}])

    summary = _run(cfg, bids, csv_path, report)

    assert summary.get("skipped_flagged") == 1
    assert "SliceTiming" not in json.loads(js.read_text())


def test_skips_non_philips_and_present(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    siemens = _bold_json_path(bids, "ADNI002S0001", "M000")
    _write_json(siemens, {"Manufacturer": "SIEMENS", "RepetitionTime": 1.2, "SeriesNumber": 5})
    present = _bold_json_path(bids, "ADNI002S0413", "M000")
    _write_json(present, {"Manufacturer": "Philips", "RepetitionTime": 1.2,
                          "SeriesNumber": 5, "SliceTiming": [9.9]})
    _write_metadata_csv(csv_path, [{
        "RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips",
        "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
        "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}])

    summary = _run(cfg, bids, csv_path, report)

    assert summary.get("skipped_not_target") == 1
    assert summary.get("skipped_present") == 1
    assert json.loads(present.read_text())["SliceTiming"] == [9.9]  # untouched


def test_normalize_subject_accepts_spellings() -> None:
    for token in ("002_S_0413", "sub-ADNI002S0413", "ADNI002S0413", "002S0413", "002-s-0413"):
        assert stc.normalize_subject(token) == "002S0413"


def test_subject_filter_restricts_processing(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    for sub, rid in (("ADNI002S0413", "413"), ("ADNI130S1234", "1234")):
        js = _bold_json_path(bids, sub, "M000")
        _write_json(js, {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [
        {"RID": r, "VISCODE2": "bl", "MANUFACTURER": "Philips",
         "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
         "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}
        for r in ("413", "1234")])

    keys = stc.load_subject_filter(["002_S_0413"], None)  # ADNI id spelling
    summary = stc.run(config_path=str(cfg), bids_dir=str(bids), metadata_csv=str(csv_path),
                      report_tsv=str(report), subject_keys=keys)

    # Only the requested subject is written; the other is untouched.
    assert summary.get("written") == 1
    assert "SliceTiming" in json.loads(_bold_json_path(bids, "ADNI002S0413", "M000").read_text())
    assert "SliceTiming" not in json.loads(_bold_json_path(bids, "ADNI130S1234", "M000").read_text())


def test_subject_filter_from_list_file(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    _write_json(_bold_json_path(bids, "ADNI002S0413", "M000"),
                {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [
        {"RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips",
         "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
         "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}])
    list_file = tmp_path / "subs.txt"
    list_file.write_text("# targeted\nsub-ADNI002S0413\n", encoding="utf-8")

    keys = stc.load_subject_filter(None, str(list_file))
    summary = stc.run(config_path=str(cfg), bids_dir=str(bids), metadata_csv=str(csv_path),
                      report_tsv=str(report), subject_keys=keys)
    assert summary.get("written") == 1


def test_no_subject_filter_processes_all(tmp_path: Path) -> None:
    assert stc.load_subject_filter(None, None) is None


def _write_sessions_csv(path: Path, rows: List[tuple]) -> None:
    """rows: (SUBJECT_ID, VISCODE)."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["VISCODE", "SCANDATE", "SERIES_ID", "IMAGE_ID", "SUBJECT_ID"])
        for sub, vis in rows:
            w.writerow([vis, "2012-05-15", "150694", "304790", sub])


def test_load_session_filter_maps_viscodes(tmp_path: Path) -> None:
    sess = tmp_path / "philips_sessions.csv"
    _write_sessions_csv(sess, [("002_S_0413", "m72"), ("002_S_0413", "bl"),
                               ("006_S_0498", "m108")])
    pairs = stc.load_session_filter(str(sess))
    assert pairs == {("002S0413", "M072"), ("002S0413", "M000"), ("006S0498", "M108")}


def test_load_session_filter_bad_columns_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        stc.load_session_filter(str(bad))


def test_session_filter_restricts_to_listed_pairs(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    # Same subject, two sessions on disk; only one is in the sessions list.
    for ses in ("M072", "M084"):
        _write_json(_bold_json_path(bids, "ADNI002S0413", ses),
                    {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [
        {"RID": "413", "VISCODE2": vis, "MANUFACTURER": "Philips",
         "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
         "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}
        for vis in ("m72", "m84")])

    sess = tmp_path / "philips_sessions.csv"
    _write_sessions_csv(sess, [("002_S_0413", "m72")])  # only M072

    summary = stc.run(config_path=str(cfg), bids_dir=str(bids), metadata_csv=str(csv_path),
                      report_tsv=str(report), session_keys=stc.load_session_filter(str(sess)))

    assert summary.get("written") == 1
    assert "SliceTiming" in json.loads(_bold_json_path(bids, "ADNI002S0413", "M072").read_text())
    assert "SliceTiming" not in json.loads(_bold_json_path(bids, "ADNI002S0413", "M084").read_text())


def test_only_resting_state_bold_is_touched(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    # A non-resting BOLD run for the same subject/session should be ignored.
    other = (bids / "sub-ADNI002S0413" / "ses-M000" / "func"
             / "sub-ADNI002S0413_ses-M000_task-nback_bold.json")
    _write_json(other, {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    rest = _bold_json_path(bids, "ADNI002S0413", "M000")
    _write_json(rest, {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [{
        "RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips",
        "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
        "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}])

    summary = _run(cfg, bids, csv_path, report)

    assert summary.get("written") == 1  # only the task-rest sidecar
    assert json.loads(rest.read_text())["SliceTiming"] == STD_REL
    assert "SliceTiming" not in json.loads(other.read_text())


def test_unmatched_when_no_metadata_row(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    js = _bold_json_path(bids, "ADNI002S0999", "M000")
    _write_json(js, {"Manufacturer": "Philips", "RepetitionTime": 1.2, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [{
        "RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips",
        "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
        "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}])

    summary = _run(cfg, bids, csv_path, report)

    assert summary.get("unmatched") == 1
    assert "SliceTiming" not in json.loads(js.read_text())


def test_validation_failed_on_tr_mismatch(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    js = _bold_json_path(bids, "ADNI002S0413", "M000")
    _write_json(js, {"Manufacturer": "Philips", "RepetitionTime": 2.0, "SeriesNumber": 5})
    _write_metadata_csv(csv_path, [{
        "RID": "413", "VISCODE2": "bl", "MANUFACTURER": "Philips",
        "MANUFACTURERSMODELNAME": "Achieva", "REPETITIONTIME": "1200",
        "SERIESNUMBER": "5", "SLICETIMING": _abs_string(STD_REL)}])

    summary = _run(cfg, bids, csv_path, report)

    assert summary.get("validation_failed") == 1
    assert "SliceTiming" not in json.loads(js.read_text())


def test_missing_bids_dir_raises(tmp_path: Path) -> None:
    cfg, bids, csv_path, report = _base_setup(tmp_path)
    _write_metadata_csv(csv_path, [])
    with pytest.raises(FileNotFoundError):
        _run(cfg, tmp_path / "does_not_exist", csv_path, report)
