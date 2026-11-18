"""CLI tests for the commands that write files or talk to the API.

The API is never contacted: httpx.get is replaced, so these exercise the same
cache-then-API path a real run takes.
"""

import json
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from knack_sleuth import __version__
from knack_sleuth.cli import cli

runner = CliRunner()
SAMPLE = "tests/data/sample_knack_app_meta.json"
SAMPLE_ABS = str(Path(SAMPLE).resolve())  # for tests that chdir


@pytest.fixture
def env(tmp_path):
    """Isolated cache dir, no app ID from the developer's environment."""
    return {
        "KNACK_CACHE_DIR": str(tmp_path / "cache"),
        "KNACK_APP_ID": "",
        "COLUMNS": "200",
    }


@pytest.fixture
def api(monkeypatch, sample_metadata_dict):
    """Serve sample metadata from a fake API.

    Returns (calls, state): the URLs requested, and a dict whose "status" a
    test can change to make the API fail.
    """
    calls: list[str] = []
    state = {"status": 200}

    def fake_get(url, **_):
        calls.append(url)
        request = httpx.Request("GET", url)
        if state["status"] >= 400:
            return httpx.Response(
                state["status"], text="server exploded", request=request
            )
        return httpx.Response(200, json=sample_metadata_dict, request=request)

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls, state


class TestMetadataLoading:
    def test_requires_an_app_id(self, env):
        result = runner.invoke(cli, ["list-objects"], env=env)
        assert result.exit_code == 1
        assert "App ID is required" in result.stderr

    def test_fetches_then_reuses_cache(self, env, api):
        calls, _ = api
        first = runner.invoke(cli, ["list-objects", "--app-id", "abc"], env=env)
        second = runner.invoke(cli, ["list-objects", "--app-id", "abc"], env=env)
        assert first.exit_code == second.exit_code == 0
        assert len(calls) == 1
        assert "Cached metadata to" in first.stderr
        assert "Using cached data" in second.stderr

    def test_corrupt_cache_falls_back_to_api(self, env, api, tmp_path):
        calls, _ = api
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "abc_app_metadata_202601010000.json").write_text("{not json")
        result = runner.invoke(cli, ["list-objects", "--app-id", "abc"], env=env)
        assert result.exit_code == 0
        assert "Failed to read cache" in result.stderr
        assert len(calls) == 1

    def test_http_error_is_one_line(self, env, api):
        _, state = api
        state["status"] = 500
        result = runner.invoke(cli, ["list-objects", "--app-id", "abc"], env=env)
        assert result.exit_code == 1
        assert "HTTP 500: server exploded" in result.stderr
        assert "Traceback" not in result.output

    def test_connection_error(self, env, monkeypatch):
        def refuse(*_, **__):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(httpx, "get", refuse)
        result = runner.invoke(cli, ["list-objects", "--app-id", "abc"], env=env)
        assert result.exit_code == 1
        assert "Failed to connect to Knack API: no route" in result.stderr

    def test_unusable_cache_dir_is_one_line(self, tmp_path):
        not_a_dir = tmp_path / "cache"
        not_a_dir.write_text("")
        env = {"KNACK_CACHE_DIR": str(not_a_dir), "KNACK_APP_ID": ""}
        result = runner.invoke(cli, ["list-objects", "--app-id", "abc"], env=env)
        assert result.exit_code == 1
        assert result.stderr.startswith("Error:")
        assert not isinstance(result.exception, FileExistsError)

    def test_missing_file(self, env):
        result = runner.invoke(cli, ["list-objects", "nope.json"], env=env)
        assert result.exit_code == 1
        assert "File not found" in result.stderr


class TestDownloadMetadata:
    def test_default_filename_and_cache(self, env, api, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["download-metadata", "--app-id", "abc"], env=env)
        assert result.exit_code == 0, result.output
        saved = json.loads((tmp_path / "abc_metadata.json").read_text())
        assert saved["application"]["name"] == "Sample Application"
        assert "Objects: 19 | Scenes: 65" in result.stdout
        # The download refreshes the cache other commands read.
        assert list((tmp_path / "cache").glob("abc_app_metadata_*.json"))

    def test_malformed_metadata_is_one_line(self, env, api, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "abc_app_metadata_209901010000.json").write_text(
            '{"application": null}'
        )
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["download-metadata", "--app-id", "abc"], env=env)
        assert result.exit_code == 1
        assert "Failed to save file" in result.stderr
        assert not isinstance(result.exception, AttributeError)

    def test_unwritable_output(self, env, api, tmp_path):
        out = tmp_path / "missing" / "dir" / "out.json"
        result = runner.invoke(
            cli, ["download-metadata", str(out), "--app-id", "abc"], env=env
        )
        assert result.exit_code == 1
        assert "Failed to save file" in result.stderr


class TestExportDbSchema:
    @pytest.mark.parametrize(
        ("fmt", "suffix", "marker"),
        [
            ("json", "json", '"$schema"'),
            ("dbml", "dbml", "Table "),
            ("yaml", "yaml", "application:"),
            ("mermaid", "mmd", "erDiagram"),
        ],
    )
    def test_formats(self, tmp_path, monkeypatch, fmt, suffix, marker):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            cli, ["export-db-schema", SAMPLE_ABS, "-f", fmt, "-d", "compact"]
        )
        assert result.exit_code == 0, result.output
        out = tmp_path / f"knack_db_schema.{suffix}"
        assert marker in out.read_text()
        assert "Tip:" in result.stdout

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (
                ["-f", "xml"],
                "Invalid format 'xml'. Use one of: json, dbml, yaml, mermaid",
            ),
            (["-d", "huge"], "Invalid detail level 'huge'"),
        ],
    )
    def test_rejects_bad_options(self, args, message):
        result = runner.invoke(
            cli, ["export-db-schema", SAMPLE, *args], env={"COLUMNS": "200"}
        )
        assert result.exit_code == 1
        assert message in result.stderr


