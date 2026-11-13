"""Report the Builder rules that make a Knack app *do* things.

Knack keeps behaviour in the app metadata, not in any code repo:

- form submits run ``views[].rules`` (``emails``, ``records``, ``submits``,
  ``fields``);
- action links in table and details views run ``action_rules[]``
  (``record_rules``, ``submit_rules``, and email rules where present);
- scheduled tasks run ``objects[].tasks``;
- conditional field rules (``objects[].fields[].rules``) set values on save.

Email rules can carry personal data, so this module never returns an email
body, a sender address, or a custom recipient address in clear. A recipient
taken from a record field is reported by field key and name only.
"""

from collections.abc import Iterator
import re
from typing import Any

from knack_sleuth.models import KnackAppMetadata, Scene, View
from knack_sleuth.sleuth import FIELD_KEY_PATTERN, KnackSleuth

FORM_RULE_LISTS = ("emails", "records", "submits", "fields")
EMAIL_ACTIONS = {"email", "email_notification"}
KNOWN_ACTION_RULE_KEYS = {"key", "criteria", "link_text", "record_rules", "submit_rules"}

# Record-rule actions, as Knack names them, in plain words.
RECORD_ACTIONS = {
    "record": "update this record",
    "connection": "update connected records",
    "insert": "insert a connected record",
}

# Field-value sources a record rule can set a field from.
VALUE_SOURCES = {
    "current_date": "the current date/time",
    "user": "the logged-in user",
}


TAG_PATTERN = re.compile(r"<[^>]+>")


def _plain(text: str) -> str:
    """Builder messages are HTML snippets; keep the words."""
    return " ".join(TAG_PATTERN.sub(" ", text).split())


def _literal(value: Any) -> Any:
    """Connection values are stored as ``[{id, identifier}]``; show identifiers."""
    if isinstance(value, list) and value and all(
        isinstance(item, dict) and "identifier" in item for item in value
    ):
        return ", ".join(str(item["identifier"]) for item in value)
    return value


def _dict(value: Any) -> dict[str, Any]:
    """Metadata is user-edited JSON; treat a wrong-typed container as empty
    instead of crashing (a crash dump could print the raw rule, body and all)."""
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def mask_address(address: Any) -> str:
    """Keep only the domain of a custom address: enough to tell staff from
    applicants, without handing out the mailbox."""
    if not isinstance(address, str) or not address.strip():
        return "(none)"
    _, at, domain = address.strip().rpartition("@")
    return f"***@{domain}" if at and domain else "***"


class _FieldNames:
    def __init__(self, app_export: KnackAppMetadata):
        self.names = {
            field.key: field.name
            for obj in app_export.application.objects
            for field in obj.fields
        }

    def label(self, field_key: Any) -> dict[str, Any]:
        if not isinstance(field_key, str):
            return {"field": None, "field_name": None}
        return {"field": field_key, "field_name": self.names.get(field_key)}


def _criteria(rules: Any, names: _FieldNames) -> list[dict[str, Any]]:
    out = []
    for rule in _list(rules):
        if not isinstance(rule, dict):
            continue
        out.append(
            {
                **names.label(rule.get("field")),
                "operator": rule.get("operator"),
                "value": rule.get("value"),
            }
        )
    return out


def _value(value: dict[str, Any], names: _FieldNames) -> dict[str, Any]:
    """Describe one ``field = value`` assignment of a record rule."""
    source = value.get("type")
    if source == "value":
        literal = value.get("value")
        set_to = "(blank)" if _is_blank(literal) else _literal(literal)
    elif source == "record":
        input_key = value.get("input")
        input_name = names.names.get(input_key) if isinstance(input_key, str) else None
        set_to = f"value of {input_key}" + (f" ({input_name})" if input_name else "")
    elif source == "connection":
        set_to = f"value via connection {value.get('connection_field') or value.get('input')}"
    else:
        # str(): a wrong-typed `type` (e.g. a list) must not crash the lookup.
        set_to = VALUE_SOURCES.get(str(source), str(source))
    entry = {**names.label(value.get("field")), "source": source, "set_to": set_to}
    if value.get("action"):
        # e.g. "append" adds to a connection field instead of replacing it.
        entry["mode"] = value["action"]
    return entry


