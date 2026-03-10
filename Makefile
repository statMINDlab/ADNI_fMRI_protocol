# Makefile for ADNI_fMRI_protocol
# Lightweight orchestration over the 8 protocol steps.
#
# Usage examples:
#   make step3            # run unzip/organize/QC download
#   make step4            # run Clinica adni-to-bids conversion
#   make step6            # run MRIQC
#   make step7            # run fMRIPrep
#   make all              # run all computational steps (3–8)

CONFIG ?= config/config_adni.yaml

.PHONY: all \
        step1 step2 step3 step4 step5 step6 step7 step8 \
        download organize clinica post_clinica_qc mriqc fmriprep final_qc \
        test lint

# By default, only run the automated parts (3–8).
all: step3 step4 step5 step6 step7 step8

########################################
# Step 1: Account & Access (manual)
########################################
step1:
	@echo "Step 1 is manual: create ADNI / LONI account, sign DUA."
	@echo "See s1_setup_account/README.md for detailed instructions."

########################################
# Step 2: Build & Download Image Collection (manual via LONI)
########################################
step2 download:
	@echo "Step 2 is manual in the LONI IDA interface."
	@echo "See s2_download/README.md for walkthrough and screenshots."
	@echo "Place downloaded zip files in the directory specified in:"
	@echo "  $(CONFIG) under paths.raw_zip_dir"

########################################
# Step 3: Unzip, organize, and QC download
########################################
# Assumes you create a script like:
#   s3_organize/run_s3_organize.sh --config config/config_adni.yaml
########################################
step3 organize:
	@echo "Running Step 3: unzip, organize, and initial QC of downloads..."
	bash s3_organize/run_s3_organize.sh --config $(CONFIG)

########################################
# Step 4: Clinica (DCM -> NIfTI & BIDS)
########################################
# Assumes a wrapper script around Clinica, e.g.:
#   s4_clinica/run_clinica_adni2bids.sh --config config/config_adni.yaml
########################################
step4 clinica:
	@echo "Running Step 4: Clinica DICOM->NIfTI and BIDS conversion..."
	bash s4_clinica/run_clinica_adni2bids.sh --config $(CONFIG)

########################################
# Step 5: Post-Clinica QC
########################################
# Assumes something like:
#   s5_post_clinica_qc/run_post_clinica_qc.sh --config config/config_adni.yaml
########################################
step5 post_clinica_qc:
	@echo "Running Step 5: Post-Clinica QC and QC tables..."
	bash s5_post_clinica_qc/run_post_clinica_qc.sh --config $(CONFIG)

########################################
# Step 6: MRIQC
########################################
# Assumes a Slurm or local wrapper script, e.g.:
#   s6_mriqc/run_mriqc_array.sh --config config/config_adni.yaml
# that reads paths.mriqc_* and mriqc.* from the YAML file.
########################################
step6 mriqc:
	@echo "Running Step 6: MRIQC (participant-level and/or group-level)..."
	bash s6_mriqc/run_mriqc_array.sh --config $(CONFIG)

########################################
# Step 7: fMRIPrep
########################################
# Assumes a Slurm or local wrapper script, e.g.:
#   s7_fmriprep/run_fmriprep_array.sh --config config/config_adni.yaml
# which uses fmriprep.* and containers.* from the YAML.
########################################
step7 fmriprep:
	@echo "Running Step 7: fMRIPrep on QC-passed sessions..."
	bash s7_fmriprep/run_fmriprep_array.sh --config $(CONFIG)

########################################
# Step 8: Final QC + inclusion/exclusion tables
########################################
# Assumes:
#   s8_final_qc/run_final_qc.sh --config config/config_adni.yaml
########################################
step8 final_qc:
	@echo "Running Step 8: Final QC + inclusion/exclusion decisions..."
	bash s8_final_qc/run_final_qc.sh --config $(CONFIG)

########################################
# Optional helper targets
########################################

# Remove working directories (be careful!)
# You can replace these hard-coded paths with a YAML parser
# or 'yq' call if you like.
clean_workdirs:
	@echo "Cleaning MRIQC and fMRIPrep work directories (edit paths in Makefile if needed)..."
	rm -rf /scratch/adni/mriqc_work
	rm -rf /scratch/adni/fmriprep_work

status:
	@echo "Pipeline status (implement utils/print_pipeline_status.py if desired)..."
	@echo "This could, for example, count finished subjects per step."
	# python utils/print_pipeline_status.py --config $(CONFIG)

########################################
# Developer helpers
########################################

test:
	pytest

lint:
	@echo "Running Ruff (Python lint) and shellcheck (Bash/Slurm lint)..."
	ruff check .
	@# shellcheck on tracked shell/Slurm scripts; ignore if none
	@if git ls-files '*.sh' '*.slurm' >/dev/null 2>&1; then \
		shellcheck $$(git ls-files '*.sh' '*.slurm'); \
	else \
		echo "No shell or Slurm scripts found for shellcheck"; \
	fi