class TestExportSchemaSubgraph:
    def test_default_filename_is_a_slug(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            ["export-schema-subgraph", SAMPLE_ABS, "--object", "Object Name 12"],
        )
        assert result.exit_code == 0, result.output
        assert (tmp_path / "knack_subgraph_object-name-12.json").exists()
        assert "Starting object: Object Name 12 (object_12)" in result.stdout

    def test_depth_is_clamped(self, tmp_path):
        out = tmp_path / "s.yaml"
        result = runner.invoke(
            cli,
            [
                "export-schema-subgraph",
                SAMPLE,
                "--object",
                "object_12",
                "--depth",
                "5",
                "-f",
                "yaml",
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert "Depth 5 is not recommended" in result.stderr
        assert "Depth: 2" in result.stdout

    def test_negative_depth(self):
        result = runner.invoke(
            cli,
            [
                "export-schema-subgraph",
                SAMPLE,
                "--object",
                "object_12",
                "--depth",
                "-1",
            ],
        )
        assert result.exit_code == 1
        assert "Depth must be >= 0" in result.stderr

    def test_unknown_object(self, tmp_path):
        result = runner.invoke(
            cli,
            [
                "export-schema-subgraph",
                SAMPLE,
                "--object",
                "nope",
                "-o",
                str(tmp_path / "x"),
            ],
        )
        assert result.exit_code == 1
        assert "Object 'nope' not found" in result.stderr


class TestImpactAnalysis:
    def test_markdown_lists_builder_pages(self):
        result = runner.invoke(
            cli, ["impact-analysis", "object_12", SAMPLE, "--format", "markdown"]
        )
        assert result.exit_code == 0
        assert result.stdout.startswith("# Impact Analysis: Object Name 12")
        assert "## Builder Pages to Review" in result.stdout

    def test_yaml_by_field_name(self):
        result = runner.invoke(
            cli, ["impact-analysis", "Organization ID", SAMPLE, "--format", "yaml"]
        )
        assert result.exit_code == 0
        assert yaml.safe_load(result.stdout)["target"]["type"] == "field"

    def test_ambiguous_field_name(self):
        result = runner.invoke(cli, ["impact-analysis", "Email", SAMPLE])
        assert result.exit_code == 1
        assert "Ambiguous" in result.stdout

    def test_unknown_target_suggests(self):
        result = runner.invoke(cli, ["impact-analysis", "Objekt Name 12", SAMPLE])
        assert result.exit_code == 1
        assert "Could not find object or field" in result.stderr
        assert "Did you mean" in result.stdout

    def test_unknown_key(self):
        result = runner.invoke(cli, ["impact-analysis", "object_999", SAMPLE])
        assert result.exit_code == 1

    def test_bad_format_fails_before_loading(self):
        result = runner.invoke(
            cli, ["impact-analysis", "object_12", "missing.json", "--format", "csv"]
        )
        assert result.exit_code == 1
        assert "Unknown format 'csv'" in result.stderr

    def test_writes_output_file(self, tmp_path):
        out = tmp_path / "impact.json"
        result = runner.invoke(
            cli, ["impact-analysis", "object_12", SAMPLE, "-o", str(out)]
        )
        assert result.exit_code == 0
        assert json.loads(out.read_text())["target"]["key"] == "object_12"
        assert "Analysis saved to" in result.stdout


class TestAppSummary:
    def test_yaml(self):
        result = runner.invoke(cli, ["app-summary", SAMPLE, "--format", "yaml"])
        assert result.exit_code == 0
        assert (
            yaml.safe_load(result.stdout)["application"]["name"] == "Sample Application"
        )

    def test_markdown_to_file(self, tmp_path):
        out = tmp_path / "summary.md"
        result = runner.invoke(
            cli, ["app-summary", SAMPLE, "--format", "markdown", "-o", str(out)]
        )
        assert result.exit_code == 0
        text = out.read_text()
        for heading in (
            "## Domain Model",
            "## Relationship Topology",
            "## Extensibility",
        ):
            assert heading in text

    def test_unwritable_output(self, tmp_path):
        result = runner.invoke(
            cli, ["app-summary", SAMPLE, "-o", str(tmp_path / "no" / "dir" / "s.json")]
        )
        assert result.exit_code == 1
        assert "Failed to save file" in result.stderr


class TestInstallSkill:
    def test_install_then_refuse_then_force(self, tmp_path):
        target = tmp_path / "skill"
        first = runner.invoke(cli, ["install-skill", "--target", str(target)])
        assert first.exit_code == 0
        assert (
            f"knack-sleuth-version: {__version__}" in (target / "SKILL.md").read_text()
        )

        again = runner.invoke(cli, ["install-skill", "--target", str(target)])
        assert again.exit_code == 0
        assert "already installed" in again.stdout
        assert "matches this release" in again.stdout

        (target / "SKILL.md").write_text(
            "<!-- knack-sleuth-version: 0.0.1 -->\nSTALE-COPY"
        )
        stale = runner.invoke(cli, ["install-skill", "--target", str(target)])
        assert "install-skill --force" in stale.stdout

        forced = runner.invoke(
            cli, ["install-skill", "--target", str(target), "--force"]
        )
        assert forced.exit_code == 0
        assert "STALE-COPY" not in (target / "SKILL.md").read_text()


def test_version():
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
