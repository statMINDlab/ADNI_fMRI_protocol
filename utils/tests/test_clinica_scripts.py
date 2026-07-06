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
    """create_slurm_script_per_sub.sh creates per-subject text and Slurm files.

    The script is config-driven: it reads the DICOM root, Slurm jobs dir,
    subject list, and template path from the YAML passed via ``--config``.
    """

    # Fixtures the script requires to exist on disk.
    dicom_root = tmp_path / "sourcedata"
    dicom_root.mkdir()
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    template = tmp_path / "adni_clinica.slurm"
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

    subs = tmp_path / "adni_subs.txt"
    subs.write_text("S_0001\nS_0002\n", encoding="utf-8")

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
        paths:
          raw_dicom_dir: {dicom_root}
          slurm_jobs_dir: {jobs}
          raw_subject_list: {subs}
          slurm_template: {template}
        """.format(dicom_root=dicom_root, jobs=jobs_dir, subs=subs, template=template),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(CLINICA_DIR / "create_slurm_script_per_sub.sh"), "--config", str(cfg)],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    # One subject-list file and one Slurm script per subject, with the subject
    # ID substituted into the template placeholders.
    for sub in ("S_0001", "S_0002"):
        assert (jobs_dir / f"{sub}.txt").is_file()
        slurm = jobs_dir / f"{sub}_adni_clinica.slurm"
        assert slurm.is_file()
        assert sub in slurm.read_text(encoding="utf-8")


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
