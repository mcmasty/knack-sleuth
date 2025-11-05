"""Tests for database schema export functionality."""


import pytest
import yaml

from knack_sleuth.db_schema import (
    export_database_schema,
    export_to_dbml,
    export_to_json_schema,
    export_to_yaml,
)
from knack_sleuth.models import KnackAppMetadata


@pytest.fixture
def sample_app(sample_metadata_dict):
    """Sample Knack application."""
    return KnackAppMetadata(**sample_metadata_dict).application


class TestJSONSchemaExport:
    """Tests for JSON Schema export."""

    def test_export_to_json_schema(self, sample_app):
        """Test exporting to JSON Schema format."""
        schema = export_to_json_schema(sample_app)

        # Check schema structure
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["title"] == sample_app.name
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "definitions" in schema

        # Check metadata
        assert schema["x-knack-app-id"] == sample_app.id
        assert schema["x-knack-slug"] == sample_app.slug

        # Verify all objects are in definitions
        for obj in sample_app.objects:
            assert obj.key in schema["definitions"]
            obj_schema = schema["definitions"][obj.key]
            assert obj_schema["type"] == "object"
            assert obj_schema["title"] == obj.name
            assert obj_schema["x-knack-key"] == obj.key
            assert "properties" in obj_schema

    def test_json_schema_field_properties(self, sample_app):
        """Test that fields are properly represented in JSON Schema."""
        schema = export_to_json_schema(sample_app)

        # Find first object with fields
        obj = sample_app.objects[0]
        obj_schema = schema["definitions"][obj.key]

        # Check field properties
        for field in obj.fields:
            assert field.key in obj_schema["properties"]
            field_schema = obj_schema["properties"][field.key]
            assert "type" in field_schema
            assert field_schema["title"] == field.name
            assert field_schema["x-knack-type"] == field.type
            assert field_schema["x-knack-key"] == field.key

    def test_json_schema_required_fields(self, sample_app):
        """Test that required fields are marked in schema."""
        schema = export_to_json_schema(sample_app)

        for obj in sample_app.objects:
            obj_schema = schema["definitions"][obj.key]
            required_fields = [f.key for f in obj.fields if f.required]

            if required_fields:
                assert "required" in obj_schema
                assert obj_schema["required"] == required_fields

    def test_json_schema_connections(self, sample_app):
        """Test that connections are properly represented."""
        schema = export_to_json_schema(sample_app)

        for obj in sample_app.objects:
            if obj.connections and obj.connections.outbound:
                obj_schema = schema["definitions"][obj.key]
                assert "x-connections" in obj_schema
                assert "outbound" in obj_schema["x-connections"]

                # Verify connection details
                for i, conn in enumerate(obj.connections.outbound):
                    conn_schema = obj_schema["x-connections"]["outbound"][i]
                    assert conn_schema["key"] == conn.key
                    assert conn_schema["name"] == conn.name
                    assert conn_schema["target_object"] == conn.object
                    assert conn_schema["has"] in ["one", "many"]
                    assert conn_schema["belongs_to"] in ["one", "many"]

    def test_json_schema_relationship_fields(self, sample_app):
        """Test that relationship fields have proper metadata."""
        schema = export_to_json_schema(sample_app)

        for obj in sample_app.objects:
            obj_schema = schema["definitions"][obj.key]
            for field in obj.fields:
                if field.relationship:
                    field_schema = obj_schema["properties"][field.key]
                    assert "x-relationship" in field_schema
                    rel = field_schema["x-relationship"]
                    assert rel["has"] == field.relationship.has
                    assert rel["object"] == field.relationship.object
                    assert rel["belongs_to"] == field.relationship.belongs_to


