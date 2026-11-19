"""Tests for show-rules: what a Knack app's forms, action links and tasks DO."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from knack_sleuth.cli import cli
from knack_sleuth.core import load_app_metadata
from knack_sleuth.lookup import resolve_object
from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.rules import collect_rules, mask_address

FIXTURE = Path("tests/data/rules_app_meta.json")
WIDE = {"COLUMNS": "200"}
runner = CliRunner()

# Strings that must never leave the tool: email bodies, sender addresses,
# custom recipient mailboxes, and the stale `email` on field recipients.
SECRETS = [
    "BODY_SECRET",
    "TASK_BODY_SECRET",
    "APPROVE_BODY_SECRET",
    "noreply@sender.example",
    "intake.officer",
    "task.custom",
    "leftover@applicant.example",
    "x@applicant.example",
    "y@applicant.example",
    "NOTIFY_BODY_SECRET",
    "z@applicant.example",
]


@pytest.fixture
def report():
    return collect_rules(load_app_metadata(file_path=FIXTURE), "object_1")


def _by_view(report, view_key):
    return [t for t in report["triggers"] if t["view_key"] == view_key]


def _json(*args):
    result = runner.invoke(
        cli, ["show-rules", str(FIXTURE), *args, "--format", "json"], env=WIDE
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


class TestFormRules:
    def test_email_rule_reports_subject_and_recipients(self, report):
        (form,) = _by_view(report, "view_1")
        assert form["trigger"] == "form_submit"
        assert form["form_action"] == "insert"
        (email,) = form["emails"]
        assert email["subject"] == "Thanks for applying"
        assert email["has_body"] is True
        assert email["recipients"] == [
            {"mode": "to", "type": "field", "field": "field_2", "field_name": "Email"},
            {"mode": "bcc", "type": "custom", "address": "***@staff.example"},
        ]

    def test_record_submit_and_display_rules(self, report):
        (form,) = _by_view(report, "view_1")
        (record,) = form["records"]
        assert record["values"][0]["field"] == "field_4"
        assert record["values"][0]["set_to"] == "(blank)"
        assert form["submits"][0]["message"] == "Thanks!"
        assert form["display_rules"][0]["actions"] == [
            {"action": "hide", "field": "field_4", "field_name": "Reviewer Notes"}
        ]

    def test_warns_when_record_rule_blanks_a_field_the_email_uses(self, report):
        (form,) = _by_view(report, "view_1")
        (warning,) = form["warnings"]
        assert "field_4" in warning
        assert "email rules run after record rules" in warning


class TestActionLinks:
    def test_reject_link_updates_status_and_sends_nothing(self, report):
        (link,) = _by_view(report, "view_2")
        assert link["trigger"] == "action_link"
        assert link["link_text"] == "Reject"
        (rule,) = link["action_rules"]
        assert rule["emails"] == []
        assert [(v["field"], v["set_to"]) for v in rule["records"][0]["values"]] == [
            ("field_3", "Rejected")
        ]
        assert rule["submits"] == [
            {
                "key": None,
                "action": "message",
                "criteria": [],
                "message": "Applicant rejected",
            }
        ]

    def test_details_view_action_link_is_found_with_its_email_rule(self, report):
        (link,) = _by_view(report, "view_3")
        assert link["link_text"] == "Approve"
        (rule,) = link["action_rules"]
        assert [e["subject"] for e in rule["emails"]] == ["You're in"]
        assert rule["unrecognised_keys"] == ["future_rules"]

    def test_email_inside_record_rules_is_reported_as_email(self, report):
        (link,) = _by_view(report, "view_6")
        (rule,) = link["action_rules"]
        assert [e["subject"] for e in rule["emails"]] == ["Status update"]
        assert rule["records"] == []

    def test_non_list_email_key_is_surfaced_not_dropped(self):
        data = json.loads(FIXTURE.read_text())
        link = data["application"]["scenes"][1]["views"][0]["columns"][1]
        link["action_rules"][0]["email_rules"] = "unexpected"
        report = collect_rules(KnackAppMetadata(**data), "object_1")
        (rule,) = _by_view(report, "view_2")[0]["action_rules"]
        assert rule["unrecognised_keys"] == ["email_rules"]

    def test_rich_output_says_no_email_explicitly(self):
        result = runner.invoke(
            cli, ["show-rules", str(FIXTURE), "--view", "view_2"], env=WIDE
        )
        assert result.exit_code == 0, result.output
        assert "Action link 'Reject'" in result.output
        assert "Email rules: none" in result.output
        assert "field_3 (Status) = Rejected" in result.output


class TestReachabilityAndScope:
    def test_orphaned_view_is_flagged_unreachable(self, report):
        (orphan,) = _by_view(report, "view_4")
        assert orphan["reachable"] is False
        assert "never renders" in orphan["unreachable_reason"]
        assert all(
            t["reachable"] for t in report["triggers"] if t["view_key"] != "view_4"
        )

    def test_rich_output_flags_orphan(self):
        result = runner.invoke(
            cli, ["show-rules", str(FIXTURE), "--object", "object_1"], env=WIDE
        )
        assert "UNREACHABLE" in result.output

    def test_connected_record_rule_on_another_object_is_reported(self, report):
        (entry,) = report["connected_record_rules"]
        assert entry["view_key"] == "view_5"
        assert entry["source_object"] == "object_2"
        assert entry["record_rule"]["connection"] == "object_1.field_5"

    def test_views_without_rules_are_listed(self, report):
        assert [v["view_key"] for v in report["views_without_rules"]] == ["view_7"]

    def test_views_of_other_objects_are_not_triggers(self, report):
        assert {t["source_object"] for t in report["triggers"]} == {"object_1"}

    def test_view_filter_limits_to_one_view_without_tasks(self):
        payload = _json("--view", "view_2")
        assert [t["view_key"] for t in payload["triggers"]] == ["view_2"]
        assert payload["tasks"] == []
        assert payload["object"] is None


class TestTasks:
    def test_task_reports_status_schedule_and_email(self, report):
        (task,) = report["tasks"]
        assert task["key"] == "task_1"
        assert task["run_status"] == "paused"
        assert task["schedule"]["repeat"] == "weekly"
        assert task["criteria"][0]["field_name"] == "Status"
        (email,) = task["emails"]
        assert email["recipients"] == [
            {"mode": "to", "type": "field", "field": "field_2", "field_name": "Email"}
        ]


class TestPrivacy:
    @pytest.mark.parametrize("fmt", ["rich", "json"])
    def test_no_bodies_or_addresses_in_output(self, fmt):
        result = runner.invoke(
            cli,
            ["show-rules", str(FIXTURE), "--object", "object_1", "--format", fmt],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        leaked = [s for s in SECRETS if s in result.output]
        assert not leaked, f"leaked: {leaked}"

    def test_mask_address_keeps_only_domain(self):
        assert mask_address("jo.bloggs@example.org") == "***@example.org"
        assert mask_address("") == "(none)"
        assert mask_address("not-an-address") == "***"


class TestCli:
    def test_object_resolves_by_singular_inflection(self):
        payload = _json("--object", "Applicant")
        assert payload["object"] == {"key": "object_1", "name": "Applicants"}
        assert len(payload["tasks"]) == 1

    def test_requires_object_or_view(self):
        result = runner.invoke(cli, ["show-rules", str(FIXTURE)], env=WIDE)
        assert result.exit_code == 1
        assert "--object" in result.output

    def test_unknown_view_errors(self):
        result = runner.invoke(
            cli, ["show-rules", str(FIXTURE), "--view", "view_999"], env=WIDE
        )
        assert result.exit_code == 1


class TestInflectionLookup:
    def test_ambiguous_inflection_does_not_resolve(self):
        app = KnackAppMetadata(**json.loads(FIXTURE.read_text())).application
        inflections = app.objects[1].inflections
        assert inflections is not None
        inflections.singular = "Applicant"
        assert resolve_object(app, "Applicant") is None
        resolved = resolve_object(app, "Applicants")
        assert resolved is not None
        assert resolved.key == "object_1"


def _mutated(mutate):
    data = json.loads(FIXTURE.read_text())
    mutate(data["application"])
    return data


def _run_on(tmp_path, data, *args):
    path = tmp_path / "app.json"
    path.write_text(json.dumps(data))
    return runner.invoke(cli, ["show-rules", str(path), *args], env=WIDE)


class TestReviewRegressions:
    def test_malformed_rules_do_not_crash_or_leak(self, tmp_path):
        def mutate(app):
            form = app["scenes"][0]["views"][0]
            form["rules"]["emails"][0]["email"]["message"] = ["BODY_SECRET"]
            form["rules"]["emails"].append(
                {"key": "2", "action": "email", "email": "BODY_SECRET"}
            )
            form["rules"]["records"][0]["values"][0]["field"] = {"key": "field_4"}
            form["rules"]["records"][0]["criteria"] = "oops"
            app["objects"][0]["tasks"][0]["action"] = "oops"

        for fmt in ("rich", "json"):
            result = _run_on(
                tmp_path, _mutated(mutate), "--object", "object_1", "--format", fmt
            )
            assert result.exit_code == 0, result.output
            assert not [s for s in SECRETS if s in result.output]

    def test_record_rule_with_empty_email_placeholder_stays_a_record(self):
        data = _mutated(
            lambda app: app["scenes"][1]["views"][0]["columns"][1]["action_rules"][0][
                "record_rules"
            ][0].update(email={})
        )
        (rule,) = _by_view(
            collect_rules(KnackAppMetadata(**data), "object_1"), "view_2"
        )[0]["action_rules"]
        assert rule["emails"] == []
        assert rule["records"][0]["values"][0]["set_to"] == "Rejected"

    def test_form_with_only_display_rules_is_reported(self):
        def mutate(app):
            form = app["scenes"][0]["views"][0]
            form["rules"] = {"fields": form["rules"]["fields"]}

        (form,) = _by_view(
            collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1"), "view_1"
        )
        assert len(form["display_rules"]) == 1
        assert form["emails"] == []

    def test_details_view_display_rules_alone_are_not_a_trigger(self):
        def mutate(app):
            app["scenes"][1]["views"][1]["rules"] = {
                "fields": [{"key": "1", "actions": []}]
            }
            app["scenes"][1]["views"][1]["columns"] = []

        report = collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1")
        assert _by_view(report, "view_3") == []

    def test_metadata_markup_is_printed_literally(self, tmp_path):
        injected = "[/bold][red]INJECTED[/red][bold]"

        def mutate(app):
            app["scenes"][0]["views"][0]["action"] = injected
            app["scenes"][0]["views"][0]["name"] = injected

        result = _run_on(tmp_path, _mutated(mutate), "--object", "object_1")
        assert result.exit_code == 0, result.output
        assert result.output.count(injected) == 2

    def test_connected_rule_keeps_link_conditions_and_emails(self):
        def mutate(app):
            app["scenes"][2]["views"].append(
                {
                    "key": "view_8",
                    "name": "Programs Table",
                    "type": "table",
                    "source": {"object": "object_2"},
                    "columns": [
                        {
                            "type": "action_link",
                            "link_text": "Close",
                            "action_rules": [
                                {
                                    "key": "1",
                                    "link_text": "Close",
                                    "criteria": [
                                        {
                                            "field": "field_10",
                                            "operator": "is",
                                            "value": "Summer",
                                        }
                                    ],
                                    "record_rules": [
                                        {
                                            "key": "1",
                                            "action": "connection",
                                            "connection": "object_1.field_5",
                                            "values": [
                                                {
                                                    "type": "value",
                                                    "field": "field_3",
                                                    "value": "Closed",
                                                }
                                            ],
                                        },
                                        {
                                            "key": "2",
                                            "action": "email",
                                            "email": {
                                                "subject": "Programme closed",
                                                "message": "BODY_SECRET",
                                                "recipients": [
                                                    {
                                                        "recipient_mode": "to",
                                                        "recipient_type": "field",
                                                        "field": "field_2",
                                                    }
                                                ],
                                            },
                                        },
                                    ],
                                    "submit_rules": [],
                                }
                            ],
                        }
                    ],
                }
            )
            app["scenes"][2]["groups"][0]["columns"][0]["keys"].append("view_8")

        report = collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1")
        (entry,) = [
            e for e in report["connected_record_rules"] if e["view_key"] == "view_8"
        ]
        assert entry["trigger_criteria"][0]["field_name"] == "Title"
        assert [e["subject"] for e in entry["emails_on_same_trigger"]] == [
            "Programme closed"
        ]

    def test_redirect_target_uses_existing_page_and_ignores_stale_url(self):
        def mutate(app):
            app["scenes"][0]["views"][0]["rules"]["submits"] = [
                {
                    "key": "submit_1",
                    "action": "existing_page",
                    "existing_page": "review",
                    "scene": "stale-scene",
                    "url": "https://stale.example",
                    "criteria": [],
                }
            ]

        (form,) = _by_view(
            collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1"), "view_1"
        )
        (submit,) = form["submits"]
        assert submit["target_page"] == "review"
        assert "url" not in submit

    def test_relative_date_criteria_keep_their_range(self, tmp_path):
        # "is during the next" means nothing without "7 days". Knack also
        # leaves range/type behind on operators that take no range.
        def mutate(app):
            app["objects"][0]["tasks"][0]["action"]["criteria"] = [
                {
                    "field": "field_1",
                    "operator": "is during the next",
                    "range": "7",
                    "type": "days",
                    "value": "",
                },
                {
                    "field": "field_1",
                    "operator": "is before the previous",
                    "range": 3,
                    "type": "rolling weeks",
                    "value": "",
                },
                {
                    "field": "field_1",
                    "operator": "is today",
                    "range": "7",
                    "type": "days",
                    "value": "",
                },
                {
                    "field": "field_3",
                    "operator": "is",
                    "range": 1,
                    "type": "days",
                    "value": "Approved",
                },
            ]

        data = _mutated(mutate)
        (task,) = collect_rules(KnackAppMetadata(**data), "object_1")["tasks"]
        criteria = task["emails"][0]["criteria"]
        assert [c.get("range") for c in criteria] == [
            "7 days",
            "3 rolling weeks",
            None,
            None,
        ]

        result = _run_on(tmp_path, data, "--object", "object_1")
        assert result.exit_code == 0, result.output
        assert "is during the next 7 days" in result.output
        assert "is before the previous 3 rolling weeks" in result.output
        assert "is today and" in result.output
        assert "is 'Approved'" in result.output

    @staticmethod
    def _task_criteria(app, criteria):
        """Give Programs a role key, Applicants a roles field, and the task
        these criteria."""
        app["objects"][1]["profile_key"] = "profile_7"
        app["objects"][0]["fields"].append(
            {"key": "field_90", "name": "Roles", "type": "user_roles"}
        )
        app["objects"][0]["tasks"][0]["action"]["criteria"] = criteria

    def test_criteria_values_read_as_a_person_would_say_them(self, tmp_path):
        # An "is blank" on a date field keeps an empty date dict; a criterion
        # on a roles field holds role keys. Neither should print raw.
        def mutate(app):
            self._task_criteria(
                app,
                [
                    {
                        "field": "field_1",
                        "operator": "is blank",
                        "value": {"all_day": False, "date": ""},
                    },
                    {
                        "field": "field_1",
                        "operator": "is",
                        "value": {"all_day": False, "date": "01/02/2026"},
                    },
                    {
                        "field": "field_90",
                        "operator": "does not contain",
                        "value": "profile_7",
                    },
                    {
                        "field": "all_users-field_90",
                        "operator": "contains",
                        "value": ["profile_7", "profile_404"],
                    },
                ],
            )

        data = _mutated(mutate)
        (task,) = collect_rules(KnackAppMetadata(**data), "object_1")["tasks"]
        criteria = task["emails"][0]["criteria"]
        assert [c.get("value_names") for c in criteria] == [
            None,
            None,
            {"profile_7": "Programs"},
            {"profile_7": "Programs"},
        ]
        # The JSON keeps the stored value untouched.
        assert criteria[0]["value"] == {"all_day": False, "date": ""}

        result = _run_on(tmp_path, data, "--object", "object_1")
        assert result.exit_code == 0, result.output
        text = " ".join(result.output.split())
        assert "(Name) is blank and" in text
        assert "(Name) is '01/02/2026' and" in text
        assert "does not contain Programs (profile_7) and" in text
        assert "contains Programs (profile_7), 'profile_404'" in text
        assert "all_day" not in text

    def test_text_that_looks_like_a_role_key_is_left_as_text(self, tmp_path):
        # Only a roles field is compared with role keys. "profile_7" typed
        # into a text condition is the text "profile_7".
        def mutate(app):
            self._task_criteria(
                app, [{"field": "field_1", "operator": "is", "value": "profile_7"}]
            )

        data = _mutated(mutate)
        (task,) = collect_rules(KnackAppMetadata(**data), "object_1")["tasks"]
        assert "value_names" not in task["emails"][0]["criteria"][0]

        result = _run_on(tmp_path, data, "--object", "object_1")
        assert "(Name) is 'profile_7'" in " ".join(result.output.split())
        assert "Programs (profile_7)" not in result.output

    def test_role_list_holding_something_unexpected_does_not_crash(self, tmp_path):
        # The role lookup indexed a dict with whatever the list held; a
        # nested object raised TypeError and took the command down.
        def mutate(app):
            self._task_criteria(
                app,
                [
                    {
                        "field": "field_90",
                        "operator": "contains",
                        "value": ["profile_7", {"id": "user_1"}, 5],
                    }
                ],
            )

        result = _run_on(tmp_path, _mutated(mutate), "--object", "object_1")

        assert result.exit_code == 0, result.output
        assert "contains Programs (profile_7), {'id': 'user_1'}, 5" in " ".join(
            result.output.split()
        )

    @pytest.mark.parametrize(
        ("value", "shown"),
        [
            (
                {"date": "01/05/2026", "time": "8:00am", "all_day": False},
                "'01/05/2026 8:00am'",
            ),
            (
                {"date": "01/05/2026", "hours": "9", "minutes": "5", "am_pm": "PM"},
                "'01/05/2026 9:05PM'",
            ),
            (
                {
                    "all_day": False,
                    "hours": 7,
                    "minutes": 30,
                    "am_pm": "am",
                    "time": "",
                },
                "'7:30am'",
            ),
            (
                {"date": "01/05/2026", "hours": None, "minutes": None, "time": ""},
                "'01/05/2026'",
            ),
        ],
        ids=["time-string", "hours-and-minutes", "time-only", "date-only"],
    )
    def test_date_criteria_keep_their_time(self, tmp_path, value, shown):
        # Dropping the time moved the apparent cutoff to midnight.
        def mutate(app):
            self._task_criteria(
                app, [{"field": "field_1", "operator": "is after", "value": value}]
            )

        result = _run_on(tmp_path, _mutated(mutate), "--object", "object_1")

        assert result.exit_code == 0, result.output
        assert f"(Name) is after {shown}" in " ".join(result.output.split())

    def test_notification_recipient_is_a_masked_address(self, tmp_path):
        # A form's "email notification" lists bare addresses: no recipient
        # type or mode. It used to print as "None: None ?".
        def mutate(app):
            app["scenes"][0]["views"][0]["rules"]["emails"] = [
                {
                    "key": "9",
                    "action": "email_notification",
                    "criteria": [],
                    "email": {"recipients": [{"email": "staff.inbox@notify.example"}]},
                }
            ]

        data = _mutated(mutate)
        report = collect_rules(KnackAppMetadata(**data), "object_1")
        (email,) = _by_view(report, "view_1")[0]["emails"]
        assert email["recipients"] == [
            {"mode": "to", "type": "custom", "address": "***@notify.example"}
        ]

        result = _run_on(tmp_path, data, "--object", "object_1")
        assert result.exit_code == 0, result.output
        assert "Email notification → to: ***@notify.example" in result.output
        assert "None" not in result.output
        assert "staff.inbox" not in result.output

    @staticmethod
    def _editable_table(view_key, source, rule, **flags):
        """A table whose Status column carries one inline-edit rule."""
        return {
            "key": view_key,
            "name": "Editable",
            "type": "table",
            "source": {"object": source},
            "options": {"cell_editor": flags.get("cell_editor", True)},
            "columns": [
                {
                    "type": "field",
                    "header": "Status",
                    "field": {"key": "field_3"},
                    "ignore_edit": flags.get("ignore_edit", False),
                    "edit_rules": [rule],
                }
            ],
        }

    def test_inline_edit_rules_are_a_trigger(self, tmp_path):
        # Editing a cell in a table fires the column's edit_rules. A table
        # with only these was listed as having no rules.
        rule = {
            "key": "1",
            "action": "record",
            "connection": None,
            "criteria": [{"field": "field_3", "operator": "is", "value": "Rejected"}],
            "values": [{"type": "value", "field": "field_4", "value": "Closed out"}],
        }

        def mutate(app):
            app["scenes"][0]["views"].append(
                self._editable_table("view_20", "object_1", rule)
            )

        data = _mutated(mutate)
        report = collect_rules(KnackAppMetadata(**data), "object_1")

        (edit,) = _by_view(report, "view_20")
        assert edit["trigger"] == "inline_edit"
        assert edit["active"] is True
        assert edit["edited_field"] == {"field": "field_3", "field_name": "Status"}
        assert edit["emails"] == []
        (record,) = edit["records"]
        assert [(v["field"], v["set_to"]) for v in record["values"]] == [
            ("field_4", "Closed out")
        ]
        assert record["criteria"][0]["value"] == "Rejected"
        assert "view_20" not in {v["view_key"] for v in report["views_without_rules"]}

        result = _run_on(tmp_path, data, "--object", "object_1")
        assert result.exit_code == 0, result.output
        assert "Inline edit of field_3 (Status):" in result.output
        assert "INACTIVE" not in result.output

    @pytest.mark.parametrize(
        ("flags", "reason"),
        [
            ({"cell_editor": False}, "inline editing is off for this table"),
            ({"ignore_edit": True}, "inline editing is off for this column"),
        ],
    )
    def test_inline_edit_rules_left_behind_are_reported_inactive(
        self, tmp_path, flags, reason
    ):
        rule = {"key": "1", "action": "record", "values": []}

        def mutate(app):
            app["scenes"][0]["views"].append(
                self._editable_table("view_20", "object_1", rule, **flags)
            )

        data = _mutated(mutate)
        (edit,) = _by_view(
            collect_rules(KnackAppMetadata(**data), "object_1"), "view_20"
        )
        assert (edit["active"], edit["inactive_reason"]) == (False, reason)

        result = _run_on(tmp_path, data, "--object", "object_1")
        assert f"INACTIVE: {reason}" in result.output

    @pytest.mark.parametrize(
        ("change", "reason"),
        [
            (lambda t: t.update(type="details"), "only tables can be edited inline"),
            (
                lambda t: t["columns"][0].update(type="link", field=None),
                "this column is not an editable field",
            ),
            (
                lambda t: t["columns"][0].pop("field"),
                "this column is not an editable field",
            ),
            (
                lambda t: t["columns"][0].update(field={"key": ""}),
                "this column is not an editable field",
            ),
        ],
        ids=["details-view", "link-column", "no-field", "empty-key"],
    )
    def test_inline_edit_rules_where_nothing_can_be_edited_are_inactive(
        self, change, reason
    ):
        # cell_editor is on, but the rules sit where no cell can be edited.
        rule = {"key": "1", "action": "record", "values": []}

        def mutate(app):
            table = self._editable_table("view_20", "object_1", rule)
            change(table)
            app["scenes"][0]["views"].append(table)

        (edit,) = _by_view(
            collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1"), "view_20"
        )
        assert (edit["active"], edit["inactive_reason"]) == (False, reason)

    def test_inline_edit_on_another_object_reaches_this_one_by_connection(self):
        rule = {
            "key": "1",
            "action": "connection",
            "connection": "object_1.field_5",
            "values": [{"type": "value", "field": "field_3", "value": "Closed"}],
        }

        def mutate(app):
            table = self._editable_table("view_21", "object_2", rule)
            table["columns"][0]["field"] = {"key": "field_10"}
            app["scenes"][2]["views"].append(table)

        report = collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1")

        (connected,) = [
            c for c in report["connected_record_rules"] if c["view_key"] == "view_21"
        ]
        assert connected["trigger"] == "inline_edit"
        assert connected["edited_field"]["field"] == "field_10"
        assert connected["active"] is True
        assert connected["record_rule"]["connection"] == "object_1.field_5"

    @staticmethod
    def _with_page_rules(app):
        """Page rules on the Apply page (view_1), and on a page with no views."""
        app["scenes"][0]["rules"] = [
            {
                "key": "1",
                "action": "existing_page",
                "existing_page": "closed",
                "url": "https://stale.example",
                "message": "",
                "view_keys": [],
                "criteria": [{"field": "field_3", "operator": "is", "value": "Closed"}],
            },
            {
                "key": "2",
                "action": "hide_views",
                "existing_page": "leftover",
                "message": "",
                "view_keys": ["view_1"],
                "criteria": [
                    {
                        "field": "all_users-field_2",
                        "operator": "is blank",
                        "value": "",
                    }
                ],
            },
            {
                "key": "3",
                "action": "hide_views",
                "view_keys": ["view_99"],
                "criteria": [{"field": "field_3", "operator": "is", "value": "Paused"}],
            },
            {
                "key": "4",
                "action": "message",
                "type": "warning",
                "message": "<b>Hi</b>",
            },
        ]
        app["scenes"].append(
            {
                "key": "scene_50",
                "name": "Landing",
                "slug": "landing",
                "views": [{"key": "view_50", "name": "Text", "type": "rich_text"}],
                "rules": [
                    {
                        "key": "1",
                        "action": "existing_page",
                        "existing_page": "apply",
                        "criteria": [
                            {
                                "field": "field_5-field_10",
                                "operator": "is",
                                "value": "Summer",
                            }
                        ],
                    }
                ],
            }
        )

    def test_page_rules_of_the_objects_pages_are_reported(self, tmp_path):
        # Page rules run when the page loads. A form can be hidden, or the
        # visitor redirected away, without the form's own rules saying so.
        data = _mutated(self._with_page_rules)
        report = collect_rules(KnackAppMetadata(**data), "object_1")

        pages = {page["scene_key"]: page["rules"] for page in report["page_rules"]}
        redirect, hide_form, hide_other, message = pages["scene_1"]
        assert (redirect["action"], redirect["target_page"]) == (
            "existing_page",
            "closed",
        )
        assert "url" not in redirect  # stale: only a url action redirects there
        assert hide_form["hides"] == [
            {"view_key": "view_1", "view_name": "Application Form"}
        ]
        assert hide_form["hides_selected_view"] is True
        assert "target_page" not in hide_form
        assert hide_form["criteria"][0]["field_name"] == "logged-in user's Email"
        assert hide_other["hides_selected_view"] is False
        assert hide_other["hides"] == [{"view_key": "view_99", "view_name": None}]
        assert message["message"] == "Hi"

        # The landing page has no view of this object, but its rule tests the
        # object's Program field (through the connection).
        (landing,) = pages["scene_50"]
        assert landing["target_page"] == "apply"
        assert landing["criteria"][0]["field_name"] == "Program > Title"

        result = _run_on(tmp_path, data, "--object", "object_1")
        assert result.exit_code == 0, result.output
        assert (
            "Redirect to page 'closed' when field_3 (Status) is 'Closed'"
            in result.output
        )
        assert "Hide view_1 (Application Form) when" in result.output
        assert "1 rule(s) hiding other views on this page" in result.output
        assert "Message 'Hi'" in result.output

    def test_hide_rule_on_a_page_matched_by_criteria_is_printed_in_full(self, tmp_path):
        # The landing page has no view of the object; its hide rule is listed
        # only because it tests the object's Status. Collapsing it into
        # "1 rule(s) hiding other views" left the terminal saying nothing.
        def mutate(app):
            self._with_page_rules(app)
            app["scenes"][-1]["rules"].append(
                {
                    "key": "2",
                    "action": "hide_views",
                    "view_keys": ["view_50"],
                    "criteria": [
                        {"field": "field_3", "operator": "is", "value": "Approved"}
                    ],
                }
            )

        data = _mutated(mutate)
        report = collect_rules(KnackAppMetadata(**data), "object_1")
        matched = {p["scene_key"]: p["matched_by"] for p in report["page_rules"]}
        assert matched == {"scene_1": "views", "scene_50": "criteria"}

        result = _run_on(tmp_path, data, "--object", "object_1")
        assert result.exit_code == 0, result.output
        assert (
            "Hide view_50 (Text) when field_3 (Status) is 'Approved'" in result.output
        )
        # The object's own page still collapses rules hiding unrelated views.
        assert result.output.count("hiding other views on this page") == 1

    def test_page_rules_for_one_view_skip_rules_hiding_other_views(self):
        data = _mutated(self._with_page_rules)
        report = collect_rules(KnackAppMetadata(**data), view_key="view_1")

        (page,) = report["page_rules"]
        assert page["scene_key"] == "scene_1"
        assert [rule["key"] for rule in page["rules"]] == ["1", "2", "4"]

    def test_pages_without_page_rules_add_nothing(self, report):
        assert report["page_rules"] == []

    def test_conditional_field_rules_are_reported(self, report):
        (entry,) = report["conditional_field_rules"]
        assert entry["field_name"] == "Status"
        (rule,) = entry["rules"]
        assert rule["values"][0]["set_to"] == "Rejected"
        assert rule["criteria"][0]["field_name"] == "Reviewer Notes"


class TestViewSelection:
    """Which views collect_rules looks at, for each combination of arguments."""

    @pytest.fixture
    def metadata(self):
        return load_app_metadata(file_path=FIXTURE)

    def test_quiet_view_is_listed_with_reachability(self, report):
        assert report["views_without_rules"] == [
            {
                "scene_key": "scene_2",
                "view_key": "view_7",
                "view_name": "Plain Table",
                "view_type": "table",
                "reachable": True,
            }
        ]

    def test_object_and_view_keeps_the_view_even_from_another_object(self, metadata):
        """view_5 is sourced on object_2; naming it explicitly still reports it,
        while object_1's own tasks come along."""
        result = collect_rules(metadata, object_key="object_1", view_key="view_5")
        assert {t["view_key"] for t in result["triggers"]} == {"view_5"}
        assert len(result["tasks"]) == 1

    def test_connected_rules_only_without_a_view(self, metadata):
        assert collect_rules(metadata, object_key="object_1")["connected_record_rules"]
        with_view = collect_rules(metadata, object_key="object_1", view_key="view_1")
        assert with_view["connected_record_rules"] == []
