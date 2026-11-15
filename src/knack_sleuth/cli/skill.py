"""install-skill: copy the knack-explorer skill into Claude Code."""

from pathlib import Path
from typing import Annotated

import typer

from ._common import cli, console, exit_on_error
from ._skill_drift import _skill_drift_warning, default_skill_dir, packaged_skill


@cli.command(name="install-skill")
def install_skill(
    target_dir: Annotated[
        Path | None,
        typer.Option(
            "--target",
            "-t",
            help="Target directory (default: ~/.claude/skills/knack-explorer)",
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite existing skill file")
    ] = False,
):
    """
    Install the knack-explorer skill for Claude Code.

    This copies the knack-explorer skill definition to your local
    Claude Code skills directory (~/.claude/skills/knack-explorer/),
    making it available as a Claude Code skill in any project.

    Once installed, Claude Code can use the knack-explorer skill to
    run knack-sleuth commands on your behalf when analyzing Knack apps.

    Examples:

        uvx knack-sleuth install-skill

        knack-sleuth install-skill --force

        knack-sleuth install-skill --target ~/custom/skills/knack-explorer
    """
    target_dir = target_dir or default_skill_dir()
    target_file = target_dir / "SKILL.md"

    with exit_on_error("Could not read skill file from package: "):
        skill_content = packaged_skill()

    if target_file.exists() and not force:
        console.print(f"[yellow]Skill already installed at[/yellow] {target_file}")
        warning = _skill_drift_warning(target_file, skill_content)
        if warning:
            console.print(f"[yellow]{warning}[/yellow]")
        else:
            console.print("[dim]Installed skill matches this release[/dim]")
        console.print("[dim]Use --force to overwrite[/dim]")
        raise typer.Exit(0)

    with exit_on_error("Could not write skill file: "):
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(skill_content)

    console.print()
    console.print(
        f"[green]✓[/green] Installed knack-explorer skill to [bold]{target_file}[/bold]"
    )
    console.print()
    console.print(
        "[dim]Claude Code will now offer the knack-explorer skill in any project.[/dim]"
    )
    console.print(
        "[dim]The skill lets Claude run knack-sleuth commands when analyzing Knack apps.[/dim]"
    )
    console.print()
