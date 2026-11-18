"""Schema exports of a synthetic app, compared with golden files.

tests/data/schema_cases_meta.json covers what the sample fixtures don't: all
four has/belongs_to combinations, two objects with the same name, a target
object without an identifier, a user object, an object name starting with a
digit, a field description with HTML and quotes, an unknown field type, and
an app name with quotes. Every exporter runs at every detail level.

A deliberate output change regenerates the files with

    UPDATE_GOLDEN=1 uv run pytest tests/test_schema_export_golden.py

and the golden diff shows exactly what moved.
"""

import json
import os
from pathlib import Path

import pytest

from knack_sleuth.db_schema import (
    export_to_dbml,
    export_to_json_schema,
    export_to_mermaid,
    export_to_yaml,
)
from knack_sleuth.models import KnackAppMetadata

DATA = Path(__file__).parent / "data"
GOLDEN = DATA / "golden" / "schema_cases"
DETAILS = ("structural", "minimal", "compact", "standard")
EXPORTERS = {
    "json": lambda app, detail: json.dumps(
        export_to_json_schema(app, detail), indent=2, ensure_ascii=False
    ),
    "dbml": export_to_dbml,
    "yaml": export_to_yaml,
    "mmd": export_to_mermaid,
}


@pytest.fixture(scope="module")
def app():
    metadata = json.loads((DATA / "schema_cases_meta.json").read_text())
    return KnackAppMetadata(**metadata).application


@pytest.mark.parametrize("detail", DETAILS)
@pytest.mark.parametrize("fmt", EXPORTERS)
def test_matches_golden(app, fmt, detail):
    # Exactly one trailing newline, as pre-commit's end-of-file-fixer leaves it.
    actual = EXPORTERS[fmt](app, detail).rstrip("\n") + "\n"
    golden = GOLDEN / f"{detail}.{fmt}"
    if os.environ.get("UPDATE_GOLDEN"):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)
    assert actual == golden.read_text()


def test_fixture_has_every_relationship_shape(app):
    shapes = {
        (conn.has, conn.belongs_to)
        for obj in app.objects
        for conn in (obj.connections.outbound if obj.connections else [])
    }
    assert shapes == {
        ("one", "one"),
        ("one", "many"),
        ("many", "one"),
        ("many", "many"),
    }
