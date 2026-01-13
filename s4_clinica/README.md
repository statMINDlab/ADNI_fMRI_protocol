# Step 4.) Run Clinica (DICOM→NIfTI and BIDS-ify)

**4.1.)** We will use [Clinica](https://aramislab.paris.inria.fr/clinica/docs/public/dev/Converters/ADNI2BIDS/) to convert the DICOMs to NIFTI format and to organize the data following the BIDS format (Brain Imaging Data Structure). Below is the homepage of the Clinica software’s website.  
<div>
<img src="screenshots/ADNI_step4.1.png" width="800"/>
</div>

**4.2.)** Clinica requires users to download and install the [dcm2nix](https://github.com/rordenlab/dcm2niix) software. You can instill it via conda.

```conda install –c conda-forge dcm2niix```


**4.3.)** Use conda to create and activate a virtual environment. 

```module load conda; conda create –n clinica_env; conda activate clinica_env;```


**4.4)** Use pip to install the Clinica Python package. 

```pip install clinica```


**4.5.)** Use the subject list you created in Step 3.10 to create subject-specific Clinica scripts (faster than running on everyone at once). We run Clinica on individual subjects (in parallel) because this significantly speeds up the process. The helper script for creating per-subject Slurm jobs is `create_slurm_script_per_sub.sh`.

`create_slurm_script_per_sub.sh` resolves all project- and cluster-specific paths from `config/config_adni.yaml` via `utils.config_tools` (for example, Clinica input DICOM locations, BIDS output, and log directories). Edit the YAML, not the script, when retargeting to a new environment.

**4.6.)** Use the script `adni_submit_slurm.sh` to submit all subjects to Slurm to run in parallel. This script can be adjusted to run on different HPC systems. If you are not running on an HPC (for example, a personal workstation—_not_ recommended at full ADNI scale), you can skip this script and instead run the per-subject Clinica scripts directly, as many in parallel as your machine allows.

**4.7.)** Once all Clinica jobs finish running, merge the individual BIDS folders into a single BIDS tree using `merge_individual_clinica.sh`. This script also resolves its input and output paths via `config/config_adni.yaml`.

Now, continue on to Step 5 (`s5_post_clinica_qc/README.md`).
