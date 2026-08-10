"""Tests for role/page access security analysis in knack_sleuth.security.

This module makes security claims (which roles can access which pages), so
the failure mode we're guarding against is wrong-but-plausible output, not
just crashes. Every pinned expectation below was derived independently by
reading tests/data/sample_knack_app_meta.json directly (see the comment
above each assertion for how) -- NOT by trusting security.py's own output
and pinning it. Where the module's output disagreed with an independent
derivation, that is called out explicitly rather than silently pinned.

Two behavioral quirks discovered while deriving these expectations now have
explicit contracts: missing `authenticated` values remain distinct from an
explicit `False`, and duplicate slugs retain all matching scenes. Equivalent
duplicate parents are disclosed in navigation labels; conflicting duplicates
raise an error because their inherited security cannot be determined safely.
"""

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from knack_sleuth.cli import cli
from knack_sleuth.models import Application, Scene
from knack_sleuth.security import (
    analyze_scene_security,
    build_navigation_hierarchy,
    build_navigation_path,
    count_children,
    generate_security_report,
    get_profile_mapping,
    get_views_for_profile,
)

SAMPLE_FILE = Path("tests/data/sample_knack_app_meta.json")

runner = CliRunner()
# Wide terminal so Rich doesn't truncate table columns in assertions
WIDE = {"COLUMNS": "200"}


# ---------------------------------------------------------------------------
# Module-scoped fixtures. These load the sample file directly rather than
# depending on conftest's function-scoped `sample_metadata_dict`, because a
# module-scoped fixture cannot depend on a function-scoped one -- and
# generate_security_report() only needs to run once for this whole file.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def raw_app_dict():
    with SAMPLE_FILE.open() as f:
        return json.load(f)["application"]


@pytest.fixture(scope="module")
def raw_scenes(raw_app_dict):
    return raw_app_dict["scenes"]


@pytest.fixture(scope="module")
def raw_objects(raw_app_dict):
    return raw_app_dict["objects"]


@pytest.fixture(scope="module")
def application(raw_app_dict):
    return Application(**raw_app_dict)


@pytest.fixture(scope="module")
def report(application):
    return generate_security_report(application)


@pytest.fixture(scope="module")
def scenes_by_key(application):
    return {s.key: s for s in application.scenes}


@pytest.fixture(scope="module")
def analyses_by_key(report):
    return {s.scene_key: s for s in report.scene_analyses}


# ---------------------------------------------------------------------------
# A. generate_security_report top-line statistics
# ---------------------------------------------------------------------------


class TestGenerateSecurityReportTopLine:
    def test_total_scenes_matches_raw_scene_count(self, report, raw_scenes):
        # Derived: len(application["scenes"]) counted directly in the JSON.
        assert len(raw_scenes) == 65
        assert report.total_scenes == len(raw_scenes)

    def test_public_and_login_required_split(self, report, raw_scenes):
        # Derived by inspecting all 11 parentless (top-level) scenes in the
        # raw JSON: the 2 `type: "menu"` scenes (scene_45, scene_46) both
        # carry `"authenticated": true`; all 9 `type: "authentication"`
        # scenes have a "Login Form" view with `limit_profile_access: true`
        # and a non-empty `allowed_profiles` list (restricting who may even
        # use that login page). Every other scene (54) carries a `parent`
        # slug that resolves to a real scene in the file, so it walks up to
        # one of those 11 roots and inherits a login/profile requirement
        # (see module docstring point 1 above -- this walk-up always
        # "inherits" something once the parent resolves). There is
        # therefore no scene in this app that should be public.
        top_level = [s for s in raw_scenes if not s.get("parent")]
        assert len(top_level) == 11
        menu_scenes = [s for s in top_level if s.get("type") == "menu"]
        auth_scenes = [s for s in top_level if s.get("type") == "authentication"]
        assert len(menu_scenes) + len(auth_scenes) == len(top_level)
        assert all(s.get("authenticated") is True for s in menu_scenes)
        for s in auth_scenes:
            login_views = [v for v in s["views"] if v["type"] == "login"]
            assert len(login_views) == 1
            assert login_views[0]["limit_profile_access"] is True
            assert login_views[0]["allowed_profiles"]

        assert report.public_scenes == 0
        assert report.login_required_scenes == 65
        assert report.public_scenes + report.login_required_scenes == report.total_scenes

    def test_total_profiles_matches_profile_objects(self, report, raw_objects):
        # A "profile object" per get_profile_mapping = object with user=True
        # AND a non-empty profile_key.
        profile_objs = [o for o in raw_objects if o.get("user") and o.get("profile_key")]
        assert len(profile_objs) == 4
        assert report.total_profiles == len(profile_objs)

    def test_profiles_dict_matches_raw_profile_objects(self, report, raw_objects):
        expected = {
            o["profile_key"]: o["name"] for o in raw_objects if o.get("user") and o.get("profile_key")
        }
        # Spot-check one entry against the raw JSON directly.
        assert expected["profile_3"] == "Object Name 3"
        # Full mapping, independently built from the raw objects list.
        assert report.profiles == expected

    def test_scene_analyses_has_one_entry_per_scene(self, report, raw_scenes):
        assert len(report.scene_analyses) == len(raw_scenes)
        assert {s.scene_key for s in report.scene_analyses} == {s["key"] for s in raw_scenes}


