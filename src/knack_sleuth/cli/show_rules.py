"""show-rules: what an object's forms, action links and scheduled tasks DO."""

import json
from typing import Annotated

import typer
from rich.markup import escape
from rich.panel import Panel

from knack_sleuth.rules import collect_rules

from ._common import (
    cli,
    console,
    fail,
    load_app_metadata,
    resolve_object_or_exit,
    validate_output_format,
)
from ._options import AppId, MetadataFile, Refresh, RichOrJson

BREADCRUMB = "\u203a"  # single right-pointing angle quotation mark


def _fmt_field(entry: dict) -> str:
    name = entry.get("field_name")
    key = entry.get("field") or "?"
    return f"{key} ({name})" if name else str(key)


def _fmt_criteria(criteria: list) -> str:
    if not criteria:
        return ""
    parts = [
        f"{_fmt_field(c)} {c.get('operator')} {c['range']}"
        if c.get("range")
        else f"{_fmt_field(c)} {c.get('operator')} {c.get('value')!r}"
        if c.get("value") not in (None, "", [])
        else f"{_fmt_field(c)} {c.get('operator')}"
        for c in criteria
    ]
    return " [dim]when " + escape(" and ".join(parts)) + "[/dim]"


def _print_emails(emails: list, indent: str) -> None:
    for email in emails:
        recipients = (
            ", ".join(
                f"{r.get('mode')}: "
                + (
                    r["address"]
                    if r.get("type") == "custom"
                    else f"{r.get('type')} {_fmt_field(r)}"
                )
                for r in email["recipients"]
            )
            or "no recipients"
        )
        # A notification has no subject of its own; Knack sends a stock message.
        subject = (
            "notification"
            if email.get("action") == "email_notification" and not email.get("subject")
            else repr(email.get("subject") or "")
        )
        console.print(
            f"{indent}[magenta]Email[/magenta] {escape(subject)} "
            f"→ {escape(recipients)}{_fmt_criteria(email['criteria'])}"
        )


def _print_records(records: list, indent: str) -> None:
    for record in records:
        values = (
            "; ".join(
                f"{_fmt_field(v)} = {v['set_to']}"
                + (f" ({v['mode']})" if v.get("mode") else "")
                for v in record["values"]
            )
            or "no values"
        )
        target = f" via {record['connection']}" if record.get("connection") else ""
        console.print(
            f"{indent}[cyan]Record[/cyan] {escape(str(record['description']))}{escape(target)}: "
            f"{escape(values)}{_fmt_criteria(record['criteria'])}"
        )


def _print_submits(submits: list, indent: str) -> None:
    for submit in submits:
        detail = (
            submit.get("target_page")
            or submit.get("url")
            or submit.get("message")
            or ""
        )
        console.print(
            f"{indent}[blue]Submit[/blue] {escape(str(submit.get('action')))}"
            f"{': ' + escape(repr(detail)) if detail else ''}{_fmt_criteria(submit['criteria'])}"
        )


def _print_rule_lists(item: dict, indent: str, note_no_email: bool = True) -> None:
    """Print the email/record/submit rules shared by every trigger kind.

    "Email rules: none" is printed on purpose: the question this answers is
    usually "does this send anything?", and silence reads as "not checked".
    """
    emails = item.get("emails", [])
    if not emails and note_no_email:
        console.print(f"{indent}[green]Email rules: none[/green]")
    _print_emails(emails, indent)
    _print_records(item.get("records", []), indent)
    _print_submits(item.get("submits", []), indent)
    for warning in item.get("warnings", []):
        console.print(f"{indent}[yellow]⚠ {escape(warning)}[/yellow]")
    if item.get("unrecognised_keys"):
        console.print(
            f"{indent}[yellow]⚠ rule keys knack-sleuth does not interpret (check them in the Builder): "
            f"{escape(', '.join(item['unrecognised_keys']))}[/yellow]"
        )


def _print_view_heading(trigger: dict, label: str) -> None:
    where = escape(
        f"{trigger['scene_name']} ({trigger['scene_key']}) {BREADCRUMB} "
        f"{trigger['view_name']} ({trigger['view_key']}, {trigger['view_type']})"
    )
    flag = (
        ""
        if trigger["reachable"]
        else " [red]UNREACHABLE: orphaned view, never renders[/red]"
    )
    console.print(f"\n[bold]{label}[/bold] {where}{flag}")


