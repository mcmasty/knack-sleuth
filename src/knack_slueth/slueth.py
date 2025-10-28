"""Core search functionality for finding object and field usages in Knack metadata."""

from dataclasses import dataclass
from typing import Any

from knack_slueth.models import Application, KnackAppExport, KnackObject


@dataclass
class Usage:
    """Represents a usage of an object or field."""

    location_type: str  # "connection", "view_source", "view_column", "field_equation", etc.
    context: str  # Human-readable description of where it's used
    details: dict[str, Any]  # Additional context-specific information


class KnackSlueth:
    """Search engine for finding object and field usages in Knack metadata."""

    def __init__(self, app_export: KnackAppExport):
        self.app = app_export.application
        self._build_indexes()

    def _build_indexes(self) -> None:
        """Build lookup indexes for faster searching."""
        # Object index
        self.objects_by_key: dict[str, KnackObject] = {
            obj.key: obj for obj in self.app.objects
        }

        # Field index (field_key -> object_key)
        self.field_to_object: dict[str, str] = {}
        for obj in self.app.objects:
            for field in obj.fields:
                self.field_to_object[field.key] = obj.key

    def search_object(self, object_key: str) -> dict[str, list[Usage]]:
        """
        Search for all usages of an object and cascade to its fields.

        Returns a dict with:
        - "object_usages": list of usages of the object itself
        - field keys (e.g., "field_116"): list of usages for each field
        """
        if object_key not in self.objects_by_key:
            return {}

        obj = self.objects_by_key[object_key]
        results: dict[str, list[Usage]] = {"object_usages": []}

        # Search for object-level usages
        results["object_usages"] = self._find_object_usages(object_key)

        # Cascade: search for each field in the object
        for field in obj.fields:
            field_usages = self._find_field_usages(field.key)
            if field_usages:
                results[field.key] = field_usages

        return results

    def search_field(self, field_key: str) -> list[Usage]:
        """Search for all usages of a specific field."""
        if field_key not in self.field_to_object:
            return []

        return self._find_field_usages(field_key)

    def _find_object_usages(self, object_key: str) -> list[Usage]:
        """Find all places where an object is referenced."""
        usages: list[Usage] = []

        # 1. Check connections (inbound and outbound)
        for obj in self.app.objects:
            if obj.connections:
                # Check outbound connections
                for conn in obj.connections.outbound:
                    if conn.object == object_key:
                        usages.append(
                            Usage(
                                location_type="connection_outbound",
                                context=f"{obj.name} ({obj.key}) connects to this object via {conn.name} ({conn.key})",
                                details={
                                    "source_object": obj.key,
                                    "source_object_name": obj.name,
                                    "connection_field": conn.key,
                                    "connection_name": conn.name,
                                    "relationship": f"{conn.has} to {conn.belongs_to}",
                                },
                            )
                        )

                # Check inbound connections
                for conn in obj.connections.inbound:
                    if conn.object == object_key:
                        usages.append(
                            Usage(
                                location_type="connection_inbound",
                                context=f"This object connects from {obj.name} ({obj.key}) via {conn.name} ({conn.key})",
                                details={
                                    "target_object": obj.key,
                                    "target_object_name": obj.name,
                                    "connection_field": conn.key,
                                    "connection_name": conn.name,
                                    "relationship": f"{conn.has} to {conn.belongs_to}",
                                },
                            )
                        )

        # 2. Check view sources
        for scene in self.app.scenes:
            for view in scene.views:
                if view.source and view.source.object == object_key:
                    usages.append(
                        Usage(
                            location_type="view_source",
                            context=f"View '{view.name}' ({view.key}) in scene '{scene.name}' ({scene.key}) displays this object",
                            details={
                                "scene_key": scene.key,
                                "scene_name": scene.name,
                                "view_key": view.key,
                                "view_name": view.name,
                                "view_type": view.type,
                            },
                        )
                    )

                # Check parent_source
                if (
                    view.source
                    and view.source.parent_source
                    and view.source.parent_source.object == object_key
                ):
                    usages.append(
                        Usage(
                            location_type="view_parent_source",
                            context=f"View '{view.name}' ({view.key}) uses this object as parent source",
                            details={
                                "scene_key": scene.key,
                                "scene_name": scene.name,
                                "view_key": view.key,
                                "view_name": view.name,
                            },
                        )
                    )

        return usages

    def _find_field_usages(self, field_key: str) -> list[Usage]:
        """Find all places where a field is referenced."""
        usages: list[Usage] = []

        # 1. Check if it's a connection field
        for obj in self.app.objects:
            if obj.connections:
                for conn in obj.connections.outbound:
                    if conn.key == field_key:
                        usages.append(
                            Usage(
                                location_type="connection_field",
                                context=f"Connection field in {obj.name} ({obj.key})",
                                details={
                                    "object_key": obj.key,
                                    "object_name": obj.name,
                                    "target_object": conn.object,
                                    "connection_name": conn.name,
                                },
                            )
                        )

        # 2. Check object sort fields
        for obj in self.app.objects:
            if obj.sort and obj.sort.field == field_key:
                usages.append(
                    Usage(
                        location_type="object_sort",
                        context=f"Used as sort field for {obj.name} ({obj.key})",
                        details={
                            "object_key": obj.key,
                            "object_name": obj.name,
                            "sort_order": obj.sort.order,
                        },
                    )
                )

            # Check if it's the identifier field
            if obj.identifier == field_key:
                usages.append(
                    Usage(
                        location_type="object_identifier",
                        context=f"Used as identifier field for {obj.name} ({obj.key})",
                        details={
                            "object_key": obj.key,
                            "object_name": obj.name,
                        },
                    )
                )

        # 3. Check field equations (field references like {field_123})
        for obj in self.app.objects:
            for field in obj.fields:
                if field.format:
                    # Access equation from the format dict if it exists
                    format_dict = (
                        field.format.model_dump()
                        if hasattr(field.format, "model_dump")
                        else {}
                    )
                    equation = format_dict.get("equation")
                    if equation and f"{{{field_key}}}" in str(equation):
                        usages.append(
                            Usage(
                                location_type="field_equation",
                                context=f"Referenced in equation for {obj.name}.{field.name} ({field.key})",
                                details={
                                    "object_key": obj.key,
                                    "object_name": obj.name,
                                    "field_key": field.key,
                                    "field_name": field.name,
                                    "equation": equation,
                                },
                            )
                        )

        # 4. Check view columns
        for scene in self.app.scenes:
            for view in scene.views:
                for col in view.columns:
                    if col.field and col.field.get("key") == field_key:
                        usages.append(
                            Usage(
                                location_type="view_column",
                                context=f"Column in view '{view.name}' ({view.key}) in scene '{scene.name}'",
                                details={
                                    "scene_key": scene.key,
                                    "scene_name": scene.name,
                                    "view_key": view.key,
                                    "view_name": view.name,
                                    "view_type": view.type,
                                    "column_header": col.header,
                                },
                            )
                        )

        # 5. Check view source sort fields
        for scene in self.app.scenes:
            for view in scene.views:
                if view.source and view.source.sort:
                    for sort in view.source.sort:
                        if sort.field == field_key:
                            usages.append(
                                Usage(
                                    location_type="view_sort",
                                    context=f"Sort field in view '{view.name}' ({view.key})",
                                    details={
                                        "scene_key": scene.key,
                                        "scene_name": scene.name,
                                        "view_key": view.key,
                                        "view_name": view.name,
                                        "sort_order": sort.order,
                                    },
                                )
                            )

                # Check connection_key in parent_source
                if (
                    view.source
                    and view.source.parent_source
                    and view.source.parent_source.connection == field_key
                ):
                    usages.append(
                        Usage(
                            location_type="view_parent_connection",
                            context=f"Parent connection in view '{view.name}' ({view.key})",
                            details={
                                "scene_key": scene.key,
                                "scene_name": scene.name,
                                "view_key": view.key,
                                "view_name": view.name,
                            },
                        )
                    )

                # Check connection_key
                if view.source and view.source.connection_key == field_key:
                    usages.append(
                        Usage(
                            location_type="view_connection_key",
                            context=f"Connection key in view '{view.name}' ({view.key})",
                            details={
                                "scene_key": scene.key,
                                "scene_name": scene.name,
                                "view_key": view.key,
                                "view_name": view.name,
                            },
                        )
                    )

        # 6. Check form inputs
        for scene in self.app.scenes:
            for view in scene.views:
                for input_field in view.inputs:
                    if (
                        isinstance(input_field, dict)
                        and input_field.get("key") == field_key
                    ):
                        usages.append(
                            Usage(
                                location_type="form_input",
                                context=f"Input field in form '{view.name}' ({view.key})",
                                details={
                                    "scene_key": scene.key,
                                    "scene_name": scene.name,
                                    "view_key": view.key,
                                    "view_name": view.name,
                                },
                            )
                        )

        return usages

    def get_object_info(self, object_key: str) -> KnackObject | None:
        """Get the object definition."""
        return self.objects_by_key.get(object_key)

    def get_field_info(self, field_key: str) -> tuple[KnackObject | None, Any]:
        """Get the field definition and its parent object."""
        object_key = self.field_to_object.get(field_key)
        if not object_key:
            return None, None

        obj = self.objects_by_key[object_key]
        for field in obj.fields:
            if field.key == field_key:
                return obj, field

        return obj, None