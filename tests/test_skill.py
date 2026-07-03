"""Guard tests for the knack-explorer Claude Code skill."""

from importlib import resources
from pathlib import Path


def test_packaged_skill_matches_repo_copy():
    """The packaged skill (what install-skill installs) and the repo-local
    project skill must stay byte-identical — they are maintained by hand in
    two places."""
    packaged = resources.files("knack_sleuth").joinpath("data/SKILL.md").read_text()
    repo_copy = Path(".claude/skills/knack-explorer/SKILL.md").read_text()
    assert packaged == repo_copy


def test_skill_documents_every_user_facing_command():
    """Every CLI command should be listed in the skill so agents know it exists.

    install-skill is exempt — the skill has no reason to install itself.
    """
    from knack_sleuth.cli import cli

    skill_text = resources.files("knack_sleuth").joinpath("data/SKILL.md").read_text()

    command_names = {
        command.name for command in cli.registered_commands if command.name
    }
    command_names.discard("install-skill")

    missing = {name for name in command_names if f"`{name}`" not in skill_text}
    assert not missing, f"Commands missing from SKILL.md: {sorted(missing)}"