def _link_label(entry: dict) -> str:
    return f"Action link {escape(repr(entry.get('link_text') or ''))}:"


def _inline_edit_label(entry: dict) -> str:
    label = f"Inline edit of {escape(_fmt_field(entry['edited_field']))}:"
    if not entry.get("active", True):
        label += f" [yellow]INACTIVE: {escape(entry['inactive_reason'])}[/yellow]"
    return label


def _print_trigger(trigger: dict) -> None:
    if trigger["trigger"] == "inline_edit":
        _print_view_heading(trigger, _inline_edit_label(trigger))
        _print_rule_lists(trigger, "  ")
        return
    if trigger["trigger"] != "form_submit":
        _print_view_heading(trigger, _link_label(trigger))
        for action_rule in trigger["action_rules"]:
            console.print(
                f"  Rule {escape(str(action_rule.get('key')))}"
                f"{_fmt_criteria(action_rule['criteria'])}"
            )
            _print_rule_lists(action_rule, "    ")
        return

    action = (
        f" — form {escape(str(trigger['form_action']))}"
        if trigger.get("form_action")
        else ""
    )
    _print_view_heading(trigger, f"Form submit{action}:")
    _print_rule_lists(trigger, "  ")
    if trigger["display_rules"]:
        console.print(
            f"  [dim]{len(trigger['display_rules'])} display rule(s) "
            "(show/hide inputs; see --format json)[/dim]"
        )


def _print_connected(connected: list) -> None:
    if not connected:
        return
    console.print(
        "\n[bold cyan]Changed from other objects' views (via connection):[/bold cyan]"
    )
    for entry in connected:
        if entry["trigger"] == "action_link":
            label = _link_label(entry)
        elif entry["trigger"] == "inline_edit":
            label = _inline_edit_label(entry)
        else:
            label = "Form submit:"
        _print_view_heading(entry, label + _fmt_criteria(entry["trigger_criteria"]))
        _print_rule_lists(
            {
                "records": [entry["record_rule"]],
                "emails": entry["emails_on_same_trigger"],
            },
            "  ",
            note_no_email=False,
        )


def _page_rule_line(rule: dict) -> str:
    action = rule.get("action")
    if action == "hide_views":
        hidden = ", ".join(
            f"{v['view_key']} ({v['view_name']})"
            if v.get("view_name")
            else v["view_key"]
            for v in rule["hides"]
        )
        return f"[yellow]Hide[/yellow] {escape(hidden or 'no views')}"
    if rule.get("target_page"):
        return f"[blue]Redirect[/blue] to page {escape(repr(rule['target_page']))}"
    if rule.get("url"):
        return f"[blue]Redirect[/blue] to {escape(repr(rule['url']))}"
    if action == "message":
        return f"[blue]Message[/blue] {escape(repr(rule.get('message') or ''))}"
    return f"[blue]{escape(str(action))}[/blue]"


def _print_page_rules(pages: list) -> None:
    if not pages:
        return
    console.print(
        "\n[bold cyan]Page rules[/bold cyan] "
        "[dim](run when the page loads; they can hide a view or redirect away):[/dim]"
    )
    for page in pages:
        console.print(
            f"  [bold]{escape(str(page['scene_name']))}[/bold] "
            f"({escape(str(page['scene_key']))})"
        )
        other_hides = 0
        for rule in page["rules"]:
            if rule.get("hides_selected_view") is False:
                other_hides += 1
                continue
            console.print(
                f"    {_page_rule_line(rule)}{_fmt_criteria(rule['criteria'])}"
            )
        if other_hides:
            console.print(
                f"    [dim]{other_hides} rule(s) hiding other views on this page "
                "(see --format json)[/dim]"
            )


def _print_field_rules(field_rules: list) -> None:
    if not field_rules:
        return
    console.print(
        "\n[bold cyan]Conditional field rules[/bold cyan] "
        "[dim](applied whenever a record is saved, by any form, link, import or API call):[/dim]"
    )
    for entry in field_rules:
        for rule in entry["rules"]:
            values = "; ".join(
                f"{_fmt_field(v)} = {v['set_to']}" for v in rule["values"]
            )
            console.print(f"  {escape(values)}{_fmt_criteria(rule['criteria'])}")


