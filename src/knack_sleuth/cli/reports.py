"""Structured reports for humans and agents: impact-analysis and app-summary."""

import json
from collections.abc import Callable, Mapping
from typing import Annotated, Any

import typer
import yaml
from rich.markup import escape

from knack_sleuth.lookup import (
    resolve_fields,
    resolve_object,
    suggest_field_names,
    suggest_object_names,
)
from knack_sleuth.models import Application
from knack_sleuth.sleuth import KnackSleuth

from ._common import (
    cli,
    console,
    emit,
    err_console,
    exit_ambiguous_field,
    fail,
    load_app_metadata,
    print_suggestions,
    scene_url,
)
from ._markdown import app_summary_markdown, impact_markdown
from ._options import (
    AppId,
    IncludeSystemConnections,
    MetadataFile,
    Refresh,
    ReportFormat,
    ReportOutput,
)

REPORT_FORMATS = ("json", "yaml", "markdown")


def _validate_report_format(output_format: str) -> None:
    if output_format not in REPORT_FORMATS:
        fail(f"Unknown format '{output_format}'")


def _render(
    data: Mapping[str, Any], output_format: str, markdown: Callable[[], str]
) -> str:
    if output_format == "json":
        return json.dumps(data, indent=2)
    if output_format == "yaml":
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
    return markdown()


# --- impact-analysis ------------------------------------------------------------


def _resolve_target(app: Application, identifier: str) -> tuple[str, str]:
    """(key, "object" | "field") for an identifier, or exit with suggestions.

    Keys are taken as given; names try objects first, then fields.
    """
    lowered = identifier.lower()
    if lowered.startswith("object_"):
        return identifier, "object"
    if lowered.startswith("field_"):
        return identifier, "field"

    matched_object = resolve_object(app, identifier)
    if matched_object:
        return matched_object.key, "object"

    field_matches = resolve_fields(app, identifier)
    if len(field_matches) > 1:
        exit_ambiguous_field(identifier, field_matches)
    if field_matches:
        return field_matches[0][1].key, "field"

    err_console.print(
        f"[red]Error:[/red] Could not find object or field '{escape(identifier)}'"
    )
    print_suggestions(
        suggest_object_names(app, identifier) or suggest_field_names(app, identifier)
    )
    raise typer.Exit(1)


@cli.command(name="impact-analysis")
def impact_analysis(
    target_identifier: Annotated[
        str,
        typer.Argument(
            help="Object or field key/name to analyze (e.g., 'object_12' or 'field_116')",
        ),
    ],
    file_path: MetadataFile = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    output_format: ReportFormat = "json",
    output_file: ReportOutput = None,
):
    """
    [EXPERIMENTAL] Generate a comprehensive impact analysis for human and AI/agent consumption.

    This command analyzes how changing a specific object or field would impact
    your Knack application, providing structured output suitable for:


    Use cases:

    - AI agents planning database changes

    - Human-readable markdown reports (--format markdown)

    - Impact assessment documentation

    - Change risk analysis

    - Migration planning


    The output includes:

    - Direct impacts (connections, views, forms, formulas)

    - Cascade impacts (affected fields, scenes)

    - Risk assessment (likelihood, impact score)

    - Affected user workflows


    Output formats:

    - JSON: Structured for AI/agent processing

    - Markdown: Human-friendly documentation (--format markdown)

    - YAML: Alternative structured format


    Examples:

        knack-sleuth impact-analysis object_12 --format json

        knack-sleuth impact-analysis field_116 --app-id YOUR_APP_ID --output impact.json

        knack-sleuth impact-analysis "Organization" my_app.json --format markdown
    """
    _validate_report_format(output_format)
    app_export = load_app_metadata(file_path, app_id, refresh)
    target_key, target_type = _resolve_target(app_export.application, target_identifier)

    analysis = KnackSleuth(app_export).generate_impact_analysis(target_key, target_type)
    if "error" in analysis:
        fail(analysis["error"])

    content = _render(
        analysis,
        output_format,
        lambda: impact_markdown(analysis, lambda key: scene_url(app_export, key)),
    )
    emit(content, output_file, "Analysis")


# --- app-summary ----------------------------------------------------------------


@cli.command(name="app-summary")
def app_summary(
    file_path: MetadataFile = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    output_format: ReportFormat = "json",
    output_file: ReportOutput = None,
    include_system_connections: IncludeSystemConnections = False,
):
    """
    [EXPERIMENTAL] Generate a comprehensive architectural summary for human and AI/agent consumption.

    This command provides universal context for ANY architectural discussion,
    including domain model, relationships, patterns, and extensibility.


    Perfect for:

    - Understanding overall app architecture

    - Planning major refactorings

    - AI-assisted architecture discussions

    - Human-readable documentation (--format markdown)

    - Complexity assessment


    The output includes:

    - Domain model classification (user profiles, core, transactional, reference objects)

    - Relationship topology (connections, clusters, hubs)

    - Data patterns (temporal, calculations)

    - UI architecture (scenes, views, navigation)

    - Access patterns (authentication, roles)

    - Technical debt indicators (orphaned resources, bottlenecks)

    - Extensibility assessment (modularity, coupling)


    Output formats:

    - JSON: Structured for AI/agent processing (default)

    - Markdown: Human-friendly documentation (--format markdown)

    - YAML: Alternative structured format


    Examples:

        knack-sleuth app-summary my_app.json

        knack-sleuth app-summary --app-id YOUR_APP_ID --format markdown

        knack-sleuth app-summary --app-id YOUR_APP_ID --output summary.json
    """
    _validate_report_format(output_format)
    app_export = load_app_metadata(file_path, app_id, refresh)

    with console.status("[cyan]Analyzing application architecture..."):
        summary = KnackSleuth(app_export).generate_app_summary(
            include_system_connections=include_system_connections
        )

    content = _render(summary, output_format, lambda: app_summary_markdown(summary))
    emit(content, output_file, "Summary")