class TestDBMLExport:
    """Tests for DBML export."""

    def test_export_to_dbml(self, sample_app):
        """Test exporting to DBML format."""
        dbml = export_to_dbml(sample_app)

        assert isinstance(dbml, str)
        assert len(dbml) > 0

        # Check for basic DBML structure
        assert f"Database schema for: {sample_app.name}" in dbml
        assert f"Knack App ID: {sample_app.id}" in dbml
        assert "Project knack_app" in dbml

    def test_dbml_contains_tables(self, sample_app):
        """Test that DBML contains table definitions."""
        dbml = export_to_dbml(sample_app)

        # All objects should be represented as tables
        for obj in sample_app.objects:
            assert f"Table {obj.key}" in dbml
            assert f"// {obj.name}" in dbml

    def test_dbml_contains_fields(self, sample_app):
        """Test that DBML contains field definitions."""
        dbml = export_to_dbml(sample_app)

        # Check that fields are included
        for obj in sample_app.objects:
            for field in obj.fields:
                # Field key should be in the DBML
                assert field.key in dbml

    def test_dbml_contains_relationships(self, sample_app):
        """Test that DBML contains relationship definitions."""
        dbml = export_to_dbml(sample_app)

        # Check for relationships section
        assert "// Relationships" in dbml

        # Check for relationship definitions
        for obj in sample_app.objects:
            if obj.connections and obj.connections.outbound:
                for conn in obj.connections.outbound:
                    # Should have a Ref line for each connection
                    assert f"Ref: {obj.key}.{conn.key}" in dbml

    def test_dbml_field_constraints(self, sample_app):
        """Test that DBML includes field constraints."""
        dbml = export_to_dbml(sample_app)

        # Look for required and unique constraints
        for obj in sample_app.objects:
            for field in obj.fields:
                if field.required:
                    # Required fields should have "not null"
                    # Note: we check this exists somewhere in the DBML
                    # as the exact position depends on field ordering
                    assert "not null" in dbml


class TestYAMLExport:
    """Tests for YAML export."""

    def test_export_to_yaml(self, sample_app):
        """Test exporting to YAML format."""
        yaml_str = export_to_yaml(sample_app)

        assert isinstance(yaml_str, str)
        assert len(yaml_str) > 0

        # Parse YAML to verify structure
        data = yaml.safe_load(yaml_str)
        assert "application" in data
        assert "objects" in data

    def test_yaml_application_metadata(self, sample_app):
        """Test that YAML contains application metadata."""
        yaml_str = export_to_yaml(sample_app)
        data = yaml.safe_load(yaml_str)

        app_data = data["application"]
        assert app_data["name"] == sample_app.name
        assert app_data["slug"] == sample_app.slug
        assert app_data["id"] == sample_app.id

    def test_yaml_objects_structure(self, sample_app):
        """Test that YAML contains proper object structure."""
        yaml_str = export_to_yaml(sample_app)
        data = yaml.safe_load(yaml_str)

        # Verify all objects are present
        assert len(data["objects"]) == len(sample_app.objects)

        for obj_data, obj in zip(data["objects"], sample_app.objects):
            assert obj_data["key"] == obj.key
            assert obj_data["name"] == obj.name
            assert "fields" in obj_data
            assert isinstance(obj_data["fields"], list)

    def test_yaml_fields_structure(self, sample_app):
        """Test that YAML contains proper field structure."""
        yaml_str = export_to_yaml(sample_app)
        data = yaml.safe_load(yaml_str)

        for obj_data, obj in zip(data["objects"], sample_app.objects):
            # Verify fields
            assert len(obj_data["fields"]) == len(obj.fields)

            for field_data, field in zip(obj_data["fields"], obj.fields):
                assert field_data["key"] == field.key
                assert field_data["name"] == field.name
                assert field_data["type"] == field.type
                assert "sql_type" in field_data
                assert field_data["required"] == field.required
                assert field_data["unique"] == field.unique

    def test_yaml_connections(self, sample_app):
        """Test that YAML includes connection information."""
        yaml_str = export_to_yaml(sample_app)
        data = yaml.safe_load(yaml_str)

        for obj_data, obj in zip(data["objects"], sample_app.objects):
            if obj.connections and (obj.connections.outbound or obj.connections.inbound):
                assert "connections" in obj_data

                if obj.connections.outbound:
                    assert "outbound" in obj_data["connections"]
                    for conn_data, conn in zip(
                        obj_data["connections"]["outbound"], obj.connections.outbound
                    ):
                        assert conn_data["key"] == conn.key
                        assert conn_data["name"] == conn.name
                        assert conn_data["target_object"] == conn.object
                        assert "relationship_type" in conn_data

    def test_yaml_relationship_types(self, sample_app):
        """Test that relationship types are correctly identified."""
        yaml_str = export_to_yaml(sample_app)
        data = yaml.safe_load(yaml_str)

        valid_relationship_types = {
            "one-to-one",
            "one-to-many",
            "many-to-one",
            "many-to-many",
        }

        for obj_data in data["objects"]:
            if "connections" in obj_data:
                if "outbound" in obj_data["connections"]:
                    for conn in obj_data["connections"]["outbound"]:
                        assert conn["relationship_type"] in valid_relationship_types
                if "inbound" in obj_data["connections"]:
                    for conn in obj_data["connections"]["inbound"]:
                        assert conn["relationship_type"] in valid_relationship_types


