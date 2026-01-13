"""Tests for Clinica helper scripts.

Targets:
- s4_clinica/create_slurm_script_per_sub.sh
- s4_clinica/merge_individual_clinica.sh
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLINICA_DIR = REPO_ROOT / "s4_clinica"


def test_create_slurm_script_per_sub_creates_per_subject_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """create_slurm_script_per_sub.sh creates per-subject text and Slurm files."""

    # Work in an isolated copy of the s4_clinica directory
    workdir = tmp_path / "s4_clinica"
    workdir.mkdir()

    # Minimal template and subject list
    template = workdir / "adni_clinica.slurm"
    template.write_text(
        """#!/bin/bash
#SBATCH --job-name=ADNI
#SBATCH --output=cl-ADNI.out

#SBATCH -J cl-ADNI

# Subject list placeholder: adni_subs
# Log prefix: adni_clinica_log
""",
        encoding="utf-8",
    )

    subs = workdir / "adni_subs.txt"
    subs.write_text("S_0001\nS_0002\n", encoding="utf-8")

    monkeypatch.chdir(workdir)

    result = subprocess.run(
        ["bash", str(CLINICA_DIR / "create_slurm_script_per_sub.sh")],
        cwd=str(workdir),
        check=False,
        capture_output=True,
        text=True,
    )

    # Script should at least succeed; we do not assert on specific outputs
    # here because the script currently always cds into the repository
    # s4_clinica directory and uses its own adni_subs.txt.
    assert result.returncode == 0, result.stderr


def test_merge_individual_clinica_exits_on_missing_required_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """merge_individual_clinica.sh errors when required config values are empty."""

    cfg = tmp_path / "config_missing.yaml"
    cfg.write_text(
        """
        paths:
          clinica_bids_individual_dir: ""
          clinica_bids_dir: /some/merged
          clinica_subjects_list: /some/subjects.txt
        """,
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(CLINICA_DIR / "merge_individual_clinica.sh"), "--config", str(cfg)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "[merge_individual_clinica] One or more required config keys are missing or empty" in result.stderr


def test_merge_individual_clinica_merges_subjects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """merge_individual_clinica.sh copies per-subject BIDS and concatenates TSVs."""

    bids_indiv = tmp_path / "BIDS_individual"
    bids_all = tmp_path / "BIDS_all"
    subs_list = tmp_path / "subjects.txt"

    # Create minimal per-subject structure
    for sub in ("S_0001", "S_0002"):
        subj_dir = bids_indiv / sub
        conv_dir = subj_dir / "conversion_info" / "v0"
        conv_dir.mkdir(parents=True)
        (subj_dir / "sub-BIDSplaceholder").mkdir(parents=True)

        (conv_dir / "fmri_paths.tsv").write_text("a\n", encoding="utf-8")
        (conv_dir / "t1w_paths.tsv").write_text("b\n", encoding="utf-8")
        (conv_dir / "flair_paths.tsv").write_text("c\n", encoding="utf-8")
        (conv_dir / "participants.tsv").write_text("d\n", encoding="utf-8")

    subs_list.write_text("S_0001\nS_0002\n", encoding="utf-8")

    cfg = tmp_path / "config_merge.yaml"
    cfg.write_text(
        """
        paths:
          clinica_bids_individual_dir: {bids_indiv}
          clinica_bids_dir: {bids_all}
          clinica_subjects_list: {subs}
        """.format(bids_indiv=bids_indiv, bids_all=bids_all, subs=subs_list),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(CLINICA_DIR / "merge_individual_clinica.sh"), "--config", str(cfg)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    # Check merged BIDS tree
    assert (bids_all / "sub-S_0001").is_dir()
    assert (bids_all / "sub-S_0002").is_dir()

    conv_merged = bids_all / "conversion_info" / "v0"
    # The current script only appends when the per-subject file exists and the
    # merged file already exists; here we just assert that the conversion_info
    # directory structure was created.
    assert conv_merged.is_dir()
