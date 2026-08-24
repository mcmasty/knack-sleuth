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


class TestJsonOutput:
    def test_list_objects_json(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["list-objects", str(sample_metadata_file), "--format", "json"], env=WIDE
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"application", "objects", "totals"}
        assert parsed["objects"]

    def test_search_object_json(self, sample_metadata_file):
        result = runner.invoke(
            cli,
            ["search-object", "object_12", str(sample_metadata_file), "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {
            "object",
            "object_usages",
            "field_usages",
            "scenes_to_review",
        }

    def test_search_field_json(self, sample_metadata_file):
        result = runner.invoke(
            cli,
            ["search-field", "field_105", str(sample_metadata_file), "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"field", "usages", "scenes_to_review"}

    def test_show_coupling_json(self, sample_metadata_file):
        result = runner.invoke(
            cli,
            ["show-coupling", "object_12", str(sample_metadata_file), "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed["ca"], int)
        assert isinstance(parsed["ce"], int)
        assert isinstance(parsed["inbound"], list)
        assert isinstance(parsed["outbound"], list)
        assert parsed["instability"] is None or isinstance(parsed["instability"], float)

    def test_find_orphans_json(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["find-orphans", str(sample_metadata_file), "--format", "json"], env=WIDE
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed["orphaned_fields"], list)
        assert isinstance(parsed["totals"], dict)
        assert parsed["totals"]["orphaned_fields"] == len(parsed["orphaned_fields"])
        assert (
            parsed["totals"]["orphaned_fields_including_hidden"]
            == parsed["totals"]["orphaned_fields"]
            + parsed["totals"]["hidden_system_fields"]
        )

    def test_invalid_format_exits_1(self, sample_metadata_file):
        result = runner.invoke(
            cli, ["find-orphans", str(sample_metadata_file), "--format", "xml"], env=WIDE
        )
        assert result.exit_code == 1
        assert "Invalid format" in result.output


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
        parsed = json.loads(result.stdout)
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


class TestFindOrphansViews:
    """A page-layout orphan is a view Knack never draws."""

    @staticmethod
    def _app_json(tmp_path):
        app = {
            "application": {
                "id": "app_1",
                "name": "Layout Debt",
                "slug": "layout-debt",
                "account": {"slug": "acme"},
                "home_scene": {"key": "scene_1", "slug": "home"},
                "objects": [],
                "scenes": [
                    {
                        "key": "scene_1",
                        "name": "Home",
                        "slug": "home",
                        "groups": [{"columns": [{"keys": ["view_1", "view_8"]}]}],
                        "rules": [{"action": "hide_views", "view_keys": ["view_2"]}],
                        "views": [
                            {"key": "view_1", "name": "Live", "type": "table"},
                            {"key": "view_2", "name": "Leftover", "type": "form"},
                        ],
                    }
                ],
            }
        }
        path = tmp_path / "app.json"
        path.write_text(json.dumps(app))
        return path

    def test_json_reports_all_three_layout_defects(self, tmp_path):
        result = runner.invoke(
            cli, ["find-orphans", str(self._app_json(tmp_path)), "--format", "json"], env=WIDE
        )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert [v["view_key"] for v in parsed["orphaned_views"]] == ["view_2"]
        assert [d["view_key"] for d in parsed["dangling_layout_keys"]] == ["view_8"]
        assert [r["view_key"] for r in parsed["stale_view_rule_references"]] == ["view_2"]
        assert parsed["totals"]["orphaned_views"] == 1

    def test_json_orphan_carries_a_builder_deep_link(self, tmp_path):
        """The view is not on the canvas, so a scene link has nothing to click
        -- the view-level URL is the only way to reach it."""
        result = runner.invoke(
            cli, ["find-orphans", str(self._app_json(tmp_path)), "--format", "json"], env=WIDE
        )

        assert json.loads(result.output)["orphaned_views"][0]["builder_url"] == (
            "https://builder.knack.com/acme/layout-debt/pages/scene_1/views/view_2/form"
        )

    def test_rich_output_names_the_orphaned_view(self, tmp_path):
        result = runner.invoke(cli, ["find-orphans", str(self._app_json(tmp_path))], env=WIDE)

        assert result.exit_code == 0
        assert "Orphaned Views" in result.output
        assert "view_2" in result.output
