"""Core search functionality for finding object and field usages in Knack metadata."""

from dataclasses import dataclass
from typing import Any

from knack_sleuth.models import KnackAppMetadata, KnackObject


@dataclass
class Usage:
    """Represents a usage of an object or field."""

    location_type: str  # "connection", "view_source", "view_column", "field_equation", etc.
    context: str  # Human-readable description of where it's used
    details: dict[str, Any]  # Additional context-specific information


class KnackSleuth:
    """Search engine for finding object and field usages in Knack metadata."""

    def __init__(self, app_export: KnackAppMetadata):
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

    def generate_impact_analysis(
        self, target_key: str, target_type: str = "auto"
    ) -> dict[str, Any]:
        """
        Generate a comprehensive impact analysis for AI consumption.

        Args:
            target_key: The object or field key to analyze (e.g., 'object_12' or 'field_116')
            target_type: 'object', 'field', or 'auto' (default: auto-detect)

        Returns:
            A structured dictionary with impact analysis suitable for AI agents
        """
        # Auto-detect target type
        if target_type == "auto":
            if target_key.startswith("object_"):
                target_type = "object"
            elif target_key.startswith("field_"):
                target_type = "field"
            else:
                return {"error": "Could not detect target type from key"}

        # Initialize analysis structure
        analysis = {
            "target": {
                "key": target_key,
                "type": target_type,
                "name": None,
                "description": None,
            },
            "direct_impacts": {
                "connections": [],
                "views": [],
                "scenes": [],
                "formulas": [],
                "forms": [],
            },
            "cascade_impacts": {
                "affected_fields": [],
                "affected_objects": [],
                "affected_scenes": [],
                "dependency_chains": [],
            },
            "risk_assessment": {
                "breaking_change_likelihood": "unknown",
                "impact_score": 0,
                "affected_user_workflows": [],
            },
            "metadata": {
                "total_direct_impacts": 0,
                "total_cascade_impacts": 0,
                "analysis_timestamp": None,
            },
        }

        # Perform analysis based on target type
        if target_type == "object":
            analysis = self._analyze_object_impact(target_key, analysis)
        elif target_type == "field":
            analysis = self._analyze_field_impact(target_key, analysis)

        return analysis

    def _analyze_object_impact(
        self, object_key: str, analysis: dict[str, Any]
    ) -> dict[str, Any]:
        """Analyze impact of changes to an object."""
        obj = self.get_object_info(object_key)
        if not obj:
            analysis["error"] = f"Object {object_key} not found"
            return analysis

        # Update target info
        analysis["target"]["name"] = obj.name
        analysis["target"]["description"] = f"{len(obj.fields)} fields"

        # Get all usages
        results = self.search_object(object_key)
        object_usages = results.get("object_usages", [])

        # Categorize direct impacts
        scenes_set = set()
        views_set = set()

        for usage in object_usages:
            if "connection" in usage.location_type:
                analysis["direct_impacts"]["connections"].append(
                    {
                        "type": usage.location_type,
                        "description": usage.context,
                        "source_object": usage.details.get("source_object"),
                        "connection_field": usage.details.get("connection_field"),
                    }
                )
            elif "view" in usage.location_type:
                view_key = usage.details.get("view_key")
                scene_key = usage.details.get("scene_key")
                if view_key:
                    views_set.add(view_key)
                if scene_key:
                    scenes_set.add(scene_key)
                analysis["direct_impacts"]["views"].append(
                    {
                        "view_key": view_key,
                        "view_name": usage.details.get("view_name"),
                        "view_type": usage.details.get("view_type"),
                        "scene_key": scene_key,
                        "scene_name": usage.details.get("scene_name"),
                    }
                )

        # Process field-level cascades
        field_results = {k: v for k, v in results.items() if k.startswith("field_")}
        for field_key, usages in field_results.items():
            _, field_info = self.get_field_info(field_key)
            if field_info:
                field_impact = {
                    "field_key": field_key,
                    "field_name": field_info.name,
                    "field_type": field_info.type,
                    "usage_count": len(usages),
                    "usages": [],
                }

                for usage in usages:
                    if usage.location_type == "field_equation":
                        analysis["direct_impacts"]["formulas"].append(
                            {
                                "field_key": usage.details.get("field_key"),
                                "field_name": usage.details.get("field_name"),
                                "object_key": usage.details.get("object_key"),
                                "equation": usage.details.get("equation"),
                            }
                        )
                    elif usage.location_type == "form_input":
                        analysis["direct_impacts"]["forms"].append(
                            {
                                "view_key": usage.details.get("view_key"),
                                "view_name": usage.details.get("view_name"),
                                "scene_key": usage.details.get("scene_key"),
                            }
                        )

                    if "scene_key" in usage.details:
                        scenes_set.add(usage.details["scene_key"])
                    if "view_key" in usage.details:
                        views_set.add(usage.details["view_key"])

                    field_impact["usages"].append(
                        {
                            "type": usage.location_type,
                            "context": usage.context,
                        }
                    )

                analysis["cascade_impacts"]["affected_fields"].append(field_impact)

        # Populate scene info
        for scene_key in scenes_set:
            for scene in self.app.scenes:
                if scene.key == scene_key:
                    analysis["direct_impacts"]["scenes"].append(
                        {
                            "scene_key": scene_key,
                            "scene_name": scene.name,
                            "scene_slug": scene.slug,
                        }
                    )
                    analysis["cascade_impacts"]["affected_scenes"].append(scene_key)
                    break

        # Calculate impact score and risk
        total_impacts = (
            len(analysis["direct_impacts"]["connections"])
            + len(analysis["direct_impacts"]["views"])
            + len(analysis["direct_impacts"]["formulas"])
            + len(analysis["direct_impacts"]["forms"])
        )

        analysis["metadata"]["total_direct_impacts"] = total_impacts
        analysis["metadata"]["total_cascade_impacts"] = len(
            analysis["cascade_impacts"]["affected_fields"]
        )
        analysis["risk_assessment"]["impact_score"] = total_impacts + len(
            analysis["cascade_impacts"]["affected_fields"]
        )

        # Determine risk level
        impact_score = analysis["risk_assessment"]["impact_score"]
        if impact_score == 0:
            analysis["risk_assessment"]["breaking_change_likelihood"] = "none"
        elif impact_score <= 5:
            analysis["risk_assessment"]["breaking_change_likelihood"] = "low"
        elif impact_score <= 15:
            analysis["risk_assessment"]["breaking_change_likelihood"] = "medium"
        else:
            analysis["risk_assessment"]["breaking_change_likelihood"] = "high"

        # Add user-facing workflow hints
        if analysis["direct_impacts"]["forms"]:
            analysis["risk_assessment"]["affected_user_workflows"].append(
                "User data entry forms"
            )
        if analysis["direct_impacts"]["views"]:
            analysis["risk_assessment"]["affected_user_workflows"].append(
                "Data display views"
            )
        if analysis["direct_impacts"]["connections"]:
            analysis["risk_assessment"]["affected_user_workflows"].append(
                "Related data relationships"
            )

        return analysis

    def _analyze_field_impact(
        self, field_key: str, analysis: dict[str, Any]
    ) -> dict[str, Any]:
        """Analyze impact of changes to a field."""
        obj_info, field_info = self.get_field_info(field_key)
        if not field_info:
            analysis["error"] = f"Field {field_key} not found"
            return analysis

        # Update target info
        analysis["target"]["name"] = f"{obj_info.name}.{field_info.name}"
        analysis["target"]["description"] = f"{field_info.type} field"

        # Get all usages
        usages = self.search_field(field_key)

        scenes_set = set()
        views_set = set()

        for usage in usages:
            if usage.location_type == "connection_field":
                analysis["direct_impacts"]["connections"].append(
                    {
                        "type": "connection",
                        "description": usage.context,
                        "target_object": usage.details.get("target_object"),
                    }
                )
            elif usage.location_type == "field_equation":
                analysis["direct_impacts"]["formulas"].append(
                    {
                        "field_key": usage.details.get("field_key"),
                        "field_name": usage.details.get("field_name"),
                        "object_key": usage.details.get("object_key"),
                        "equation": usage.details.get("equation"),
                    }
                )
            elif "view" in usage.location_type:
                view_key = usage.details.get("view_key")
                scene_key = usage.details.get("scene_key")
                if view_key:
                    views_set.add(view_key)
                if scene_key:
                    scenes_set.add(scene_key)
                analysis["direct_impacts"]["views"].append(
                    {
                        "view_key": view_key,
                        "view_name": usage.details.get("view_name"),
                        "view_type": usage.details.get("view_type"),
                        "scene_key": scene_key,
                        "scene_name": usage.details.get("scene_name"),
                    }
                )
            elif usage.location_type == "form_input":
                analysis["direct_impacts"]["forms"].append(
                    {
                        "view_key": usage.details.get("view_key"),
                        "view_name": usage.details.get("view_name"),
                        "scene_key": usage.details.get("scene_key"),
                    }
                )

        # Populate scene info
        for scene_key in scenes_set:
            for scene in self.app.scenes:
                if scene.key == scene_key:
                    analysis["direct_impacts"]["scenes"].append(
                        {
                            "scene_key": scene_key,
                            "scene_name": scene.name,
                            "scene_slug": scene.slug,
                        }
                    )
                    analysis["cascade_impacts"]["affected_scenes"].append(scene_key)
                    break

        # Calculate impact score
        total_impacts = (
            len(analysis["direct_impacts"]["connections"])
            + len(analysis["direct_impacts"]["views"])
            + len(analysis["direct_impacts"]["formulas"])
            + len(analysis["direct_impacts"]["forms"])
        )

        analysis["metadata"]["total_direct_impacts"] = total_impacts
        analysis["risk_assessment"]["impact_score"] = total_impacts

        # Determine risk level
        if total_impacts == 0:
            analysis["risk_assessment"]["breaking_change_likelihood"] = "none"
        elif total_impacts <= 3:
            analysis["risk_assessment"]["breaking_change_likelihood"] = "low"
        elif total_impacts <= 10:
            analysis["risk_assessment"]["breaking_change_likelihood"] = "medium"
        else:
            analysis["risk_assessment"]["breaking_change_likelihood"] = "high"

        # Add user-facing workflow hints
        if analysis["direct_impacts"]["forms"]:
            analysis["risk_assessment"]["affected_user_workflows"].append(
                "User data entry forms"
            )
        if analysis["direct_impacts"]["views"]:
            analysis["risk_assessment"]["affected_user_workflows"].append(
                "Data display views"
            )
        if analysis["direct_impacts"]["formulas"]:
            analysis["risk_assessment"]["affected_user_workflows"].append(
                "Calculated fields and formulas"
            )

        return analysis

    def generate_app_summary(self) -> dict[str, Any]:
        """
        Generate a comprehensive architectural summary of the entire application.

        This provides universal context for any architectural discussion or change,
        including domain model, relationships, patterns, and extensibility.

        Returns:
            A structured dictionary with complete app architecture summary
        """
        summary = {
            "application": self._analyze_application_metadata(),
            "domain_model": self._analyze_domain_model(),
            "relationship_map": self._analyze_relationship_topology(),
            "data_patterns": self._analyze_data_patterns(),
            "ui_architecture": self._analyze_ui_architecture(),
            "access_patterns": self._analyze_access_patterns(),
            "technical_debt_indicators": self._analyze_technical_debt(),
            "extensibility_assessment": self._analyze_extensibility(),
        }

        return summary

    def _analyze_application_metadata(self) -> dict[str, Any]:
        """Extract basic application metadata and complexity metrics."""
        total_fields = sum(len(obj.fields) for obj in self.app.objects)
        total_views = sum(len(scene.views) for scene in self.app.scenes)
        total_records = self.app.counts.get("total_entries", 0)

        # Calculate connection density
        total_objects = len(self.app.objects)
        actual_connections = sum(
            len(obj.connections.inbound) + len(obj.connections.outbound)
            if obj.connections
            else 0
            for obj in self.app.objects
        )
        possible_connections = total_objects * (total_objects - 1)
        connection_density = (
            actual_connections / possible_connections if possible_connections > 0 else 0
        )

        return {
            "name": self.app.name,
            "id": self.app.id,
            "complexity_metrics": {
                "total_objects": total_objects,
                "total_fields": total_fields,
                "total_scenes": len(self.app.scenes),
                "total_views": total_views,
                "total_records": total_records,
                "connection_density": round(connection_density, 3),
            },
        }

    def _classify_object_roles(self, obj: KnackObject) -> dict[str, bool]:
        """Classify an object into multiple orthogonal categories.
        
        Returns a dict with boolean flags:
        - is_user_profile: User/account/auth object (has profile_key)
        - is_core_entity: Determined dynamically in _analyze_domain_model (set post-hoc)
        - primary_role: One of 'transactional', 'reference', 'supporting'
        
        Primary roles are mutually exclusive:
        - Transactional: medium-high record count with connections
        - Reference: low record count, used by others (inbound >> outbound)
        - Supporting: low record count, low connectivity
        
        Note: is_core_entity is a placeholder here; actual core entity selection
        happens in _analyze_domain_model based on top N by volume/connectivity.
        """
        record_count = self.app.counts.get(obj.key, 0)
        inbound = 0
        outbound = 0
        if obj.connections:
            inbound = len(obj.connections.inbound)
            outbound = len(obj.connections.outbound)
        total_connections = inbound + outbound

        # Check if user profile
        is_user_profile = bool(obj.profile_key)

        # Classify primary role (mutually exclusive)
        primary_role = ""
        if record_count < 100 and inbound > outbound:
            primary_role = "reference"
        elif record_count > 100 and total_connections > 0:
            primary_role = "transactional"
        else:
            primary_role = "supporting"

        return {
            "is_user_profile": is_user_profile,
            "is_core_entity": False,  # Set post-hoc in _analyze_domain_model
            "primary_role": primary_role,
        }

    def _calculate_centrality(self, obj: KnackObject) -> float:
        """Calculate how central/important an object is (0-1 scale)."""
        if not obj.connections:
            return 0.0

        connection_count = len(obj.connections.inbound) + len(
            obj.connections.outbound
        )
        max_connections = len(self.app.objects) - 1

        # Factor in both connections and usage
        connection_score = connection_count / max_connections if max_connections > 0 else 0

        # Count how many views use this object
        view_usage = 0
        for scene in self.app.scenes:
            for view in scene.views:
                if view.source and view.source.object == obj.key:
                    view_usage += 1

        max_views = sum(len(scene.views) for scene in self.app.scenes)
        view_score = view_usage / max_views if max_views > 0 else 0

        # Weighted average (connections more important)
        centrality = (connection_score * 0.7) + (view_score * 0.3)

        return round(centrality, 3)

    def _analyze_domain_model(self) -> dict[str, Any]:
        """Analyze domain model and classify objects into orthogonal categories.
        
        Core entity selection: Top N objects by record count OR connectivity.
        - Maximum: 20% of total objects, capped at 10
        - Minimum: Top 2 (highest volume) + Top 2 (most connected), deduplicated
        - Always exclude user profiles from this calculation
        
        Returns:
            - user_profiles: Objects that represent user/auth entities
            - core_entities: Top N most important by volume or connectivity
            - transactional_entities: Medium-high records with connections (primary role)
            - reference_data: Low record count, used by many (primary role)
            - supporting_entities: Low record count, low connectivity (primary role)
        """
        user_profiles = []
        all_objects_summary = []  # For core entity ranking
        reference_data = []
        transactional = []
        supporting = []

        for obj in self.app.objects:
            record_count = self.app.counts.get(obj.key, 0)
            roles = self._classify_object_roles(obj)
            centrality = self._calculate_centrality(obj)

            # Count field types
            field_types = {}
            for field in obj.fields:
                field_type = field.type
                field_types[field_type] = field_types.get(field_type, 0) + 1

            # Calculate total connections
            total_connections = 0
            if obj.connections:
                total_connections = len(obj.connections.inbound) + len(obj.connections.outbound)

            obj_summary = {
                "object_key": obj.key,
                "name": obj.name,
                "record_count": record_count,
                "field_count": len(obj.fields),
                "centrality_score": centrality,
                "field_types": field_types,
                "total_connections": total_connections,
                "is_core_entity": False,  # Will be set below
                "primary_role": roles["primary_role"],
            }

            # Categorize into primary buckets
            if roles["is_user_profile"]:
                user_profiles.append(obj_summary)
            elif roles["primary_role"] == "reference":
                # Add list of objects that use this reference
                used_by = []
                for other_obj in self.app.objects:
                    if other_obj.connections:
                        for conn in other_obj.connections.outbound:
                            if conn.object == obj.key:
                                used_by.append(other_obj.key)
                obj_summary["used_by"] = used_by
                # Don't add to reference_data yet - will be added in reassignment if not core
            elif roles["primary_role"] == "transactional":
                transactional.append(obj_summary)
            else:  # supporting
                supporting.append(obj_summary)

            # Track for core entity ranking (exclude user profiles)
            if not roles["is_user_profile"]:
                all_objects_summary.append(obj_summary)

        # Determine core entities dynamically:
        # Rank by combined importance (volume + connectivity)
        # Then take top N where N = max(4, 20% of objects) capped at 10
        total_non_user_objects = len(all_objects_summary)
        max_core_entities = min(10, max(4, int(total_non_user_objects * 0.2)))

        # Score each object by combined importance
        # Normalize scores to 0-1 range
        if all_objects_summary:
            max_volume = max(obj["record_count"] for obj in all_objects_summary) or 1
            max_connectivity = max(obj["total_connections"] for obj in all_objects_summary) or 1

            for obj in all_objects_summary:
                volume_score = obj["record_count"] / max_volume
                connectivity_score = obj["total_connections"] / max_connectivity
                # Weighted: 60% volume, 40% connectivity
                obj["importance_score"] = (volume_score * 0.6) + (connectivity_score * 0.4)
        
        # Get top N by importance score
        ranked_objects = sorted(
            all_objects_summary, key=lambda x: x.get("importance_score", 0), reverse=True
        )
        core_entity_keys = {obj["object_key"] for obj in ranked_objects[:max_core_entities]}

        # Mark core entities and separate them
        core_entities = []
        other_objects = []

        for obj_summary in all_objects_summary:
            if obj_summary["object_key"] in core_entity_keys:
                obj_summary["is_core_entity"] = True
                core_entities.append(obj_summary)
            else:
                other_objects.append(obj_summary)

        # Reassign other objects back to their primary buckets
        for obj_summary in other_objects:
            role = obj_summary["primary_role"]
            if role == "reference":
                reference_data.append(obj_summary)
            elif role == "transactional":
                transactional.append(obj_summary)
            else:
                supporting.append(obj_summary)

        # Sort core entities by importance (descending)
        core_entities.sort(key=lambda x: x.get("importance_score", 0), reverse=True)

        return {
            "user_profiles": sorted(
                user_profiles, key=lambda x: x["record_count"], reverse=True
            ),
            "core_entities": core_entities,
            "transactional_entities": sorted(
                transactional, key=lambda x: x["record_count"], reverse=True
            ),
            "reference_data": sorted(
                reference_data, key=lambda x: len(x.get("used_by", [])), reverse=True
            ),
            "supporting_entities": supporting,
        }

    def _analyze_relationship_topology(self) -> dict[str, Any]:
        """Analyze connection graph, clusters, and hub objects."""
        # Build connection graph
        edges = []
        for obj in self.app.objects:
            if obj.connections:
                for conn in obj.connections.outbound:
                    edges.append(
                        {
                            "from": obj.key,
                            "from_name": obj.name,
                            "to": conn.object,
                            "to_name": self.objects_by_key.get(conn.object, type('obj', (), {'name': 'Unknown'})).name,
                            "via": conn.key,
                            "connection_name": conn.name,
                            "type": f"{conn.has}_to_{conn.belongs_to}",
                        }
                    )

        # Calculate hub objects (high connection count)
        hub_objects = []
        for obj in self.app.objects:
            if obj.connections:
                inbound = len(obj.connections.inbound)
                outbound = len(obj.connections.outbound)
                total = inbound + outbound

                if total >= 3:  # Threshold for "hub"
                    hub_objects.append(
                        {
                            "object": obj.name,
                            "object_key": obj.key,
                            "inbound_connections": inbound,
                            "outbound_connections": outbound,
                            "total_connections": total,
                            "interpretation": self._interpret_hub_role(
                                inbound, outbound
                            ),
                        }
                    )

        hub_objects.sort(key=lambda x: x["total_connections"], reverse=True)

        # Identify dependency clusters (simplified - objects with strong interconnections)
        clusters = self._identify_clusters()

        return {
            "connection_graph": {
                "nodes": [obj.key for obj in self.app.objects],
                "edges": edges,
                "total_connections": len(edges),
            },
            "hub_objects": hub_objects,
            "dependency_clusters": clusters,
        }

    def _interpret_hub_role(self, inbound: int, outbound: int) -> str:
        """Interpret what kind of hub an object is based on connection patterns."""
        total = inbound + outbound
        if total == 0:
            return "Isolated"
        elif inbound > outbound * 2:
            return "Central dependency - many objects depend on this"
        elif outbound > inbound * 2:
            return "Aggregator - depends on many objects"
        elif total >= 5:
            return "Core hub - high bidirectional connectivity"
        else:
            return "Moderately connected"

    def _identify_clusters(self) -> list[dict[str, Any]]:
        """Identify groups of highly interconnected objects (simplified clustering)."""
        # Build adjacency map
        adjacency = {obj.key: set() for obj in self.app.objects}

        for obj in self.app.objects:
            if obj.connections:
                for conn in obj.connections.outbound:
                    adjacency[obj.key].add(conn.object)
                for conn in obj.connections.inbound:
                    adjacency[obj.key].add(conn.object)

        # Simple clustering: find objects with shared neighbors
        clusters = []
        processed = set()

        for obj in self.app.objects:
            if obj.key in processed:
                continue

            # Find closely related objects (share 2+ connections)
            cluster_members = {obj.key}
            obj_neighbors = adjacency[obj.key]

            if len(obj_neighbors) >= 2:
                for other_obj in self.app.objects:
                    if other_obj.key == obj.key or other_obj.key in processed:
                        continue

                    other_neighbors = adjacency[other_obj.key]
                    shared = obj_neighbors & other_neighbors

                    # If they share 2+ neighbors or connect to each other, cluster them
                    if len(shared) >= 2 or other_obj.key in obj_neighbors:
                        cluster_members.add(other_obj.key)

            if len(cluster_members) > 1:
                # Count internal vs external connections
                internal = 0
                external = 0

                for member_key in cluster_members:
                    neighbors = adjacency[member_key]
                    for neighbor in neighbors:
                        if neighbor in cluster_members:
                            internal += 1
                        else:
                            external += 1

                # Determine cohesion
                total_conn = internal + external
                cohesion = "low"
                if total_conn > 0:
                    cohesion_ratio = internal / total_conn
                    if cohesion_ratio > 0.7:
                        cohesion = "high"
                    elif cohesion_ratio > 0.4:
                        cohesion = "medium"

                cluster_names = [
                    self.objects_by_key[k].name
                    for k in cluster_members
                    if k in self.objects_by_key
                ]

                clusters.append(
                    {
                        "objects": cluster_names,
                        "object_keys": list(cluster_members),
                        "internal_connections": internal // 2,  # Divide by 2 to avoid double-counting
                        "external_connections": external,
                        "cohesion": cohesion,
                    }
                )

                processed.update(cluster_members)

        return clusters

    def _analyze_data_patterns(self) -> dict[str, Any]:
        """Detect temporal and calculation patterns."""
        # Analyze temporal objects
        temporal_objects = []
        for obj in self.app.objects:
            has_created = any("created" in f.type.lower() for f in obj.fields)
            has_modified = any("modified" in f.type.lower() for f in obj.fields)
            has_status = any("status" in f.name.lower() for f in obj.fields)

            if has_created or has_modified or has_status:
                lifecycle = "stateful_entity" if has_status else "timestamped"
                temporal_objects.append(
                    {
                        "object": obj.name,
                        "object_key": obj.key,
                        "has_created_date": has_created,
                        "has_modified_date": has_modified,
                        "has_status_field": has_status,
                        "lifecycle_pattern": lifecycle,
                    }
                )

        # Calculate formula complexity
        total_formula_fields = 0
        objects_with_formulas = 0
        max_depth = 0

        for obj in self.app.objects:
            has_formula = False
            for field in obj.fields:
                if field.type in ["equation", "concatenation", "count", "sum", "average"]:
                    total_formula_fields += 1
                    has_formula = True
            if has_formula:
                objects_with_formulas += 1

        # Simplified depth calculation (would need recursive analysis for true depth)
        if total_formula_fields > 0:
            max_depth = min(3, total_formula_fields // 5 + 1)

        return {
            "temporal_objects": temporal_objects,
            "calculation_complexity": {
                "total_formula_fields": total_formula_fields,
                "objects_with_formulas": objects_with_formulas,
                "max_formula_chain_depth": max_depth,
                "interpretation": (
                    "High formula dependencies"
                    if total_formula_fields > 30
                    else "Moderate formula dependencies"
                    if total_formula_fields > 10
                    else "Low formula dependencies"
                ),
            },
        }

    def _analyze_ui_architecture(self) -> dict[str, Any]:
        """Analyze scene and view patterns."""
        authenticated_scenes = 0
        public_scenes = 0
        view_type_counts = {}

        for scene in self.app.scenes:
            if scene.authenticated:
                authenticated_scenes += 1
            else:
                public_scenes += 1

            for view in scene.views:
                view_type = view.type
                view_type_counts[view_type] = view_type_counts.get(view_type, 0) + 1

        # Calculate navigation depth
        max_depth = 0
        total_depth = 0
        scene_count = 0

        for scene in self.app.scenes:
            depth = 1
            current = scene
            while current.parent:
                depth += 1
                parent_scene = next(
                    (s for s in self.app.scenes if s.key == current.parent), None
                )
                if not parent_scene:
                    break
                current = parent_scene

            max_depth = max(max_depth, depth)
            total_depth += depth
            scene_count += 1

        avg_depth = total_depth / scene_count if scene_count > 0 else 0

        return {
            "scene_patterns": {
                "authenticated_scenes": authenticated_scenes,
                "public_scenes": public_scenes,
                "total_scenes": len(self.app.scenes),
            },
            "view_patterns": view_type_counts,
            "navigation_depth": {
                "max_depth": max_depth,
                "avg_depth": round(avg_depth, 1),
                "interpretation": (
                    "High complexity"
                    if max_depth > 4
                    else "Moderate complexity"
                    if max_depth > 2
                    else "Simple hierarchy"
                ),
            },
        }

    def _analyze_access_patterns(self) -> dict[str, Any]:
        """Analyze authentication and access control patterns."""
        # User objects are identified by having a profile_key
        user_objects = [obj.name for obj in self.app.objects if obj.profile_key]

        # Analyze role usage
        scenes_with_roles = 0
        for scene in self.app.scenes:
            if scene.groups and len(scene.groups) > 0:
                scenes_with_roles += 1

        return {
            "authentication_model": "user_based" if user_objects else "public",
            "user_objects": user_objects,
            "role_usage": {
                "scenes_with_role_restrictions": scenes_with_roles,
                "interpretation": (
                    "Role-based access control in use"
                    if scenes_with_roles > 0
                    else "No role restrictions detected"
                ),
            },
        }

    def _analyze_technical_debt(self) -> dict[str, Any]:
        """Identify orphaned resources and complexity hotspots."""
        # Find orphaned fields (not used in views, equations, or connections)
        orphaned_fields = 0
        for obj in self.app.objects:
            for field in obj.fields:
                # Check if field is used anywhere
                field_usages = self._find_field_usages(field.key)
                if len(field_usages) == 0:
                    orphaned_fields += 1

        # Find orphaned objects (no connections, no views)
        # Exclude user profiles (objects with profile_key)
        orphaned_objects_count = 0
        orphaned_objects_list = []
        for obj in self.app.objects:
            # Skip user profile objects
            if obj.profile_key:
                continue
            
            if not obj.connections or (
                len(obj.connections.inbound) == 0 and len(obj.connections.outbound) == 0
            ):
                # Check if used in any views
                used_in_views = False
                for scene in self.app.scenes:
                    for view in scene.views:
                        if view.source and view.source.object == obj.key:
                            used_in_views = True
                            break
                    if used_in_views:
                        break

                if not used_in_views:
                    orphaned_objects_count += 1
                    orphaned_objects_list.append({"name": obj.name, "object_key": obj.key})

        # Identify bottleneck objects
        bottlenecks = []
        high_fanout = []

        for obj in self.app.objects:
            if obj.connections:
                inbound = len(obj.connections.inbound)
                outbound = len(obj.connections.outbound)

                if inbound >= 5:
                    bottlenecks.append({"object": obj.name, "object_key": obj.key})
                if outbound >= 5:
                    high_fanout.append({"object": obj.name, "object_key": obj.key})

        return {
            "orphaned_fields": orphaned_fields,
            "orphaned_objects": orphaned_objects_count,
            "orphaned_objects_list": orphaned_objects_list,
            "high_fan_out_objects": high_fanout,
            "bottleneck_objects": bottlenecks,
            "interpretation": (
                "High refactoring risk - multiple bottleneck objects"
                if len(bottlenecks) > 2
                else "Some complexity hotspots"
                if len(bottlenecks) > 0 or len(high_fanout) > 0
                else "Low technical debt"
            ),
        }

    def _analyze_extensibility(self) -> dict[str, Any]:
        """Assess how easy it is to extend or modify the application."""
        # Calculate modularity based on clusters
        clusters = self._identify_clusters()
        total_objects = len(self.app.objects)
        objects_in_clusters = sum(len(c["object_keys"]) for c in clusters)

        modularity_score = (
            objects_in_clusters / total_objects if total_objects > 0 else 0
        )

        # Identify tight coupling
        tight_coupling = []
        for obj in self.app.objects:
            if obj.connections:
                for conn in obj.connections.outbound:
                    target = self.objects_by_key.get(conn.object)
                    if target:
                        # Check if they have many shared connections
                        obj_connections = set(
                            c.object for c in obj.connections.outbound
                        )
                        target_connections = set(
                            c.object
                            for c in target.connections.outbound
                            if target.connections
                        )
                        shared = obj_connections & target_connections

                        if len(shared) >= 3:
                            tight_coupling.append(
                                {
                                    "obj1": obj.name,
                                    "obj1_key": obj.key,
                                    "connection_field": conn.name,  # Field name that creates the coupling
                                    "obj2": target.name,
                                    "obj2_key": target.key,
                                    "shared_connections_count": len(shared),
                                    "coupling": "high",
                                }
                            )

        # Determine architectural style
        hub_count = sum(
            1
            for obj in self.app.objects
            if obj.connections
            and (len(obj.connections.inbound) + len(obj.connections.outbound)) >= 5
        )

        if hub_count > 0 and modularity_score < 0.5:
            arch_style = "hub_and_spoke"
        elif modularity_score > 0.6:
            arch_style = "modular"
        else:
            arch_style = "mixed"

        # Sort by shared connections count (most coupled first)
        tight_coupling.sort(key=lambda x: x["shared_connections_count"], reverse=True)
        
        return {
            "modularity_score": round(modularity_score, 2),
            "tight_coupling_pairs": tight_coupling[:5],  # Top 5 most coupled
            "architectural_style": arch_style,
            "interpretation": (
                "Highly modular - easy to extend"
                if modularity_score > 0.7
                else "Moderately modular - some refactoring may help"
                if modularity_score > 0.4
                else "Low modularity - changes may have wide impact"
            ),
        }