def _email(rule: dict[str, Any], names: _FieldNames) -> dict[str, Any]:
    email = _dict(rule.get("email"))
    recipients = []
    listed = _list(email.get("recipients"))
    if not listed and email.get("recipient_type"):
        # Older rules keep a single recipient on the email itself.
        listed = [email]
    for recipient in listed or []:
        if not isinstance(recipient, dict):
            continue
        kind = recipient.get("recipient_type")
        entry: dict[str, Any] = {"mode": recipient.get("recipient_mode"), "type": kind}
        if kind == "custom":
            entry["address"] = mask_address(recipient.get("email"))
        else:
            # The `email` string is populated even for field recipients; it is
            # a leftover, not who receives the message, so it is never shown.
            entry.update(names.label(recipient.get("field")))
            if recipient.get("connection"):
                entry["connection"] = recipient["connection"]
        recipients.append(entry)
    return {
        "key": rule.get("key"),
        "action": rule.get("action"),
        "subject": email.get("subject") if isinstance(email.get("subject"), str) else None,
        "recipients": recipients,
        "criteria": _criteria(rule.get("criteria"), names),
        "has_body": bool(email.get("message")),
    }


def _record(rule: dict[str, Any], names: _FieldNames) -> dict[str, Any]:
    action = rule.get("action")
    return {
        "key": rule.get("key"),
        "action": action,
        "description": RECORD_ACTIONS.get(str(action), str(action)),
        "connection": rule.get("connection") if action != "record" else None,
        "values": [
            _value(value, names)
            for value in _list(rule.get("values"))
            if isinstance(value, dict)
        ],
        "criteria": _criteria(rule.get("criteria"), names),
    }


def _submit(rule: dict[str, Any], names: _FieldNames) -> dict[str, Any]:
    action = rule.get("action")
    entry: dict[str, Any] = {
        "key": rule.get("key"),
        "action": action,
        "criteria": _criteria(rule.get("criteria"), names),
    }
    if rule.get("message"):
        entry["message"] = _plain(str(rule["message"]))
    if action in ("existing_page", "child_page"):
        entry["target_page"] = rule.get("existing_page") or rule.get("scene")
    if action == "url" and rule.get("url"):
        # Other actions keep a stale `url` from an earlier setting; only a
        # "url" action redirects there.
        entry["url"] = rule["url"]
    return entry


def _display(rule: dict[str, Any], names: _FieldNames) -> dict[str, Any]:
    return {
        "key": rule.get("key"),
        "actions": [
            {"action": action.get("action"), **names.label(action.get("field"))}
            for action in _list(rule.get("actions"))
            if isinstance(action, dict)
        ],
        "criteria": _criteria(rule.get("criteria"), names),
    }


