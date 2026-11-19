"""Names from Knack metadata must reach the terminal exactly as written.

Rich reads square brackets as markup, so a field called "Amount [usd]" printed
as "Amount" and a name holding "[/x]" crashed the command with a MarkupError.
These tests give every name in the sample app the suffix " [usd] [/x]" and run
each command in its default (rich) output mode.
"""

import copy
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from knack_sleuth.cli import cli

runner = CliRunner()
SAMPLE = Path(__file__).parent / "data" / "sample_knack_app_meta.json"

NEEDLE = "[usd] [/x]"
SUFFIX = f" {NEEDLE}"
# File names cannot hold a "/", so paths carry a different tag-like needle.
PATH_NEEDLE = "[usd] [bold]"
PATH_SUFFIX = f" {PATH_NEEDLE}"

# Real keys in the sample app.
OBJECT = "object_13"  # has inbound and outbound connections, form rules
OBJECT_NAME = "Object Name 13"
FIELD = "field_104"  # object_12 "Identifier", used in views
VIEW = "view_106"  # a form with submit rules
PROFILE_KEY = "profile_10"
PROFILE_NAME = "Object Name 10"


def _load() -> dict:
    return json.loads(SAMPLE.read_text())


def _mutate(data: dict) -> dict:
    """Append the suffix to every application, object, field, scene and view name."""
    app = data["application"]
    app["name"] += SUFFIX
    for obj in app["objects"]:
        obj["name"] += SUFFIX
        for field in obj["fields"]:
            field["name"] += SUFFIX
    for scene in app["scenes"]:
        scene["name"] += SUFFIX
        for view in scene["views"]:
            view["name"] += SUFFIX
    return data


def _write(data: dict, path: Path) -> Path:
    path.write_text(json.dumps(data))
    return path


def _add_orphan_defects(data: dict) -> dict:
    """Give scene_5 an orphaned view, a dangling layout key and a stale rule."""
    scene = next(s for s in data["application"]["scenes"] if s["key"] == "scene_5")
    orphan = copy.deepcopy(scene["views"][0])
    orphan["key"] = "view_9001"
    orphan["name"] = "Orphan" + SUFFIX
    scene["views"].append(orphan)
    scene["groups"].append({"columns": [{"keys": ["view_9002"], "width": 100}]})
    scene["views"][0]["rules"] = {"hide": {"view_keys": ["view_9001", "view_9003"]}}
    return data


@pytest.fixture
def original(tmp_path):
    return _write(_load(), tmp_path / "original.json")


@pytest.fixture
def meta(tmp_path):
    """The sample app with " [usd] [/x]" on every name."""
    return _write(_mutate(_load()), tmp_path / "meta.json")


@pytest.fixture
def meta_orphans(tmp_path):
    """Like meta, plus an orphaned view, a dangling layout key and a stale rule."""
    data = _add_orphan_defects(_mutate(_load()))
    return _write(data, tmp_path / "meta_orphans.json")


@pytest.fixture
def files(meta, original, meta_orphans, tmp_path):
    """(meta, original, meta_orphans, tmp_path), as the case builders take them."""
    return meta, original, meta_orphans, tmp_path


@pytest.fixture
def env(tmp_path):
    return {
        "KNACK_CACHE_DIR": str(tmp_path / f"cache{PATH_SUFFIX}"),
        "KNACK_APP_ID": "",
        "COLUMNS": "400",
    }


def _squash(text: str) -> str:
    """Drop all whitespace, so line wrapping cannot split a match."""
    return "".join(text.split())


def _run(args, env, expect_exit):
    result = runner.invoke(cli, [str(a) for a in args], env=env)
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"{args}: {result.exception!r}\n{result.output}"
    )
    assert result.exit_code == expect_exit, result.output
    return result


def _out(tmp_path: Path, name: str) -> Path:
    """An output path that itself contains brackets."""
    return tmp_path / f"{name}{PATH_SUFFIX}"


