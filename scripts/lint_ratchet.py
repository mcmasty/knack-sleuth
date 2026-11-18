"""Ratchet on lint suppressions: the count may only go down.

Every finding hidden by an inline ``# noqa`` is technical debt that stays
visible at the function it belongs to. This script counts them per file and
rule (by re-running ruff with ``--ignore-noqa``) and compares the counts with
``lint-baseline.json``. It also records the config-level escape hatches
(``ignore``, ``per-file-ignores``, ``max-complexity``) so debt cannot move from
a noqa comment into pyproject.toml unnoticed.

    uv run python scripts/lint_ratchet.py             # check (CI, pre-commit)
    uv run python scripts/lint_ratchet.py --strict    # check, and the baseline must be tight (release tags)
    uv run python scripts/lint_ratchet.py --tighten   # lower the baseline to the code (release bump)
    uv run python scripts/lint_ratchet.py --update    # rewrite the baseline, increases included

The check fails when a count rises, a new file/rule pair appears, or the config
changes. A count that FALLS passes: cleanup PRs don't touch the baseline, so
they can't conflict over it. The release bump runs --tighten (a bump-my-version
pre-commit hook) and commits the lowered baseline, and CI on a release tag runs
--strict, so each release locks in the gains made since the last one.
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


def _report(title: str, lines: list[str]) -> None:
    print(title)
    print("\n".join(f"  {line}" for line in lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--strict",
        action="store_true",
        help="also fail when the baseline is looser than the code",
    )
    mode.add_argument(
        "--tighten",
        action="store_true",
        help="lower lint-baseline.json to the code; refuses if anything went up",
    )
    mode.add_argument(
        "--update",
        action="store_true",
        help="rewrite lint-baseline.json, increases included",
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
        _report(
            "Lint ratchet: suppressed findings went UP. Fix the code instead of\n"
            "adding a noqa or a config ignore. If a suppression is truly needed,\n"
            "justify it in review and run scripts/lint_ratchet.py --update.\n",
            worse,
        )
        return 1
    if better and args.tighten:
        write(now)
        _report(f"lint-baseline.json tightened to {now['total']}:", better)
        return 0
    if better and args.strict:
        _report(
            "Lint ratchet: lint-baseline.json is looser than the code. The release\n"
            "bump tightens it; run scripts/lint_ratchet.py --tighten and commit it.\n",
            better,
        )
        return 1
    if better:
        _report(
            f"Lint ratchet: OK ({now['total']} suppressed findings, down from "
            f"{baseline['total']}; the next release bump locks this in)",
            better,
        )
        return 0
    print(f"Lint ratchet: OK ({now['total']} suppressed findings, none new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
