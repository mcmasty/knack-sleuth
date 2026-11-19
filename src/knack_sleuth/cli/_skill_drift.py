"""Detect an installed knack-explorer skill that is older than this package."""

import re
from importlib import resources
from pathlib import Path

from rich.markup import escape

from knack_sleuth import __version__

from ._common import err_console

SKILL_VERSION_PATTERN = re.compile(
    r"^<!-- knack-sleuth-version: ([^ ]+) -->$",
    re.MULTILINE,
)


def default_skill_dir() -> Path:
    return Path.home() / ".claude" / "skills" / "knack-explorer"


def packaged_skill() -> str:
    return resources.files("knack_sleuth").joinpath("data/SKILL.md").read_text()


def _release_tuple(version: str) -> tuple[int, ...] | None:
    """Parse a simple numeric release for drift comparisons."""
    parts = version.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _without_skill_version_stamp(content: str) -> str:
    """Normalize content so the current pre-stamp skill is not called stale.

    The stamp sits between the frontmatter and the body, so dropping just the
    comment leaves the blank line that followed it; collapse that gap too, and
    normalize both sides of a comparison with this so they line up.
    """
    stripped = SKILL_VERSION_PATTERN.sub("", content)
    return re.sub(r"\n{3,}", "\n\n", stripped).lstrip("\n")


def _skill_drift_warning(
    target_file: Path,
    packaged_content: str,
    running_version: str = __version__,
) -> str | None:
    """Return an actionable warning when an installed skill is stale."""
    if not target_file.is_file():
        return None

    try:
        installed_content = target_file.read_text()
    except OSError:
        return None

    match = SKILL_VERSION_PATTERN.search(installed_content)
    if not match:
        if _without_skill_version_stamp(
            installed_content
        ) == _without_skill_version_stamp(packaged_content):
            return None
        return (
            "Installed knack-explorer skill predates version tracking and differs "
            "from this release; run 'knack-sleuth install-skill --force' to update it."
        )

    installed_version = match.group(1)
    installed_release = _release_tuple(installed_version)
    running_release = _release_tuple(running_version)
    # Same version, or the installed skill is newer than this package.
    if installed_version == running_version or (
        installed_release and running_release and installed_release >= running_release
    ):
        return None
    return (
        f"Installed knack-explorer skill is from {installed_version}; running "
        f"knack-sleuth is {running_version}. Run 'knack-sleuth install-skill "
        "--force' to update it."
    )


def warn_if_installed_skill_is_stale() -> None:
    """Warn on stderr without disrupting command output or execution."""
    try:
        packaged_content = packaged_skill()
    except (OSError, TypeError):
        return

    warning = _skill_drift_warning(default_skill_dir() / "SKILL.md", packaged_content)
    if warning:
        err_console.print(f"[yellow]Warning:[/yellow] {escape(warning)}")
