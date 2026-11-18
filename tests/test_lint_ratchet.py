"""scripts/lint_ratchet.py: decreases pass, increases fail, the release tightens."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "lint_ratchet.py"
_spec = importlib.util.spec_from_file_location("lint_ratchet", SCRIPT)
assert _spec is not None
assert _spec.loader is not None
ratchet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ratchet)

CONFIG = {"ignore": [], "per-file-ignores": {}, "max-complexity": 10}


def state(**counts: int) -> dict:
    """A ratchet snapshot with one file and the given rule counts."""
    suppressed = {"src/a.py": {k: v for k, v in counts.items() if v}}
    return {"total": sum(counts.values()), "suppressed": suppressed, "config": CONFIG}


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Run main() against a baseline and a current state; return (rc, baseline)."""
    baseline_file = tmp_path / "lint-baseline.json"
    monkeypatch.setattr(ratchet, "BASELINE", baseline_file)

    def _run(baseline: dict, now: dict, *flags: str) -> tuple[int, dict]:
        baseline_file.write_text(json.dumps(baseline))
        monkeypatch.setattr(ratchet, "current", lambda: now)
        monkeypatch.setattr(sys, "argv", ["lint_ratchet.py", *flags])
        rc = ratchet.main()
        return rc, json.loads(baseline_file.read_text())

    return _run


def test_unchanged_passes_in_every_mode(run):
    for flags in ([], ["--strict"], ["--tighten"]):
        assert run(state(C901=2), state(C901=2), *flags)[0] == 0


def test_decrease_passes_without_touching_baseline(run):
    rc, baseline = run(state(C901=2), state(C901=1))
    assert rc == 0
    assert baseline == state(C901=2)


def test_decrease_fails_strict(run):
    rc, baseline = run(state(C901=2), state(C901=1), "--strict")
    assert rc == 1
    assert baseline == state(C901=2)


def test_tighten_lowers_baseline(run):
    rc, baseline = run(state(C901=2, S110=1), state(C901=1), "--tighten")
    assert rc == 0
    assert baseline == state(C901=1)


@pytest.mark.parametrize("flags", [[], ["--strict"], ["--tighten"]])
def test_increase_fails_and_keeps_baseline(run, flags):
    rc, baseline = run(state(C901=1), state(C901=2), *flags)
    assert rc == 1
    assert baseline == state(C901=1)


def test_tighten_refuses_mixed_change(run):
    """One rule down and another up: nothing is written."""
    rc, baseline = run(state(C901=2), state(C901=1, S110=1), "--tighten")
    assert rc == 1
    assert baseline == state(C901=2)


def test_config_change_fails(run):
    now = state(C901=1) | {"config": CONFIG | {"max-complexity": 20}}
    assert run(state(C901=1), now, "--tighten")[0] == 1


def test_update_accepts_increase(run):
    rc, baseline = run(state(C901=1), state(C901=2), "--update")
    assert rc == 0
    assert baseline == state(C901=2)


def test_modes_are_exclusive(run):
    with pytest.raises(SystemExit):
        run(state(), state(), "--strict", "--tighten")
