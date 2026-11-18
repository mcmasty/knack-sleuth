"""Ratchet on lint suppressions: the count may only go down.

Every finding hidden by an inline ``# noqa`` is technical debt that stays
visible at the function it belongs to. This script counts them per file and
rule (by re-running ruff with ``--ignore-noqa``) and compares the counts with
``lint-baseline.json``. It also records the config-level escape hatches
(``ignore``, ``per-file-ignores``, ``max-complexity``) so debt cannot move from
a noqa comment into pyproject.toml unnoticed.

    uv run python scripts/lint_ratchet.py            # check (CI, pre-commit)
    uv run python scripts/lint_ratchet.py --update   # rewrite the baseline

The check fails when a count rises, a new file/rule pair appears, or the config
changes. It also fails when a count FALLS, until the baseline is lowered with
--update, so an improvement is locked in by the change that made it.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "lint-baseline.json"
PYPROJECT = ROOT / "pyproject.toml"


def suppressed_findings() -> dict[str, dict[str, int]]:
    """{path: {rule: count}} for findings that only a noqa comment hides."""
    ruff = shutil.which("ruff")
    if ruff is None:
        sys.exit("ruff not found; run through `uv run`")
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [ruff, "check", "--ignore-noqa", "--exit-zero", "--output-format=json", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    counts: Counter[tuple[str, str]] = Counter()
    for finding in json.loads(result.stdout):
        path = Path(finding["filename"]).resolve().relative_to(ROOT).as_posix()
        counts[path, finding["code"]] += 1
    nested: dict[str, dict[str, int]] = {}
    for (path, code), n in sorted(counts.items()):
        nested.setdefault(path, {})[code] = n
    return nested


def lint_config() -> dict:
    """The parts of the ruff config that switch findings off wholesale."""
    lint = tomllib.loads(PYPROJECT.read_text())["tool"]["ruff"]["lint"]
    return {
        "ignore": sorted(lint.get("ignore", [])),
        "per-file-ignores": {
            path: sorted(codes)
            for path, codes in sorted(lint.get("per-file-ignores", {}).items())
        },
        "max-complexity": lint.get("mccabe", {}).get("max-complexity"),
    }


def current() -> dict:
    findings = suppressed_findings()
    return {
        "total": sum(n for rules in findings.values() for n in rules.values()),
        "suppressed": findings,
        "config": lint_config(),
    }


def compare(baseline: dict, now: dict) -> tuple[list[str], list[str]]:
    """(regressions, improvements), each a list of human-readable lines."""
    worse, better = [], []
    old, new = baseline["suppressed"], now["suppressed"]
    for path in sorted(old.keys() | new.keys()):
        for code in sorted(old.get(path, {}).keys() | new.get(path, {}).keys()):
            was = old.get(path, {}).get(code, 0)
            is_ = new.get(path, {}).get(code, 0)
            if is_ > was:
                worse.append(f"{path}: {code} {was} -> {is_}")
            elif is_ < was:
                better.append(f"{path}: {code} {was} -> {is_}")
    if baseline["config"] != now["config"]:
        worse.append(
            "ruff config changed (ignore / per-file-ignores / max-complexity):\n"
            f"    baseline: {json.dumps(baseline['config'], sort_keys=True)}\n"
            f"    now:      {json.dumps(now['config'], sort_keys=True)}"
        )
    return worse, better


def write(data: dict) -> None:
    BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--update", action="store_true", help="rewrite lint-baseline.json"
    )
    args = parser.parse_args()

    now = current()
    if args.update:
        write(now)
        print(f"lint-baseline.json updated: {now['total']} suppressed findings")
        return 0

    baseline = json.loads(BASELINE.read_text())
    worse, better = compare(baseline, now)
    if worse:
        print("Lint ratchet: suppressed findings went UP. Fix the code instead of")
        print("adding a noqa or a config ignore. If a suppression is truly needed,")
        print("justify it in review and run scripts/lint_ratchet.py --update.\n")
        print("\n".join(f"  {line}" for line in worse))
        return 1
    if better:
        print("Lint ratchet: suppressed findings went down. Lock the gain in with")
        print("`uv run python scripts/lint_ratchet.py --update` and commit it.\n")
        print("\n".join(f"  {line}" for line in better))
        return 1
    print(f"Lint ratchet: OK ({now['total']} suppressed findings, none new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