class TestAnalyzeSceneSecurityDirect:
    def test_matches_generate_security_report_for_same_scene(self, application, report, analyses_by_key):
        # analyze_scene_security is the per-scene building block that
        # generate_security_report calls in a loop; calling it directly
        # with the same profiles/hierarchy inputs should reproduce the
        # exact same SceneSecurity the full report produced for scene_3.
        profiles = get_profile_mapping(application)
        hierarchy = build_navigation_hierarchy(application.scenes)
        scene_3 = next(s for s in application.scenes if s.key == "scene_3")

        direct = analyze_scene_security(scene_3, profiles, hierarchy)
        via_report = analyses_by_key["scene_3"]

        assert direct.requires_login == via_report.requires_login
        assert direct.inherits_security == via_report.inherits_security
        assert direct.allowed_profiles == via_report.allowed_profiles
        assert direct.page_nav == via_report.page_nav


class TestGetProfileMapping:
    def test_matches_generate_security_report_profiles(self, application, report):
        assert get_profile_mapping(application) == report.profiles

    def test_excludes_objects_without_profile_key(self, application):
        mapping = get_profile_mapping(application)
        non_profile_objects = [o for o in application.objects if not o.profile_key]
        assert len(non_profile_objects) == len(application.objects) - 4
        for obj in non_profile_objects:
            assert obj.name not in mapping.values() or obj.profile_key


# ---------------------------------------------------------------------------
# B. Security inheritance
# ---------------------------------------------------------------------------


class TestSecurityInheritance:
    """scene_3 ("Organizational Ref Data") sets its own authenticated=False
    and has no profile restriction of its own. Its parent, scene_4 ("System
    Admin Home Login", slug system-admin-home-login), restricts its Login
    Form view to profile_10 only. Both facts were read directly off the raw
    JSON below before checking what analyze_scene_security concluded.
    """

    def test_raw_json_shows_child_has_no_own_restriction(self, raw_scenes):
        scene_3 = next(s for s in raw_scenes if s["key"] == "scene_3")
        scene_4 = next(s for s in raw_scenes if s["key"] == "scene_4")
        assert scene_3["parent"] == scene_4["slug"] == "system-admin-home-login"
        assert scene_3.get("authenticated") is False
        assert not scene_3.get("allowed_profiles")
        assert not scene_3.get("profile_keys")

        login_view = next(v for v in scene_4["views"] if v["type"] == "login")
        assert login_view["limit_profile_access"] is True
        assert login_view["allowed_profiles"] == ["profile_10"]

    def test_child_without_own_auth_inherits_from_restricted_parent(self, analyses_by_key):
        analysis = analyses_by_key["scene_3"]
        assert analysis.requires_login is True
        assert analysis.inherits_security is True
        assert analysis.allowed_profiles == ["Object Name 10"]
        assert "Inherits security from parent" in analysis.security_concern
        assert "System Admin Home Login" in analysis.security_concern

    def test_scenes_with_parents_equals_scenes_inheriting_security(self, report):
        # Every child in this particular sample ultimately descends from one
        # of the restricted roots, so all 54 genuinely inherit a restriction.
        assert report.scenes_with_parents == report.scenes_inheriting_security == 54

    def test_missing_authentication_is_distinct_from_explicit_false(self):
        missing = Scene(key="scene_missing", name="Missing", slug="missing")
        explicit = Scene(
            key="scene_explicit",
            name="Explicit",
            slug="explicit",
            authenticated=False,
        )

        assert missing.authenticated is None
        assert explicit.authenticated is False

    def test_public_parent_does_not_mark_child_as_inheriting(self):
        parent = Scene(
            key="scene_parent",
            name="Public Parent",
            slug="public-parent",
            authenticated=False,
        )
        child = Scene(
            key="scene_child",
            name="Public Child",
            slug="public-child",
            parent="public-parent",
        )
        hierarchy = build_navigation_hierarchy([parent, child])

        analysis = analyze_scene_security(child, {}, hierarchy)

        assert analysis.requires_login is False
        assert analysis.inherits_security is False
        assert analysis.allowed_profiles == []

    def test_own_restriction_is_not_reported_as_inherited(self):
        parent = Scene(
            key="scene_parent",
            name="Restricted Parent",
            slug="restricted-parent",
            allowed_profiles=["profile_parent"],
        )
        child = Scene(
            key="scene_child",
            name="Restricted Child",
            slug="restricted-child",
            parent="restricted-parent",
            allowed_profiles=["profile_child"],
        )
        hierarchy = build_navigation_hierarchy([parent, child])

        analysis = analyze_scene_security(
            child,
            {"profile_parent": "Parent", "profile_child": "Child"},
            hierarchy,
        )

        assert analysis.requires_login is True
        assert analysis.inherits_security is False
        assert analysis.allowed_profiles == ["Child"]


