"""Smoke tests for CLI commands via Typer's test runner."""

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