# Each case: (id, args as a function of (meta, original, meta_orphans, tmp_path),
# expected exit code, whether the output names something from the metadata).
# The commands that print no metadata name still print a path or the typed
# identifier, so every case asserts the needle except where a comment says so.
CASES = [
    ("list-objects", lambda m, o, mo, t: ["list-objects", m], 0),
    (
        "list-objects-sort-by-rows",
        lambda m, o, mo, t: ["list-objects", m, "--sort-by-rows"],
        0,
    ),
    ("search-object-key", lambda m, o, mo, t: ["search-object", OBJECT, m], 0),
    (
        "search-object-name",
        lambda m, o, mo, t: ["search-object", OBJECT_NAME + SUFFIX, m],
        0,
    ),
    (
        "search-object-no-fields",
        lambda m, o, mo, t: ["search-object", OBJECT, m, "--no-fields"],
        0,
    ),
    (
        "search-object-not-found",
        lambda m, o, mo, t: ["search-object", f"Nope {NEEDLE}", m],
        1,
    ),
    ("search-field-key", lambda m, o, mo, t: ["search-field", FIELD, m], 0),
    (
        "search-field-ambiguous-name",
        lambda m, o, mo, t: ["search-field", "Name" + SUFFIX, m],
        1,
    ),
    (
        "search-field-not-found",
        lambda m, o, mo, t: ["search-field", f"Nope {NEEDLE}", m],
        1,
    ),
    ("show-coupling-key", lambda m, o, mo, t: ["show-coupling", OBJECT, m], 0),
    (
        "show-coupling-name",
        lambda m, o, mo, t: ["show-coupling", OBJECT_NAME + SUFFIX, m],
        0,
    ),
    (
        "show-coupling-not-found",
        lambda m, o, mo, t: ["show-coupling", f"Nope {NEEDLE}", m],
        1,
    ),
    ("find-orphans", lambda m, o, mo, t: ["find-orphans", m], 0),
    (
        "find-orphans-include-system",
        lambda m, o, mo, t: ["find-orphans", m, "--include-system"],
        0,
    ),
    # Orphaned view, dangling layout key and stale rule sections
    ("find-orphans-layout-defects", lambda m, o, mo, t: ["find-orphans", mo], 0),
    (
        "find-orphans-layout-defects-include-system",
        lambda m, o, mo, t: ["find-orphans", mo, "--include-system"],
        0,
    ),
    (
        "show-rules-object",
        lambda m, o, mo, t: ["show-rules", m, "--object", OBJECT],
        0,
    ),
    (
        "show-rules-object-by-name",
        lambda m, o, mo, t: ["show-rules", m, "--object", OBJECT_NAME + SUFFIX],
        0,
    ),
    ("show-rules-view", lambda m, o, mo, t: ["show-rules", m, "--view", VIEW], 0),
    (
        "show-rules-object-not-found",
        lambda m, o, mo, t: ["show-rules", m, "--object", f"Nope {NEEDLE}"],
        1,
    ),
    (
        "show-rules-view-not-found",
        lambda m, o, mo, t: ["show-rules", m, "--view", f"view_{NEEDLE}"],
        1,
    ),
    (
        "impact-analysis-object-output",
        lambda m, o, mo, t: [
            "impact-analysis",
            OBJECT,
            m,
            "-o",
            _out(t, "impact-object"),
        ],
        0,
    ),
    (
        "impact-analysis-field-output",
        lambda m, o, mo, t: [
            "impact-analysis",
            FIELD,
            m,
            "--format",
            "markdown",
            "-o",
            _out(t, "impact-field"),
        ],
        0,
    ),
    (
        "impact-analysis-name-output",
        lambda m, o, mo, t: [
            "impact-analysis",
            OBJECT_NAME + SUFFIX,
            m,
            "--format",
            "yaml",
            "-o",
            _out(t, "impact-name"),
        ],
        0,
    ),
    (
        "impact-analysis-not-found",
        lambda m, o, mo, t: ["impact-analysis", f"Nope {NEEDLE}", m],
        1,
    ),
    (
        "impact-analysis-ambiguous-field",
        lambda m, o, mo, t: ["impact-analysis", "Name" + SUFFIX, m],
        1,
    ),
    (
        "impact-analysis-unknown-format",
        lambda m, o, mo, t: ["impact-analysis", OBJECT, m, "--format", NEEDLE],
        1,
    ),
    (
        "app-summary-output",
        lambda m, o, mo, t: ["app-summary", m, "-o", _out(t, "summary")],
        0,
    ),
    (
        "app-summary-markdown-output",
        lambda m, o, mo, t: [
            "app-summary",
            m,
            "--format",
            "markdown",
            "-o",
            _out(t, "summary-md"),
        ],
        0,
    ),
    (
        "export-db-schema",
        lambda m, o, mo, t: ["export-db-schema", m, "-o", _out(t, "db-schema")],
        0,
    ),
    (
        "export-db-schema-mermaid",
        lambda m, o, mo, t: [
            "export-db-schema",
            m,
            "-f",
            "mermaid",
            "-o",
            _out(t, "db-schema-mmd"),
        ],
        0,
    ),
    (
        "export-db-schema-bad-format",
        lambda m, o, mo, t: ["export-db-schema", m, "-f", NEEDLE],
        1,
    ),
    (
        "export-schema-subgraph-key",
        lambda m, o, mo, t: [
            "export-schema-subgraph",
            m,
            "--object",
            OBJECT,
            "-o",
            _out(t, "subgraph"),
        ],
        0,
    ),
    (
        "export-schema-subgraph-name",
        lambda m, o, mo, t: [
            "export-schema-subgraph",
            m,
            "--object",
            OBJECT_NAME + SUFFIX,
            "--depth",
            "2",
            "-f",
            "yaml",
            "-o",
            _out(t, "subgraph-name"),
        ],
        0,
    ),
    (
        "export-schema-subgraph-not-found",
        lambda m, o, mo, t: [
            "export-schema-subgraph",
            m,
            "--object",
            f"Nope {NEEDLE}",
        ],
        1,
    ),
    (
        "export-schema",
        lambda m, o, mo, t: ["export-schema", _out(t, "internal-schema")],
        0,
    ),
    (
        "role-access-review",
        lambda m, o, mo, t: ["role-access-review", m, "-o", _out(t, "review")],
        0,
    ),
    (
        "role-access-review-summary-only",
        lambda m, o, mo, t: [
            "role-access-review",
            m,
            "--summary-only",
            "-o",
            _out(t, "review-sum"),
        ],
        0,
    ),
    (
        "role-access-summary-role",
        lambda m, o, mo, t: [
            "role-access-summary",
            m,
            "--role",
            PROFILE_NAME + SUFFIX,
            "-o",
            _out(t, "access"),
        ],
        0,
    ),
    (
        "role-access-summary-profile-key",
        lambda m, o, mo, t: [
            "role-access-summary",
            m,
            "--profile-key",
            PROFILE_KEY,
            "-o",
            _out(t, "access-key"),
        ],
        0,
    ),
    (
        "role-access-summary-unknown-role",
        lambda m, o, mo, t: ["role-access-summary", m, "--role", f"Nope {NEEDLE}"],
        1,
    ),
    (
        "role-access-summary-unknown-profile-key",
        lambda m, o, mo, t: [
            "role-access-summary",
            m,
            "--profile-key",
            f"profile_{NEEDLE}",
        ],
        1,
    ),
    # original -> mutated: every name changes, so each section lists a rename
    ("diff-renames", lambda m, o, mo, t: ["diff", o, m], 0),
    # mutated -> original: the same renames, read the other way
    ("diff-renames-reversed", lambda m, o, mo, t: ["diff", m, o], 0),
    # added and removed objects, fields, scenes and views
    ("diff-added-and-removed", lambda m, o, mo, t: ["diff", m, mo], 0),
    ("diff-removed", lambda m, o, mo, t: ["diff", mo, m], 0),
    ("diff-no-changes", lambda m, o, mo, t: ["diff", m, m], 0),
    ("diff-bad-format", lambda m, o, mo, t: ["diff", m, m, "--format", NEEDLE], 1),
    # a path with brackets in an error message
    (
        "missing-metadata-file",
        lambda m, o, mo, t: ["list-objects", _out(t, "missing") / "x.json"],
        1,
    ),
    (
        "install-skill",
        lambda m, o, mo, t: ["install-skill", "--target", _out(t, "skill")],
        0,
    ),
    ("cache-list-empty", lambda m, o, mo, t: ["cache", "list"], 0),
    ("cache-clear-empty", lambda m, o, mo, t: ["cache", "clear"], 0),
]


