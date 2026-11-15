"""The knack-sleuth command line.

Each command module registers its commands on the shared Typer app when
imported. They are imported in this order because it is the order `--help`
lists them in.
"""

from importlib import import_module

from ._common import cli, load_app_metadata
from ._skill_drift import _skill_drift_warning

_COMMAND_MODULES = (
    "cache",
    "root",
    "objects",
    "orphans",
    "show_rules",
    "metadata",
    "schema",
    "reports",
    "access",
    "skill",
)
for _module in _COMMAND_MODULES:
    import_module(f"{__name__}.{_module}")

__all__ = ["_skill_drift_warning", "cli", "load_app_metadata"]