def _split_email_rules(
    rules: list[Any], names: _FieldNames, all_email: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate email rules from record rules by content, not list name.

    A false "no email" is the expensive mistake, so anything that looks like
    an email is reported as one wherever it sits.
    """
    emails, records = [], []
    for rule in _list(rules):
        if not isinstance(rule, dict):
            continue
        action = rule.get("action")
        if (
            all_email
            or action in EMAIL_ACTIONS
            # Unknown action: an email payload with content decides it. An
            # explicit record action with an empty `email: {}` stays a record.
            or (action not in RECORD_ACTIONS and _dict(rule.get("email")))
        ):
            emails.append(_email(rule, names))
        else:
            records.append(_record(rule, names))
    return emails, records


def _email_field_refs(email: dict[str, Any]) -> set[str]:
    refs = {r["field"] for r in email["recipients"] if r.get("field")}
    refs |= {c["field"] for c in email["criteria"] if c.get("field")}
    return refs


def _blanking_warnings(
    emails: list[dict[str, Any]],
    records: list[dict[str, Any]],
    body_refs: dict[Any, set[str]],
) -> list[str]:
    """Email rules run after record rules, so an email that reads a field a
    record rule on the same trigger blanks will go out without it."""
    blanked = {
        value["field"]: record["key"]
        for record in records
        if record["action"] == "record"
        for value in record["values"]
        if value["field"] and value["source"] == "value" and value["set_to"] == "(blank)"
    }
    warnings = []
    for email in emails:
        refs = _email_field_refs(email) | body_refs.get(email["key"], set())
        if isinstance(email.get("subject"), str):
            refs |= set(FIELD_KEY_PATTERN.findall(email["subject"]))
        for field_key in sorted(refs & blanked.keys()):
            warnings.append(
                f"email rule {email['key']} uses {field_key}, which record rule "
                f"{blanked[field_key]} blanks first (email rules run after record rules)"
            )
    return warnings


def _body_field_refs(rules: list[Any]) -> dict[Any, set[str]]:
    """Field keys each email body mentions, without returning the body."""
    refs: dict[Any, set[str]] = {}
    for rule in _list(rules):
        # Email and record rules number their keys independently ("1", "2"...),
        # so only email-bearing rules may contribute or a record rule with the
        # same key would wipe the email's references.
        if isinstance(rule, dict) and isinstance(rule.get("email"), dict):
            message = rule["email"].get("message")
            if not isinstance(message, str):
                message = ""
            refs.setdefault(rule.get("key"), set()).update(
                FIELD_KEY_PATTERN.findall(message)
            )
    return refs


def _iter_action_links(value: Any) -> Iterator[dict[str, Any]]:
    """Yield every action-link column in a view.

    Tables keep them in ``columns[]``; details views nest them in
    ``columns[].groups[].columns[][]``. Walking finds both, and any layout
    Knack adds later.
    """
    if isinstance(value, dict):
        if value.get("type") == "action_link":
            yield value
            return
        for nested in value.values():
            yield from _iter_action_links(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_action_links(nested)


def _view_header(
    scene: Scene, view: View, orphaned: set[str]
) -> dict[str, Any]:
    reachable = view.key not in orphaned
    header = {
        "scene_key": scene.key,
        "scene_name": scene.name,
        "scene_slug": scene.slug,
        "view_key": view.key,
        "view_name": view.name,
        "view_type": view.type,
        "source_object": view.source.object if view.source else None,
        "reachable": reachable,
    }
    if not reachable:
        header["unreachable_reason"] = (
            "orphaned view: on the scene but not in its page layout, so it never renders"
        )
    return header


def _form_trigger(
    header: dict[str, Any], view_data: dict[str, Any], names: _FieldNames
) -> dict[str, Any] | None:
    rules = view_data.get("rules")
    if not isinstance(rules, dict):
        return None
    # Details and list views carry `rules.fields` too, but those are display
    # formatting, not anything a submit fires; only forms count on `fields` alone.
    has_submit_rules = any(k in rules for k in FORM_RULE_LISTS[:3])
    if not has_submit_rules and not (view_data.get("type") == "form" and _list(rules.get("fields"))):
        return None
    raw_emails = _list(rules.get("emails"))
    emails, _ = _split_email_rules(raw_emails, names, all_email=True)
    more_emails, records = _split_email_rules(_list(rules.get("records")), names)
    emails += more_emails
    submits = [_submit(r, names) for r in _list(rules.get("submits")) if isinstance(r, dict)]
    display = [_display(r, names) for r in _list(rules.get("fields")) if isinstance(r, dict)]
    return {
        "trigger": "form_submit",
        **header,
        "form_action": view_data.get("action"),
        "emails": emails,
        "records": records,
        "submits": submits,
        "display_rules": display,
        "warnings": _blanking_warnings(
            emails, records, _body_field_refs(raw_emails + _list(rules.get("records")))
        ),
    }


def _action_link_trigger(
    header: dict[str, Any], column: dict[str, Any], names: _FieldNames
) -> dict[str, Any]:
    action_rules = []
    for action_rule in _list(column.get("action_rules")):
        if not isinstance(action_rule, dict):
            continue
        raw_records = list(_list(action_rule.get("record_rules")))
        # The action-link email key is not pinned down (no sample has one), so
        # take any "email" key: a list of rules or a single rule dict. Anything
        # else is surfaced below rather than read as "no email".
        raw_emails: list[Any] = []
        odd_email_keys = []
        for key, value in action_rule.items():
            if "email" not in key:
                continue
            if isinstance(value, list):
                raw_emails += value
            elif isinstance(value, dict):
                raw_emails.append(value)
            elif value not in (None, "", False):
                odd_email_keys.append(key)
        emails, records = _split_email_rules(raw_records, names)
        emails += _split_email_rules(raw_emails, names, all_email=True)[0]
        unrecognised = sorted(
            [
                key
                for key in action_rule
                if key not in KNOWN_ACTION_RULE_KEYS and "email" not in key
            ]
            + odd_email_keys
        )
        entry = {
            "key": action_rule.get("key"),
            "link_text": action_rule.get("link_text"),
            "criteria": _criteria(action_rule.get("criteria"), names),
            "emails": emails,
            "records": records,
            "submits": [
                _submit(r, names)
                for r in _list(action_rule.get("submit_rules"))
                if isinstance(r, dict)
            ],
            "warnings": _blanking_warnings(
                emails, records, _body_field_refs(raw_records + raw_emails)
            ),
        }
        if unrecognised:
            entry["unrecognised_keys"] = unrecognised
        action_rules.append(entry)
    return {
        "trigger": "action_link",
        **header,
        "link_text": column.get("link_text") or column.get("header"),
        "action_rules": action_rules,
    }


def _task(task: dict[str, Any], names: _FieldNames) -> dict[str, Any]:
    action = _dict(task.get("action"))
    entry: dict[str, Any] = {
        "trigger": "task",
        "key": task.get("key"),
        "name": task.get("name"),
        "type": task.get("type"),
        "run_status": task.get("run_status"),
        "scheduled": task.get("scheduled"),
        "schedule": _dict(task.get("schedule")),
        "action": action.get("action"),
        "criteria": _criteria(action.get("criteria"), names),
    }
    emails, records = _split_email_rules([action], names) if action else ([], [])
    entry["emails"] = emails
    entry["records"] = records
    return entry


def collect_rules(
    app_export: KnackAppMetadata,
    object_key: str | None = None,
    view_key: str | None = None,
) -> dict[str, Any]:
    """Collect the behaviour rules for an object, a view, or both.

    With ``object_key``: every view sourced on that object that carries form
    rules or action links, plus the object's scheduled tasks. With
    ``view_key``: only that view (and no tasks unless an object is given).
    """
    names = _FieldNames(app_export)
    orphaned = KnackSleuth(app_export).orphaned_view_keys
    triggers: list[dict[str, Any]] = []
    quiet_views: list[dict[str, Any]] = []
    for scene in app_export.application.scenes:
        for view in scene.views:
            if view_key and view.key != view_key:
                continue
            source = view.source.object if view.source else None
            if object_key and not view_key and source != object_key:
                continue
            header = _view_header(scene, view, orphaned)
            view_data = view.model_dump(mode="python")
            found = len(triggers)
            form = _form_trigger(header, view_data, names)
            if form:
                triggers.append(form)
            for column in _iter_action_links(view_data):
                triggers.append(_action_link_trigger(header, column, names))
            if len(triggers) == found:
                # Listed so "no rules here" is visible, not inferred from silence.
                quiet_views.append(
                    {k: header[k] for k in ("scene_key", "view_key", "view_name", "view_type", "reachable")}
                )

    connected: list[dict[str, Any]] = []
    if object_key and not view_key:
        connected = _connected_record_rules(triggers, app_export, object_key, names, orphaned)

    tasks = []
    field_rules: list[dict[str, Any]] = []
    if object_key:
        for obj in app_export.application.objects:
            if obj.key != object_key:
                continue
            tasks = [_task(t, names) for t in obj.tasks if isinstance(t, dict)]
            # Conditional field rules set a value whenever a record is saved,
            # whichever form, link, import or API call saved it.
            for field in obj.fields:
                rules = [
                    {
                        "key": rule.get("key"),
                        "values": [
                            _value(v, names) for v in _list(rule.get("values")) if isinstance(v, dict)
                        ],
                        "criteria": _criteria(rule.get("criteria"), names),
                    }
                    for rule in _list(field.rules)
                    if isinstance(rule, dict)
                ]
                if rules:
                    field_rules.append({**names.label(field.key), "rules": rules})

    return {
        "triggers": triggers,
        "views_without_rules": quiet_views,
        "connected_record_rules": connected,
        "conditional_field_rules": field_rules,
        "tasks": tasks,
    }


def _targets_object(record: dict[str, Any], object_key: str) -> bool:
    connection = record.get("connection") or ""
    return record["action"] != "record" and connection.split(".", 1)[0] == object_key


def _connected_record_rules(
    own_triggers: list[dict[str, Any]],
    app_export: KnackAppMetadata,
    object_key: str,
    names: _FieldNames,
    orphaned: set[str],
) -> list[dict[str, Any]]:
    """Record rules on *other* objects' views that change this object.

    A form or action link on a parent record can update or insert this
    object's records through a connection (``connection: object_N.field_M``),
    so "what can change this status?" is not answered by this object's own
    views alone.
    """
    own_views = {t["view_key"] for t in own_triggers}
    out = []
    for scene in app_export.application.scenes:
        for view in scene.views:
            if view.key in own_views:
                continue
            header = _view_header(scene, view, orphaned)
            view_data = view.model_dump(mode="python")
            # Each candidate keeps the trigger it belongs to: the conditions on
            # the action link, and the emails the same click or submit sends.
            candidates = []
            form = _form_trigger(header, view_data, names)
            if form:
                candidates.append(("form_submit", None, [], form))
            for column in _iter_action_links(view_data):
                link = _action_link_trigger(header, column, names)
                for action_rule in link["action_rules"]:
                    candidates.append(
                        ("action_link", action_rule["link_text"], action_rule["criteria"], action_rule)
                    )
            for trigger, link_text, conditions, rules in candidates:
                for record in rules["records"]:
                    if not _targets_object(record, object_key):
                        continue
                    entry = {
                        "trigger": trigger,
                        **header,
                        "record_rule": record,
                        "trigger_criteria": conditions,
                        "emails_on_same_trigger": rules["emails"],
                    }
                    if link_text is not None:
                        entry["link_text"] = link_text
                    out.append(entry)
    return out
