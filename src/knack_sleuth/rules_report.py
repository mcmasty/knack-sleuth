"""The shape of the report ``collect_rules`` returns.

These are TypedDicts: plain dicts at run time (the report is dumped straight
to JSON), with their keys and value types visible to the type checker, so a
renderer that reads a key no builder writes fails the check instead of
printing ``None``.

A key marked ``NotRequired`` is only present when it has something to say.
"""

from typing import Any, NotRequired, TypedDict


class FieldLabel(TypedDict):
    """A field key and its name, when the key names a field the app has."""

    field: str | None
    field_name: str | None


class Criterion(FieldLabel):
    """One condition: ``field operator value``."""

    operator: Any
    value: Any
    # "7 days", on the relative date operators that take a span.
    range: NotRequired[str]
    # Role key -> role name, when the value names roles.
    value_names: NotRequired[dict[str, str]]


class ValueAssignment(FieldLabel):
    """One ``field = value`` of a record rule or conditional field rule."""

    source: Any
    set_to: Any
    # e.g. "append": add to a connection field instead of replacing it.
    mode: NotRequired[Any]


class Recipient(TypedDict):
    mode: Any
    type: Any
    # A custom address, masked to its domain. Never the full address.
    address: NotRequired[str]
    field: NotRequired[str | None]
    field_name: NotRequired[str | None]
    connection: NotRequired[Any]


class EmailRule(TypedDict):
    """An email a trigger sends. The body is never included."""

    key: Any
    action: Any
    subject: str | None
    recipients: list[Recipient]
    criteria: list[Criterion]
    has_body: bool


class RecordRule(TypedDict):
    key: Any
    action: Any
    description: str
    connection: Any
    values: list[ValueAssignment]
    criteria: list[Criterion]


class SubmitRule(TypedDict):
    """What happens after a submit, or a page rule's message or redirect."""

    key: Any
    action: Any
    criteria: list[Criterion]
    message: NotRequired[str]
    target_page: NotRequired[Any]
    url: NotRequired[Any]


class HiddenView(TypedDict):
    view_key: str
    view_name: str | None


class PageRule(SubmitRule):
    """A rule that runs when a page loads."""

    hides: NotRequired[list[HiddenView]]
    hides_selected_view: NotRequired[bool]


class PageRules(TypedDict):
    scene_key: str
    scene_name: str
    scene_slug: str
    # "views": the page holds a selected view. "criteria": it holds none, and
    # is here because its rules test the object's fields.
    matched_by: str
    rules: list[PageRule]


class DisplayAction(FieldLabel):
    action: Any


class DisplayRule(TypedDict):
    key: Any
    actions: list[DisplayAction]
    criteria: list[Criterion]


class ViewHeader(TypedDict):
    """Where a trigger lives, and whether its view ever renders."""

    scene_key: str
    scene_name: str
    scene_slug: str
    view_key: str
    view_name: str
    view_type: str
    source_object: str | None
    reachable: bool
    unreachable_reason: NotRequired[str]


class ActionRule(TypedDict):
    """One rule of an action link: its conditions and what a click does."""

    key: Any
    link_text: Any
    criteria: list[Criterion]
    emails: list[EmailRule]
    records: list[RecordRule]
    submits: list[SubmitRule]
    warnings: list[str]
    unrecognised_keys: NotRequired[list[str]]


class Trigger(ViewHeader):
    """Something on a view that runs rules.

    ``trigger`` says which kind, and decides which of the other keys exist:

    - ``form_submit``: form_action, emails, records, submits, display_rules,
      warnings
    - ``action_link``: link_text, action_rules
    - ``inline_edit``: edited_field, active (and inactive_reason), emails,
      records, warnings
    """

    trigger: str
    form_action: NotRequired[Any]
    emails: NotRequired[list[EmailRule]]
    records: NotRequired[list[RecordRule]]
    submits: NotRequired[list[SubmitRule]]
    display_rules: NotRequired[list[DisplayRule]]
    warnings: NotRequired[list[str]]
    link_text: NotRequired[Any]
    action_rules: NotRequired[list[ActionRule]]
    edited_field: NotRequired[FieldLabel]
    active: NotRequired[bool]
    inactive_reason: NotRequired[str]


class QuietView(TypedDict):
    """A selected view with no rules, listed so silence is not ambiguous."""

    scene_key: str
    view_key: str
    view_name: str
    view_type: str
    reachable: bool


class ConnectedRecordRule(ViewHeader):
    """A record rule on another object's view that changes this object."""

    trigger: str
    record_rule: RecordRule
    trigger_criteria: list[Criterion]
    emails_on_same_trigger: list[EmailRule]
    link_text: NotRequired[Any]
    edited_field: NotRequired[FieldLabel]
    active: NotRequired[bool]
    inactive_reason: NotRequired[str]


class ConditionalRule(TypedDict):
    key: Any
    values: list[ValueAssignment]
    criteria: list[Criterion]


class FieldRules(FieldLabel):
    """A field's conditional rules, applied on every save of a record."""

    rules: list[ConditionalRule]


class Task(TypedDict):
    """A scheduled task and what it does."""

    trigger: str
    key: Any
    name: Any
    type: Any
    run_status: Any
    scheduled: Any
    schedule: dict[str, Any]
    action: Any
    criteria: list[Criterion]
    emails: list[EmailRule]
    records: list[RecordRule]


class RulesReport(TypedDict):
    triggers: list[Trigger]
    page_rules: list[PageRules]
    views_without_rules: list[QuietView]
    connected_record_rules: list[ConnectedRecordRule]
    conditional_field_rules: list[FieldRules]
    tasks: list[Task]
