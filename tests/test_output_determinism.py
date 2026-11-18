"""Output must not depend on PYTHONHASHSEED.

str hashing is randomized per process, so iterating a set of keys into a
list gives a different order on each run. These tests run the CLI in fresh
interpreters (multiprocessing "spawn") under two hash seeds and require
byte-identical output.
"""

import multiprocessing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from knack_sleuth.cli import cli
from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.sleuth import KnackSleuth

SAMPLE = Path(__file__).parent / "data" / "sample_knack_app_meta.json"
SEEDS = ("1", "2")


def _invoke_cli(args: list[str]) -> str:
    """Run in the spawned child; returns stdout."""
    result = CliRunner().invoke(cli, args)
    if result.exit_code != 0:
        raise RuntimeError(f"exit {result.exit_code}: {result.output}")
    return result.stdout


def _run_cli_with_seed(
    args: list[str], seed: str, monkeypatch: pytest.MonkeyPatch
) -> str:
    # A spawned child is a new interpreter, which reads PYTHONHASHSEED at
    # startup from the environment it inherits.
    monkeypatch.setenv("PYTHONHASHSEED", seed)
    with multiprocessing.get_context("spawn").Pool(1) as pool:
        return pool.apply(_invoke_cli, (args,))


@pytest.mark.parametrize(
    "args",
    [
        ["impact-analysis", "field_116", str(SAMPLE)],
        ["impact-analysis", "field_116", str(SAMPLE), "--format", "markdown"],
        ["impact-analysis", "object_10", str(SAMPLE)],
        ["app-summary", str(SAMPLE)],
    ],
    ids=["field-json", "field-markdown", "object-json", "app-summary"],
)
def test_output_identical_across_hash_seeds(args, monkeypatch):
    outputs = [_run_cli_with_seed(args, seed, monkeypatch) for seed in SEEDS]
    assert outputs[0], "CLI produced no output"
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("target", ["field_116", "object_10"])
def test_affected_scenes_match_direct_scene_order(sample_metadata_dict, target):
    """Both scene lists come from one ordered source, so they must agree."""
    sleuth = KnackSleuth(KnackAppMetadata(**sample_metadata_dict))
    analysis = sleuth.generate_impact_analysis(target)

    affected = analysis["cascade_impacts"]["affected_scenes"]
    direct = [s["scene_key"] for s in analysis["direct_impacts"]["scenes"]]
    assert len(affected) > 1, "need several scenes for the order to matter"
    assert affected == direct
    assert len(set(affected)) == len(affected)