# ---------------------------------------------------------------------------
# C. Navigation path / hierarchy
# ---------------------------------------------------------------------------


class TestNavigationPath:
    def test_child_scene_page_nav_contains_parent_then_child_in_order(self, analyses_by_key):
        analysis = analyses_by_key["scene_3"]
        assert analysis.nav_level == "Child"
        page_nav = analysis.page_nav
        assert "System Admin Home Login" in page_nav
        assert "Organizational Ref Data" in page_nav
        assert page_nav.index("System Admin Home Login") < page_nav.index("Organizational Ref Data")

    def test_top_level_scene_classified_as_top_level(self, analyses_by_key, raw_scenes):
        # scene_4 has parent=None in the raw JSON and type="authentication"
        # (not "menu"), so it should land in the "Top-Level" bucket.
        scene_4 = next(s for s in raw_scenes if s["key"] == "scene_4")
        assert scene_4.get("parent") is None
        assert scene_4["type"] == "authentication"
        assert analyses_by_key["scene_4"].nav_level == "Top-Level"

    def test_menu_scenes_classified_as_menu(self, analyses_by_key, raw_scenes):
        menu_keys = {s["key"] for s in raw_scenes if s.get("type") == "menu"}
        assert menu_keys == {"scene_45", "scene_46"}
        for key in menu_keys:
            assert analyses_by_key[key].nav_level == "Menu"


class TestNavigationHierarchy:
    def test_menu_scenes_list_matches_raw_menu_type_scenes(self, application, raw_scenes):
        hierarchy = build_navigation_hierarchy(application.scenes)
        expected_keys = {s["key"] for s in raw_scenes if s.get("type") == "menu"}
        assert {s.key for s in hierarchy["menu_scenes"]} == expected_keys == {"scene_45", "scene_46"}

    def test_duplicate_slug_collision_documented(self, application, raw_scenes):
        # Two scenes share the slug "users": scene_6 ("Users") appears
        # earlier in the JSON scene list, scene_14 ("Object Name 3") later.
        # Both scenes remain available; neither is silently discarded.
        slug_owners = [s["key"] for s in raw_scenes if s["slug"] == "users"]
        assert slug_owners == ["scene_6", "scene_14"]

        hierarchy = build_navigation_hierarchy(application.scenes)
        assert [scene.key for scene in hierarchy["scenes_by_slug"]["users"]] == slug_owners

        scene_13 = hierarchy["scenes_by_key"]["scene_13"]
        nav = build_navigation_path(scene_13, hierarchy)
        assert "Users (scene_6) / Object Name 3 (scene_14)" in nav["page_nav"]

    def test_conflicting_duplicate_slug_fails_instead_of_guessing(self):
        restricted = Scene(
            key="scene_restricted",
            name="Restricted",
            slug="duplicate",
            authenticated=True,
        )
        public = Scene(
            key="scene_public",
            name="Public",
            slug="duplicate",
            authenticated=False,
        )
        child = Scene(
            key="scene_child",
            name="Child",
            slug="child",
            parent="duplicate",
        )
        hierarchy = build_navigation_hierarchy([restricted, public, child])

        with pytest.raises(ValueError, match="Ambiguous parent slug 'duplicate'"):
            analyze_scene_security(child, {}, hierarchy)

    def test_build_navigation_path_top_level_menu_scene(self, application):
        hierarchy = build_navigation_hierarchy(application.scenes)
        scenes_by_key = hierarchy["scenes_by_key"]
        scene_45 = scenes_by_key["scene_45"]
        nav = build_navigation_path(scene_45, hierarchy)
        assert nav["nav_level"] == "Menu"
        assert nav["page_nav"] == scene_45.name


