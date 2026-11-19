"""Argument and option types shared by many commands."""

from pathlib import Path
from typing import Annotated

import typer

MetadataFile = Annotated[
    Path | None,
    typer.Argument(
        help="Path to Knack application metadata JSON file (optional if using --app-id)",
    ),
]
AppId = Annotated[
    str | None,
    typer.Option(
        "--app-id",
        help="Knack application ID (can also use KNACK_APP_ID env var)",
    ),
]
Refresh = Annotated[
    bool,
    typer.Option("--refresh", help="Force refresh cached API data (ignore cache)"),
]
IncludeSystemConnections = Annotated[
    bool,
    typer.Option(
        "--include-system-connections",
        help=(
            "Count Knack's own audit connections (Created By, Updated By, Owned By) "
            "as relationships. They are left out by default."
        ),
    ),
]
RichOrJson = Annotated[
    str, typer.Option("--format", help="Output format: rich or json")
]
ReportFormat = Annotated[
    str, typer.Option("--format", help="Output format: json, yaml, or markdown")
]
ReportOutput = Annotated[
    Path | None,
    typer.Option("--output", "-o", help="Save output to file instead of stdout"),
]

# export-db-schema and export-schema-subgraph
SchemaFile = Annotated[
    Path | None, typer.Argument(help="Path to Knack app export JSON file")
]
SchemaAppId = Annotated[
    str | None, typer.Option("--app-id", help="Knack app ID (alternative to file)")
]
SchemaOutput = Annotated[
    Path | None, typer.Option("--output", "-o", help="Output file path")
]
SchemaFormat = Annotated[
    str,
    typer.Option("--format", "-f", help="Output format: json, dbml, yaml, or mermaid"),
]
SchemaDetail = Annotated[
    str,
    typer.Option(
        "--detail",
        "-d",
        help="Detail level: structural, minimal, compact, or standard",
    ),
]
