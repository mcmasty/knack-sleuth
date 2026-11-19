"""Structural checks a DBML or Mermaid parser would make, without Node.

dbdiagram rejects a Ref to a column its table doesn't declare, and a
connection left out of an ER diagram is a relationship the reader never sees.
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from knack_sleuth.cli import cli
from knack_sleuth.db_schema import (
    _relationship,
    export_to_dbml,
    export_to_mermaid,
    export_to_yaml,
)
from knack_sleuth.models import (
    Application,
    Connection,
    ConnectionField,
    KnackAppMetadata,
)

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
    ("has_belongs_to", "expected"),
    [
        # Events.Client: each Event holds one Client, a Client is on many Events.
        (("one", "many"), ("many-to-one", "one-to-many", ">", "}o--||")),
        (("many", "one"), ("one-to-many", "many-to-one", "<", "||--o{")),
        (("one", "one"), ("one-to-one", "one-to-one", "-", "||--||")),
        (("many", "many"), ("many-to-many", "many-to-many", "<>", "}o--o{")),
        # Anything unexpected counts as many.
        (("", "one"), ("one-to-many", "many-to-one", "<", "||--o{")),
    ],
)
def test_cardinality_reads_from_the_connecting_object(has_belongs_to, expected):
    has, belongs_to = has_belongs_to
    label, reverse, dbml, mermaid = expected
    conn = Connection(
        key="field_1",
        name="Client",
        object="object_2",
        has=has,
        belongs_to=belongs_to,
        field=ConnectionField(name="Client"),
    )
    assert conn.relationship_type() == label
    assert conn.relationship_type(from_connected=True) == reverse
    assert _relationship(conn) == (dbml, mermaid)


def test_yaml_relationship_type_reads_from_the_listing_object():
    """Owner is object_1 -> object_2 with has=one, belongs_to=many: many
    Accounts to one object_2 record, so object_2 lists it as one-to-many."""
    exported = yaml.safe_load(export_to_yaml(load("schema_cases_meta.json")))
    objects = {obj["key"]: obj for obj in exported["objects"]}

    def label(object_key, direction):
        [entry] = [
            c
            for c in objects[object_key]["connections"][direction]
            if c["key"] == "field_3"
        ]
        return entry["relationship_type"]

    assert label("object_1", "outbound") == "many-to-one"
    assert label("object_2", "inbound") == "one-to-many"


SCHEMA_CASES = str(DATA / "schema_cases_meta.json")


def test_show_coupling_labels_read_from_the_object_shown():
    """object_2 is on the 'one' side of Owner (many object_1 records to one
    object_2) and holds many object_1 records through Account Link."""
    result = CliRunner().invoke(
        cli, ["show-coupling", "object_2", SCHEMA_CASES, "--format", "json"]
    )
    payload = json.loads(result.output)
    labels = {
        c["connection_key"]: c["relationship_type"]
        for c in payload["inbound"] + payload["outbound"]
    }
    assert labels == {
        "field_3": "one-to-many",
        "field_20": "one-to-one",
        "field_21": "one-to-many",
    }

    rich = CliRunner().invoke(cli, ["show-coupling", "object_2", SCHEMA_CASES])
    assert "via Owner (field_3) [one-to-many]" in rich.output


def test_search_object_relationship_reads_from_the_connecting_object():
    result = CliRunner().invoke(
        cli, ["search-object", "object_2", SCHEMA_CASES, "--format", "json"]
    )
    assert '"relationship": "many-to-one"' in result.output
    assert "one to many" not in result.output