# ---------------------------------------------------------------------------
# D. count_children
# ---------------------------------------------------------------------------


class TestCountChildren:
    def test_count_children_of_system_admin_home_login(self, report, raw_scenes):
        # Independently walk each scene's `parent` slug chain in the raw
        # JSON to see whether it eventually reaches scene_4's slug
        # "system-admin-home-login" -- i.e. compute true descendants
        # without going through security.py at all.
        scenes_by_slug = {s["slug"]: s for s in raw_scenes}
        target_slug = "system-admin-home-login"

        def is_descendant(scene):
            slug = scene.get("parent")
            seen = set()
            while slug and slug not in seen:
                seen.add(slug)
                if slug == target_slug:
                    return True
                parent = scenes_by_slug.get(slug)
                if not parent:
                    return False
                slug = parent.get("parent")
            return False

        expected = sum(1 for s in raw_scenes if s["key"] != "scene_4" and is_descendant(s))
        assert expected == 33

        assert count_children("scene_4", report.scene_analyses) == expected

    def test_leaf_scene_has_no_children(self, report):
        # scene_13 ("Account Details") has no other scene whose parent
        # chain passes through it in the raw JSON.
        assert count_children("scene_13", report.scene_analyses) == 0


# ---------------------------------------------------------------------------
# E. get_views_for_profile
# ---------------------------------------------------------------------------


class TestGetViewsForProfile:
    def test_unrestricted_scene_all_views_accessible_to_any_profile(self, scenes_by_key, raw_scenes):
        # scene_6 ("Users") has neither scene-level nor view-level profile
        # restrictions anywhere in the raw JSON.
        scene_6_raw = next(s for s in raw_scenes if s["key"] == "scene_6")
        assert not scene_6_raw.get("allowed_profiles")
        for v in scene_6_raw["views"]:
            assert not v.get("allowed_profiles")
            assert not v.get("limit_profile_access")

        scene = scenes_by_key["scene_6"]
        names, keys = get_views_for_profile(scene, "profile_3", "Object Name 3")
        assert names == ["Add User Account", "User Accounts"]
        assert keys == ["view_6", "view_11"]
        assert len(names) == len(keys)
        for key in keys:
            assert key.startswith("view_")
            assert key.split("_", 1)[1].isdigit()

    def test_view_restricted_login_scene_only_allowed_profiles_see_view(self, scenes_by_key, raw_scenes):
        # scene_52 ("Catalog Login") restricts its single Login Form view
        # to profile_3, profile_4, and profile_10 (limit_profile_access=true).
        scene_52_raw = next(s for s in raw_scenes if s["key"] == "scene_52")
        login_view = scene_52_raw["views"][0]
        assert login_view["limit_profile_access"] is True
        assert set(login_view["allowed_profiles"]) == {"profile_3", "profile_4", "profile_10"}

        scene = scenes_by_key["scene_52"]

        names, keys = get_views_for_profile(scene, "profile_3", "Object Name 3")
        assert names == ["Login Form"]
        assert keys == [login_view["key"]]
        assert len(names) == len(keys)

        # 'all_users' is not in the view's allowed_profiles list.
        names_excluded, keys_excluded = get_views_for_profile(scene, "all_users", "Object Name 2")
        assert names_excluded == []
        assert keys_excluded == []


# ---------------------------------------------------------------------------
# F. profile_access_counts sanity
# ---------------------------------------------------------------------------