# Commands whose rich output holds no name from the metadata, only a path:
# the report commands print their content with typer.echo and the saved path
# with Rich, and export-schema, install-skill and cache never read the app.
PATH_ONLY = {
    "impact-analysis-object-output",
    "impact-analysis-field-output",
    "impact-analysis-name-output",
    "app-summary-output",
    "app-summary-markdown-output",
    "export-schema",
    "missing-metadata-file",
    "install-skill",
    "cache-list-empty",
    "cache-clear-empty",
}


@pytest.mark.parametrize(
    ("case_id", "build", "expect_exit"),
    [pytest.param(i, b, e, id=i) for i, b, e in CASES],
)
def test_command_prints_names_verbatim(case_id, build, expect_exit, files, env):
    args = build(*files)
    result = _run(args, env, expect_exit)
    if case_id in PATH_ONLY:
        assert PATH_NEEDLE in result.output
    else:
        assert NEEDLE in result.output
    if any(PATH_NEEDLE in str(a) for a in args):
        assert PATH_NEEDLE in result.output


def test_find_orphans_layout_defects_are_listed(meta_orphans, env):
    """The synthetic defects really show up, so the cases above exercise them."""
    out = _run(["find-orphans", meta_orphans], env, 0).output
    assert "Orphaned Views" in out
    assert "Dangling Layout Keys" in out
    assert "Stale View Rule References" in out
    assert f"Orphan{SUFFIX}" in out


