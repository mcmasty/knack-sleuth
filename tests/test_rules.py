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
            {"key": None, "action": "message", "criteria": [], "message": "Applicant rejected"}
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
        assert all(t["reachable"] for t in report["triggers"] if t["view_key"] != "view_4")

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
        app = KnackAppMetadata(
            **json.loads(FIXTURE.read_text())
        ).application
        inflections = app.objects[1].inflections
        assert inflections is not None
        inflections.singular = "Applicant"
        assert resolve_object(app, "Applicant") is None
        resolved = resolve_object(app, "Applicants")
        assert resolved is not None and resolved.key == "object_1"


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
            form["rules"]["emails"].append({"key": "2", "action": "email", "email": "BODY_SECRET"})
            form["rules"]["records"][0]["values"][0]["field"] = {"key": "field_4"}
            form["rules"]["records"][0]["criteria"] = "oops"
            app["objects"][0]["tasks"][0]["action"] = "oops"

        for fmt in ("rich", "json"):
            result = _run_on(tmp_path, _mutated(mutate), "--object", "object_1", "--format", fmt)
            assert result.exit_code == 0, result.output
            assert not [s for s in SECRETS if s in result.output]

    def test_record_rule_with_empty_email_placeholder_stays_a_record(self):
        data = _mutated(
            lambda app: app["scenes"][1]["views"][0]["columns"][1]["action_rules"][0][
                "record_rules"
            ][0].update(email={})
        )
        (rule,) = _by_view(collect_rules(KnackAppMetadata(**data), "object_1"), "view_2")[0][
            "action_rules"
        ]
        assert rule["emails"] == []
        assert rule["records"][0]["values"][0]["set_to"] == "Rejected"

    def test_form_with_only_display_rules_is_reported(self):
        def mutate(app):
            form = app["scenes"][0]["views"][0]
            form["rules"] = {"fields": form["rules"]["fields"]}

        (form,) = _by_view(collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1"), "view_1")
        assert len(form["display_rules"]) == 1
        assert form["emails"] == []

    def test_details_view_display_rules_alone_are_not_a_trigger(self):
        def mutate(app):
            app["scenes"][1]["views"][1]["rules"] = {"fields": [{"key": "1", "actions": []}]}
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
                {"key": "view_8", "name": "Programs Table", "type": "table",
                 "source": {"object": "object_2"},
                 "columns": [{"type": "action_link", "link_text": "Close", "action_rules": [
                     {"key": "1", "link_text": "Close",
                      "criteria": [{"field": "field_10", "operator": "is", "value": "Summer"}],
                      "record_rules": [
                          {"key": "1", "action": "connection", "connection": "object_1.field_5",
                           "values": [{"type": "value", "field": "field_3", "value": "Closed"}]},
                          {"key": "2", "action": "email", "email": {
                              "subject": "Programme closed", "message": "BODY_SECRET",
                              "recipients": [{"recipient_mode": "to", "recipient_type": "field",
                                              "field": "field_2"}]}}],
                      "submit_rules": []}]}]}
            )
            app["scenes"][2]["groups"][0]["columns"][0]["keys"].append("view_8")

        report = collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1")
        (entry,) = [e for e in report["connected_record_rules"] if e["view_key"] == "view_8"]
        assert entry["trigger_criteria"][0]["field_name"] == "Title"
        assert [e["subject"] for e in entry["emails_on_same_trigger"]] == ["Programme closed"]

    def test_redirect_target_uses_existing_page_and_ignores_stale_url(self):
        def mutate(app):
            app["scenes"][0]["views"][0]["rules"]["submits"] = [
                {"key": "submit_1", "action": "existing_page", "existing_page": "review",
                 "scene": "stale-scene", "url": "https://stale.example", "criteria": []}
            ]

        (form,) = _by_view(collect_rules(KnackAppMetadata(**_mutated(mutate)), "object_1"), "view_1")
        (submit,) = form["submits"]
        assert submit["target_page"] == "review"
        assert "url" not in submit

    def test_conditional_field_rules_are_reported(self, report):
        (entry,) = report["conditional_field_rules"]
        assert entry["field_name"] == "Status"
        (rule,) = entry["rules"]
        assert rule["values"][0]["set_to"] == "Rejected"
        assert rule["criteria"][0]["field_name"] == "Reviewer Notes"
