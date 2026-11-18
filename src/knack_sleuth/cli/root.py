"""Top-level callback: --version and the stale-skill warning."""

from typing import Annotated

import typer

from knack_sleuth import __version__

from ._common import cli, console
from ._skill_drift import warn_if_installed_skill_is_stale


def version_callback(value: bool):
    """Display version and exit."""
    if value:
        console.print(f"knack-sleuth version {__version__}")
        raise typer.Exit()


@cli.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
):
    """KnackSleuth - Investigate your Knack.app's metadata."""
    if ctx.invoked_subcommand != "install-skill":
        warn_if_installed_skill_is_stale()
