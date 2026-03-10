# Contributing and development guide

This repository is primarily maintained by the authors of the ADNI rs-fMRI protocol, but contributions and local adaptations are welcome. This document describes how to run tests, lint checks, and make changes in a way that keeps the pipeline reproducible.

## Development environment

1. Clone the repository.
2. Create a Python environment from `env/env_adni.yml` (or your own equivalent) and activate it.
3. Install the post-Clinica analysis dependencies if you plan to touch that code:

   ```bash
   pip install -r s5_post_clinica_qc/analysis/requirements.txt
   ```

4. Ensure `pytest`, `ruff`, and `shellcheck` are available (CI will run all three).

## Running tests

From the repository root:

```bash
make test
```

This runs the pytest suite under `utils/tests/`, including integration-style tests for the config helper and the MRIQC/fMRIPrep/Clinica shell scripts. These tests stub out heavy dependencies like `module` and `apptainer` so they can run on a typical development machine.

You can also run individual tests directly, for example:

```bash
pytest utils/tests/test_config_tools.py
pytest utils/tests/test_mriqc_scripts.py::test_adni_mriqc_errors_on_missing_required_config_value
```

## Linting and style

We use [Ruff](https://docs.astral.sh/ruff/) for Python linting and [shellcheck](https://www.shellcheck.net/) for shell/Slurm scripts. Configuration for Ruff lives in `ruff.toml`.

To run both linters locally:

```bash
make lint
```

This will:

- Run `ruff check .` over the Python codebase.
- Run `shellcheck` on all tracked `*.sh` and `*.slurm` files.

CI will run the same checks on each push and pull request.

## GitHub Actions CI

The workflow at `.github/workflows/tests.yml` defines two jobs:

- `tests` – installs dependencies and runs `pytest`.
- `lint` – installs Ruff and shellcheck, then runs the linters.

Please try to keep the tests and linters passing before opening a pull request.

## Making changes

- Prefer updating `config/config_adni.yaml` and using `utils.config_tools` to access paths and settings, rather than hardcoding cluster- or user-specific paths in scripts.
- When modifying shell or Slurm scripts, favor small, composable helpers and keep `--config` and dry-run options working.
- When you add new functionality:
  - Add or update tests under `utils/tests/`.
  - Update the relevant step-specific `README.md` files so that usage instructions stay in sync with the code.

## Reporting issues

If you encounter problems or corner cases (especially around specific clusters, container runtimes, or ADNI data quirks), please open an issue with:

- A brief description of the problem.
- The step and script involved.
- Relevant log excerpts (e.g., Slurm logs, error messages).

This helps us improve the robustness and portability of the protocol.