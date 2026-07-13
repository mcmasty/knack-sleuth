"""Smoke tests for CLI commands via Typer's test runner."""

import copy
import json
import re

from typer.testing import CliRunner

from knack_sleuth.cli import cli

runner = CliRunner()

# Wide terminal so Rich doesn't truncate table columns in assertions
WIDE = {"COLUMNS": "200"}


class TestListObjects:
    def test_shows_instability_values(self, sample_metadata_file):
        result = runner.invoke(cli, ["list-objects", str(sample_metadata_file)], env=WIDE)
        assert result.exit_code == 0
        # Instability renders as 0.00-1.00 for connected objects
        assert re.search(r"\b[01]\.\d{2}\b", result.output)


class TestSearchField:
    def test_by_key(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["search-field", "field_88", str(sample_metadata_file)], env=WIDE
        )
        assert result.exit_code == 0
        assert "Field Search Results" in result.output

    def test_ambiguous_name_lists_candidates(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["search-field", "Name", str(sample_metadata_file)], env=WIDE
        )
        assert result.exit_code == 1
        assert "Ambiguous" in result.output
        assert "field_" in result.output

    def test_unknown_field_errors(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["search-field", "Namee", str(sample_metadata_file)], env=WIDE
        )
        assert result.exit_code == 1
        assert "not found" in result.output


class TestFindOrphans:
    def test_runs_and_reports_totals(self, sample_metadata_file):
        result = runner.invoke(cli, ["find-orphans", str(sample_metadata_file)], env=WIDE)
        assert result.exit_code == 0
        assert "orphaned fields" in result.output
        assert "orphaned objects" in result.output


class TestDidYouMean:
    def test_search_object_typo_suggests(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["search-object", "Ref Data Categry", str(sample_metadata_file)], env=WIDE
        )
        assert result.exit_code == 1
        assert "Did you mean" in result.output
        assert "Ref Data Category" in result.output

    def test_show_coupling_typo_suggests(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["show-coupling", "Ref Data Categry", str(sample_metadata_file)], env=WIDE
        )
        assert result.exit_code == 1
        assert "Did you mean" in result.output


class TestShowCoupling:
    def test_shows_instability_in_header(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["show-coupling", "object_12", str(sample_metadata_file)], env=WIDE
        )
        assert result.exit_code == 0
        assert "I:" in result.output


class TestCacheCommands:
    def _env(self, tmp_path):
        return {**WIDE, "KNACK_CACHE_DIR": str(tmp_path)}

    def test_cache_dir_prints_path(self, tmp_path):
        result = runner.invoke(cli, ["cache", "dir"], env=self._env(tmp_path))
        assert result.exit_code == 0
        assert str(tmp_path) in result.output

    def test_cache_list_empty(self, tmp_path):
        result = runner.invoke(cli, ["cache", "list"], env=self._env(tmp_path))
        assert result.exit_code == 0
        assert "No cache files" in result.output

    def test_cache_list_and_clear(self, tmp_path, sample_metadata_dict):
        (tmp_path / "app1_app_metadata_202601010000.json").write_text(
            json.dumps(sample_metadata_dict)
        )
        (tmp_path / "app2_app_metadata_202601010000.json").write_text("{}")

        result = runner.invoke(cli, ["cache", "list"], env=self._env(tmp_path))
        assert result.exit_code == 0
        assert "app1" in result.output
        assert "app2" in result.output

        # Clear only app1
        result = runner.invoke(
            cli, ["cache", "clear", "--app-id", "app1"], env=self._env(tmp_path)
        )
        assert result.exit_code == 0
        assert "Deleted 1 cache files" in result.output
        assert not list(tmp_path.glob("app1_*.json"))
        assert list(tmp_path.glob("app2_*.json"))

        # Clear the rest
        result = runner.invoke(cli, ["cache", "clear"], env=self._env(tmp_path))
        assert result.exit_code == 0
        assert not list(tmp_path.glob("*.json"))


class TestDiff:
    @staticmethod
    def _write(tmp_path, name, data):
        path = tmp_path / name
        path.write_text(json.dumps(data))
        return path

    def test_identical_files_no_changes_exit_zero(self, sample_metadata_dict, tmp_path):
        old = self._write(tmp_path, "old.json", sample_metadata_dict)
        new = self._write(tmp_path, "new.json", sample_metadata_dict)
        result = runner.invoke(
            cli, ["diff", str(old), str(new), "--exit-code"], env=WIDE
        )
        assert result.exit_code == 0
        assert "No structural changes" in result.output

    def test_changed_files_exit_code(self, sample_metadata_dict, tmp_path):
        mutated = copy.deepcopy(sample_metadata_dict)
        mutated["application"]["objects"][0]["name"] = "Renamed For Diff Test"

        old = self._write(tmp_path, "old.json", sample_metadata_dict)
        new = self._write(tmp_path, "new.json", mutated)

        # Without --exit-code, differences still exit 0
        result = runner.invoke(cli, ["diff", str(old), str(new)], env=WIDE)
        assert result.exit_code == 0
        assert "Renamed For Diff Test" in result.output

        # With --exit-code, differences exit 1 (git-diff style)
        result = runner.invoke(
            cli, ["diff", str(old), str(new), "--exit-code"], env=WIDE
        )
        assert result.exit_code == 1

    def test_json_format_is_parseable(self, sample_metadata_dict, tmp_path):
        mutated = copy.deepcopy(sample_metadata_dict)
        mutated["application"]["objects"][0]["name"] = "Renamed For Diff Test"

        old = self._write(tmp_path, "old.json", sample_metadata_dict)
        new = self._write(tmp_path, "new.json", mutated)

        result = runner.invoke(
            cli, ["diff", str(old), str(new), "--format", "json"], env=WIDE
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["has_changes"] is True
        assert len(parsed["objects"]["renamed"]) == 1

    def test_output_requires_structured_format(self, sample_metadata_dict, tmp_path):
        old = self._write(tmp_path, "old.json", sample_metadata_dict)
        new = self._write(tmp_path, "new.json", sample_metadata_dict)
        result = runner.invoke(
            cli, ["diff", str(old), str(new), "-o", str(tmp_path / "out.txt")], env=WIDE
        )
        assert result.exit_code == 1
        assert "--format json or markdown" in result.output
