"""Structural checks a DBML or Mermaid parser would make, without Node.

dbdiagram rejects a Ref to a column its table doesn't declare, and a
connection left out of an ER diagram is a relationship the reader never sees.
"""

import json
import re
from pathlib import Path

import pytest

from knack_sleuth.db_schema import _relationship, export_to_dbml, export_to_mermaid
from knack_sleuth.models import Application, KnackAppMetadata

DATA = Path(__file__).parent / "data"
FIXTURES = ["schema_cases_meta.json", "sample_knack_app_meta.json"]
DETAILS = ("structural", "minimal", "compact", "standard")


def load(fixture: str) -> Application:
    return KnackAppMetadata(**json.loads((DATA / fixture).read_text())).application


def dbml_columns(dbml: str) -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    current = None
    for line in dbml.splitlines():
        if match := re.match(r"Table (\S+) \{", line):
            current = tables.setdefault(match.group(1), set())
        elif line == "}":
            current = None
        elif current is not None and (match := re.match(r"  (\w+) \S", line)):
            current.add(match.group(1))
    for columns in tables.values():
        columns.discard("Note")
    return tables


@pytest.mark.parametrize("detail", DETAILS)
@pytest.mark.parametrize("fixture", FIXTURES)
def test_every_dbml_ref_endpoint_is_a_declared_column(fixture, detail):
    app = load(fixture)
    dbml = export_to_dbml(app, detail)
    columns = dbml_columns(dbml)
    refs = re.findall(r"^Ref: (\w+)\.(\w+) \S+ (\w+)\.(\w+)", dbml, re.MULTILINE)
    outbound = sum(
        len(obj.connections.outbound) for obj in app.objects if obj.connections
    )
    assert len(refs) == outbound > 0
    for table, column, target_table, target_column in refs:
        assert column in columns[table]
        assert target_column in columns[target_table]


def test_dbml_ref_points_at_the_record_id_even_without_an_identifier():
    app = load("schema_cases_meta.json")
    assert app.objects[1].identifier is None
    assert "Ref: object_1.field_3 > object_2.id // Owner" in export_to_dbml(app)


def test_dbml_strings_are_escaped_and_comments_stay_on_one_line():
    app = load("schema_cases_meta.json")
    app.name = 'Line one\nline "two" \\ end'
    dbml = export_to_dbml(app)
    assert '  Note: "Line one line \\"two\\" \\\\ end"' in dbml
    assert '// Database schema for: Line one line "two" \\ end' in dbml


@pytest.mark.parametrize("fixture", FIXTURES)
def test_mermaid_draws_every_connection(fixture):
    app = load(fixture)
    mermaid = export_to_mermaid(app)
    lines = [line for line in mermaid.splitlines() if re.search(r"--.* : ", line)]
    outbound = [
        conn.name
        for obj in app.objects
        for conn in (obj.connections.outbound if obj.connections else [])
    ]
    assert [line.rsplit(" : ", 1)[1].strip('"') for line in lines] == outbound


def test_mermaid_labels_and_comments_never_contain_a_bare_double_quote():
    app = load("schema_cases_meta.json")
    connections = app.objects[0].connections
    assert connections is not None
    connections.outbound[0].name = 'The "owner"'
    mermaid = export_to_mermaid(app)
    assert ": \"The 'owner'\"" in mermaid
    for line in mermaid.splitlines():
        quoted = line.split('"', 1)[1] if '"' in line else ""
        assert quoted.count('"') <= 1


@pytest.mark.parametrize(
    ("has", "belongs_to", "label", "dbml", "mermaid"),
    [
        # Events.Client: each Event holds one Client, a Client is on many Events.
        ("one", "many", "many-to-one", ">", "}o--||"),
        ("many", "one", "one-to-many", "<", "||--o{"),
        ("one", "one", "one-to-one", "-", "||--||"),
        ("many", "many", "many-to-many", "<>", "}o--o{"),
    ],
)
def test_cardinality_reads_from_the_connecting_object(
    has, belongs_to, label, dbml, mermaid
):
    assert _relationship(has, belongs_to) == (label, dbml, mermaid)