def test_diff_lists_every_kind_of_change(original, meta, meta_orphans, env):
    out = _run(["diff", original, meta], env, 0).output
    for section in (
        "Objects Renamed",
        "Fields Changed",
        "Scenes Renamed",
        "Views Changed",
        "Application renamed",
    ):
        assert section in out
    out = _run(["diff", meta, meta_orphans], env, 0).output
    assert "Views Added" in out


def test_not_found_names_the_identifier_without_a_traceback(meta, env):
    name = f"Nope {NEEDLE}"
    result = _run(["search-object", name, meta], env, 1)
    assert f"Object '{name}' not found in application" in result.output
    assert "Traceback" not in result.output


def test_suggestions_keep_their_brackets(meta, env):
    result = _run(["search-object", OBJECT_NAME + " [usd]", meta], env, 1)
    assert f"{OBJECT_NAME}{SUFFIX}" in result.output


def test_field_names_with_brackets_are_listed(tmp_path, env):
    """Two sibling fields that differ only inside brackets both print in full."""
    data = _load()
    obj = next(o for o in data["application"]["objects"] if o["key"] == "object_11")
    names = {"field_102": "Amount [usd]", "field_103": "Amount [eur]"}  # orphans
    for field in obj["fields"]:
        field["name"] = names.get(field["key"], field["name"])
    path = _write(data, tmp_path / "amounts.json")

    out = _run(["find-orphans", path], env, 0).output
    assert "Amount [usd]" in out
    assert "Amount [eur]" in out

    out = _run(["search-field", "Amount [eur]", path], env, 0).output
    assert "Amount [eur]" in out
    assert "Amount [usd]" not in out


def test_builder_links_survive_brackets_in_the_slug(tmp_path, env):
    data = _load()
    data["application"]["slug"] = "my[app]"
    path = _write(data, tmp_path / "slug.json")
    out = _run(["search-object", OBJECT, path], env, 0).output
    assert "my[app]" in out


def test_download_metadata_prints_names_verbatim(tmp_path, env, monkeypatch):
    data = _mutate(_load())

    def fake_get(url, **_):
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    target = _out(tmp_path, "downloaded")
    result = _run(["download-metadata", target, "--app-id", "abc123"], env, 0)
    assert f"App: Sample Application{SUFFIX}" in result.output
    # A long path wraps wherever the terminal width puts it.
    assert _squash(str(target)) in _squash(result.output)

    # the cache file is now listed, under a table titled with the bracketed dir
    result = _run(["cache", "list"], env, 0)
    # The table title wraps and is centred, so collapse the padding.
    assert PATH_NEEDLE in " ".join(result.output.split())
    assert "abc123_app_metadata_" in result.output


def test_stale_skill_warning_survives_brackets_in_the_version(meta, env):
    skill = Path.home() / ".claude" / "skills" / "knack-explorer" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("<!-- knack-sleuth-version: 0.0.[/x] -->\nold skill\n")
    result = _run(["list-objects", meta], env, 0)
    assert "0.0.[/x]" in result.output