class TestExportDatabaseSchema:
    """Tests for the main export_database_schema function."""

    def test_export_json_format(self, sample_app):
        """Test exporting with JSON format."""
        result = export_database_schema(sample_app, format="json")
        assert isinstance(result, dict)
        assert "$schema" in result

    def test_export_dbml_format(self, sample_app):
        """Test exporting with DBML format."""
        result = export_database_schema(sample_app, format="dbml")
        assert isinstance(result, str)
        assert "Table" in result

    def test_export_yaml_format(self, sample_app):
        """Test exporting with YAML format."""
        result = export_database_schema(sample_app, format="yaml")
        assert isinstance(result, str)
        data = yaml.safe_load(result)
        assert "application" in data

    def test_export_invalid_format(self, sample_app):
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported format"):
            export_database_schema(sample_app, format="invalid")

    def test_export_invalid_detail(self, sample_app):
        """Test that invalid detail level raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported detail level"):
            export_database_schema(sample_app, format="json", detail="invalid")


class TestDetailLevels:
    """Tests for detail level filtering."""

    def test_minimal_detail_json(self, sample_app):
        """Test minimal detail includes only connection fields."""
        schema = export_to_json_schema(sample_app, detail="minimal")

        # Find an object with both connection and non-connection fields
        for obj in sample_app.objects:
            if not obj.fields:
                continue

            obj_schema = schema["definitions"][obj.key]
            fields_in_schema = obj_schema["properties"]

            # Check that only connection fields are included
            for field in obj.fields:
                if field.type == "connection":
                    assert field.key in fields_in_schema, f"Connection field {field.key} should be in minimal detail"
                else:
                    assert field.key not in fields_in_schema, f"Non-connection field {field.key} should not be in minimal detail"

    def test_compact_detail_json(self, sample_app):
        """Test compact detail includes identifier, required, and connection fields."""
        schema = export_to_json_schema(sample_app, detail="compact")

        # Find an object with various field types
        for obj in sample_app.objects:
            if not obj.fields:
                continue

            obj_schema = schema["definitions"][obj.key]
            fields_in_schema = obj_schema["properties"]

            # Check field inclusion rules
            for field in obj.fields:
                should_include = (
                    field.type == "connection" or
                    field.key == obj.identifier or
                    field.required
                )

                if should_include:
                    assert field.key in fields_in_schema, f"Field {field.key} should be in compact detail"
                else:
                    assert field.key not in fields_in_schema, f"Field {field.key} should not be in compact detail"

    def test_standard_detail_json(self, sample_app):
        """Test standard detail includes all fields."""
        schema = export_to_json_schema(sample_app, detail="standard")

        # Verify all fields are included for all objects
        for obj in sample_app.objects:
            obj_schema = schema["definitions"][obj.key]
            fields_in_schema = obj_schema["properties"]

            # All fields should be present
            for field in obj.fields:
                assert field.key in fields_in_schema, f"All fields should be in standard detail, missing {field.key}"

    def test_minimal_detail_dbml(self, sample_app):
        """Test minimal detail DBML includes only connection fields."""
        dbml = export_to_dbml(sample_app, detail="minimal")

        # Verify DBML contains tables
        assert "Table" in dbml

        # Check that connections are still present
        if any(obj.connections and obj.connections.outbound for obj in sample_app.objects):
            assert "Ref:" in dbml

    def test_compact_detail_yaml(self, sample_app):
        """Test compact detail YAML structure."""
        yaml_str = export_to_yaml(sample_app, detail="compact")
        data = yaml.safe_load(yaml_str)

        # Verify basic structure
        assert "application" in data
        assert "objects" in data

        # Check that fields are filtered
        for obj_data in data["objects"]:
            if not obj_data["fields"]:
                continue

            # Find corresponding object in sample_app
            obj = next(o for o in sample_app.objects if o.key == obj_data["key"])

            # Verify only appropriate fields are included
            field_keys_in_export = {f["key"] for f in obj_data["fields"]}

            for field in obj.fields:
                should_include = (
                    field.type == "connection" or
                    field.key == obj.identifier or
                    field.required
                )

                if should_include:
                    assert field.key in field_keys_in_export
                else:
                    assert field.key not in field_keys_in_export

    def test_detail_levels_preserve_connections(self, sample_app):
        """Test that all detail levels preserve connection metadata."""
        for detail in ["minimal", "compact", "standard"]:
            schema = export_to_json_schema(sample_app, detail=detail)

            # Verify connections are preserved for all objects
            for obj in sample_app.objects:
                if obj.connections:
                    obj_schema = schema["definitions"][obj.key]
                    assert "x-connections" in obj_schema, f"Connections should be preserved in {detail} detail"