class TestProfileAccessCountsSanity:
    def test_every_count_within_total_scenes(self, report):
        for profile_name, count in report.profile_access_counts.items():
            assert 0 < count <= report.total_scenes

    def test_profile_referenced_in_raw_json_has_nonzero_count(self, report, raw_scenes):
        # profile_10 is referenced directly in the allowed_profiles of 7 of
        # the 9 login-page "Login Form" views in the raw JSON (scene_4,
        # scene_21, scene_41, scene_48, scene_52, scene_54, scene_76), so
        # its aggregate access count (including inherited descendants) must
        # be at least that many.
        scenes_referencing_profile_10 = [
            s["key"]
            for s in raw_scenes
            for v in s.get("views", [])
            if "profile_10" in (v.get("allowed_profiles") or [])
        ]
        assert len(scenes_referencing_profile_10) == 7
        assert report.profile_access_counts.get("Object Name 10", 0) >= len(scenes_referencing_profile_10)

    def test_profile_never_referenced_has_zero_count(self, report, raw_scenes):
        # 'all_users' (Object Name 2) never appears in any scene- or
        # view-level allowed_profiles/profile_keys list in the raw JSON, so
        # it should accrue no access count at all (and, since
        # profile_access_counts is built from a defaultdict that's only
        # populated on actual hits, it may be entirely absent from the
        # dict rather than present with value 0).
        for s in raw_scenes:
            assert "all_users" not in (s.get("allowed_profiles") or [])
            assert "all_users" not in (s.get("profile_keys") or [])
            for v in s.get("views", []):
                assert "all_users" not in (v.get("allowed_profiles") or [])

        assert report.profile_access_counts.get("Object Name 2", 0) == 0


# ---------------------------------------------------------------------------
# G. CLI smoke tests (role-access-review / role-access-summary)
# ---------------------------------------------------------------------------


class TestRoleAccessReviewCli:
    def test_full_review_writes_one_row_per_scene(self, tmp_path):
        out = tmp_path / "review.csv"
        result = runner.invoke(
            cli, ["role-access-review", str(SAMPLE_FILE), "-o", str(out)], env=WIDE
        )
        assert result.exit_code == 0
        assert out.exists()

        with out.open(newline="") as f:
            rows = list(csv.reader(f))
        assert "scene_key" in rows[0]
        # header row + one row per scene (65, confirmed independently above)
        assert len(rows) == 65 + 1

    def test_summary_only_has_fewer_rows_than_full_report(self, tmp_path):
        full_path = tmp_path / "full.csv"
        summary_path = tmp_path / "summary.csv"

        full_result = runner.invoke(
            cli, ["role-access-review", str(SAMPLE_FILE), "-o", str(full_path)], env=WIDE
        )
        summary_result = runner.invoke(
            cli,
            ["role-access-review", str(SAMPLE_FILE), "-o", str(summary_path), "--summary-only"],
            env=WIDE,
        )
        assert full_result.exit_code == 0
        assert summary_result.exit_code == 0

        with full_path.open(newline="") as f:
            full_rows = list(csv.reader(f))
        with summary_path.open(newline="") as f:
            summary_rows = list(csv.reader(f))

        assert len(summary_rows) < len(full_rows)
        # Only Menu / Top-Level scenes (11, independently derived above)
        # plus the header row should remain.
        assert len(summary_rows) == 11 + 1


class TestRoleAccessSummaryCli:
    def test_valid_role_writes_csv(self, tmp_path):
        out = tmp_path / "role_summary.csv"
        result = runner.invoke(
            cli,
            ["role-access-summary", "--role", "Object Name 3", str(SAMPLE_FILE), "-o", str(out)],
            env=WIDE,
        )
        assert result.exit_code == 0
        assert out.exists()
        with out.open(newline="") as f:
            header = next(csv.reader(f))
        assert "scene_key" in header

    def test_unknown_role_exits_1_and_lists_available_roles(self):
        result = runner.invoke(
            cli,
            ["role-access-summary", "--role", "Nonexistent Role XYZ", str(SAMPLE_FILE)],
            env=WIDE,
        )
        assert result.exit_code == 1
        assert "not found" in result.output
        # A real role name (independently confirmed above) must be listed
        # as an available alternative.
        assert "Object Name 3" in result.output

    def test_missing_role_and_profile_key_exits_1(self):
        result = runner.invoke(cli, ["role-access-summary", str(SAMPLE_FILE)], env=WIDE)
        assert result.exit_code == 1
        assert "--role or --profile-key" in result.output
