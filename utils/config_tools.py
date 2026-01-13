"""Small helper for reading config/config_adni.yaml from Python and shell.

Usage from Python:
    from utils.config_tools import load_config, get_value
    cfg = load_config()                      # uses default path or $ADNI_CONFIG
    bids_dir = get_value(cfg, "fmriprep.bids_dir")

Usage from shell:
    python -m utils.config_tools fmriprep.bids_dir
    python -m utils.config_tools paths.raw_dicom_dir --config config/custom.yaml

If the requested key does not exist, the CLI prints an error to stderr and
exits with status 1.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict

import yaml


# Default to config/config_adni.yaml relative to repo root
_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "config_adni.yaml"
)


def load_config(path: str | os.PathLike | None = None) -> Dict[str, Any]:
    """Load YAML config and return as a dict.

    Resolution order for the path:
    1. Explicit ``path`` argument if provided.
    2. ``$ADNI_CONFIG`` environment variable if set.
    3. ``config/config_adni.yaml`` relative to repo root.
    """

    if path is None:
        env_path = os.environ.get("ADNI_CONFIG")
        path_obj = Path(env_path) if env_path else _DEFAULT_CONFIG_PATH
    else:
        path_obj = Path(path)

    if not path_obj.exists():
        raise FileNotFoundError(f"Config file not found: {path_obj}")

    with path_obj.open("r") as f:
        cfg = yaml.safe_load(f) or {}

    if not isinstance(cfg, dict):
        raise ValueError(f"Config at {path_obj} is not a mapping at top level")

    return cfg


def get_value(cfg: Dict[str, Any], key_path: str) -> Any:
    """Get a nested value from ``cfg`` using a dotted key path.

    Example: ``get_value(cfg, "paths.fmriprep_output_dir")``.
    """

    parts = [p for p in key_path.split(".") if p]
    cur: Any = cfg
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"Key path not found in config: {key_path}")
        cur = cur[part]
    return cur


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Print a value from config/config_adni.yaml given a dotted key path, "
            "for use in shell scripts."
        )
    )
    parser.add_argument(
        "key",
        help="Dotted key path (e.g., 'paths.raw_dicom_dir' or 'fmriprep.bids_dir')",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help=(
            "Optional path to a YAML config file. If omitted, uses $ADNI_CONFIG "
            "or config/config_adni.yaml."
        ),
    )
    return parser.parse_args(argv)


def _main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        cfg = load_config(args.config_path)
    except Exception as e:  # FileNotFoundError, ValueError, etc.
        print(f"[config_tools] Failed to load config: {e}", file=os.sys.stderr)
        return 1

    try:
        value = get_value(cfg, args.key)
    except KeyError as e:
        print(f"[config_tools] {e}", file=os.sys.stderr)
        return 1

    # For dicts/lists, print JSON; for scalars, print raw
    if isinstance(value, (dict, list)):
        print(json.dumps(value))
    else:
        print(value)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
