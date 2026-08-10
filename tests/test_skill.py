"""Guard tests for the knack-explorer Claude Code skill."""

from importlib import resources
import json
from pathlib import Path

from typer.testing import CliRunner

from knack_sleuth import __version__
from knack_sleuth.cli import _skill_drift_warning, cli


def test_packaged_skill_matches_repo_copy():
    """The packaged skill (what install-skill installs) and the repo-local
    project skill must stay byte-identical — they are maintained by hand in
    two places."""
    packaged = resources.files("knack_sleuth").joinpath("data/SKILL.md").read_text()
    repo_copy = Path(".claude/skills/knack-explorer/SKILL.md").read_text()
    assert packaged == repo_copy


def test_packaged_skill_version_matches_package_version():
    packaged = resources.files("knack_sleuth").joinpath("data/SKILL.md").read_text()
    assert f"<!-- knack-sleuth-version: {__version__} -->" in packaged


def test_stale_installed_skill_gets_actionable_warning(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("<!-- knack-sleuth-version: 0.4.0 -->\nold guidance\n")
    packaged = f"<!-- knack-sleuth-version: {__version__} -->\ncurrent guidance\n"

    warning = _skill_drift_warning(target, packaged)

    assert warning is not None
    assert "0.4.0" in warning
    assert __version__ in warning
    assert "install-skill --force" in warning


def test_current_installed_skill_has_no_warning(tmp_path):
    target = tmp_path / "SKILL.md"
    content = f"<!-- knack-sleuth-version: {__version__} -->\ncurrent guidance\n"
    target.write_text(content)

    assert _skill_drift_warning(target, content) is None


def test_matching_legacy_skill_without_stamp_has_no_false_warning(tmp_path):
    """Use the real packaged skill, not a synthetic one: the stamp sits mid-file
    after the frontmatter, so removing it leaves a blank-line gap that a
    stamp-on-line-1 fixture would never catch. Stripping the stamp block from
    the packaged file reproduces the v0.5.0 copy byte for byte."""
    packaged = resources.files("knack_sleuth").joinpath("data/SKILL.md").read_text()
    legacy = packaged.replace(f"<!-- knack-sleuth-version: {__version__} -->\n\n", "")
    assert legacy != packaged, "stamp block not found in packaged skill"

    target = tmp_path / "SKILL.md"
    target.write_text(legacy)

    assert _skill_drift_warning(target, packaged) is None


def test_changed_legacy_skill_without_stamp_gets_warning(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old guidance\n")
    packaged = f"<!-- knack-sleuth-version: {__version__} -->\ncurrent guidance\n"

    warning = _skill_drift_warning(target, packaged)

    assert warning is not None
    assert "predates version tracking" in warning
    assert "install-skill --force" in warning


def test_cli_warns_on_stderr_without_polluting_json_stdout(
    tmp_path,
    monkeypatch,
    sample_metadata_file,
):
    target = tmp_path / ".claude" / "skills" / "knack-explorer" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("<!-- knack-sleuth-version: 0.4.0 -->\nold guidance\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = CliRunner().invoke(
        cli,
        ["list-objects", str(sample_metadata_file), "--format", "json"],
    )

    assert result.exit_code == 0
    assert "install-skill --force" in result.stderr
    assert json.loads(result.stdout)["application"] == "Sample Application"


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