def _print_tasks(tasks: list) -> None:
    console.print("\n[bold cyan]Scheduled tasks:[/bold cyan]")
    if not tasks:
        console.print("  [dim]none[/dim]")
    for task in tasks:
        schedule = task.get("schedule") or {}
        status_color = "green" if task.get("run_status") == "running" else "yellow"
        console.print(
            f"\n  [bold]{escape(str(task.get('name')))}[/bold] ({escape(str(task.get('key')))}) — "
            f"{escape(str(task.get('action')))}, {escape(str(schedule.get('repeat')))} "
            f"at {escape(str(schedule.get('time')))}, status: "
            f"[{status_color}]{escape(str(task.get('run_status')))}[/]"
        )
        _print_rule_lists(task, "    ", note_no_email=False)


def _print_report(report: dict, title: str, show_tasks: bool) -> None:
    console.print(
        Panel(f"[bold cyan]{escape(title)}[/bold cyan]", title="Builder Rules")
    )

    if not report["triggers"]:
        console.print("\n[dim]No forms or action links with rules found.[/dim]")
    for trigger in report["triggers"]:
        _print_trigger(trigger)

    quiet = report["views_without_rules"]
    if quiet:
        console.print(
            f"\n[dim]{len(quiet)} other view(s) on this object have no form rules or action links: "
            + escape(", ".join(v["view_key"] for v in quiet))
            + "[/dim]"
        )

    _print_page_rules(report["page_rules"])
    _print_connected(report["connected_record_rules"])
    _print_field_rules(report["conditional_field_rules"])
    if show_tasks:
        _print_tasks(report["tasks"])
    console.print()


@cli.command(name="show-rules")
def show_rules(
    file_path: MetadataFile = None,
    object_identifier: Annotated[
        str | None,
        typer.Option("--object", help="Object key (e.g., 'object_12') or name"),
    ] = None,
    view_key: Annotated[
        str | None,
        typer.Option("--view", help="Limit to one view (e.g., 'view_123')"),
    ] = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    output_format: RichOrJson = "rich",
):
    """
    Show what an object's forms, action links and scheduled tasks DO.

    Knack Builder rules (emails, record updates, redirects) live in the app
    metadata, not in any code repo. For an object this lists every view
    sourced on it that has form rules or action links, with:

      - email rules: subject, recipients (record fields by key/name; custom
        addresses masked to their domain) and conditions — never the body;
      - record rules: field = value, and connected-record updates/inserts;
      - submit rules: message, redirect or child page;

    plus record rules on OTHER objects' views that change this object through a
    connection, conditional field rules (applied on every save), and the
    object's scheduled tasks (with run status).

    Views left out of their page layout are flagged unreachable: their rules
    never fire.


    Examples:

        knack-sleuth show-rules my_app.json --object Applicant

        knack-sleuth show-rules --app-id YOUR_APP_ID --object object_12 --format json

        knack-sleuth show-rules my_app.json --view view_123
    """
    validate_output_format(output_format)
    if not object_identifier and not view_key:
        fail("Pass --object, --view, or both.")

    app_export = load_app_metadata(file_path, app_id, refresh)

    target = (
        resolve_object_or_exit(app_export, object_identifier)
        if object_identifier
        else None
    )
    if view_key and not any(
        view.key == view_key
        for scene in app_export.application.scenes
        for view in scene.views
    ):
        fail(f"View '{view_key}' not found in application")

    try:
        report = collect_rules(app_export, target.key if target else None, view_key)
    except Exception as exc:
        fail(
            f"could not interpret this app's rules ({type(exc).__name__}). "
            "Please report it at https://github.com/mcmasty/knack-sleuth/issues"
        )

    if output_format == "json":
        payload = {
            "object": {"key": target.key, "name": target.name} if target else None,
            "view": view_key,
            **report,
        }
        typer.echo(json.dumps(payload, indent=2, default=str))
        return

    title = f"{target.name} ({target.key})" if target else str(view_key)
    _print_report(report, title, show_tasks=target is not None)
