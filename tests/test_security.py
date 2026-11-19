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
explicit `False`, and duplicate slugs retain all matching scenes. Knack slugs
are path-scoped, so duplicates are normal: every duplicate parent is disclosed
in navigation labels, and inheritance explores all of them. When branches
disagree the least restrictive one is reported, alongside an AMBIGUOUS PARENT
concern -- never a stricter reading that would hide a reachable public route.
"""

import csv
import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from knack_sleuth.cli import cli
from knack_sleuth.models import Application, KnackAppMetadata, Scene
from knack_sleuth.security import (
    analyze_scene_security,
    build_navigation_hierarchy,
    build_navigation_path,
    count_children,
    generate_security_report,
    get_profile_mapping,
    get_views_for_profile,
)
from knack_sleuth.sleuth import KnackSleuth

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
        assert (
            report.public_scenes + report.login_required_scenes == report.total_scenes
        )

    def test_total_profiles_matches_profile_objects(self, report, raw_objects):
        # A "profile object" per get_profile_mapping = object with user=True
        # AND a non-empty profile_key.
        profile_objs = [
            o for o in raw_objects if o.get("user") and o.get("profile_key")
        ]
        assert len(profile_objs) == 4
        assert report.total_profiles == len(profile_objs)

    def test_profiles_dict_matches_raw_profile_objects(self, report, raw_objects):
        expected = {
            o["profile_key"]: o["name"]
            for o in raw_objects
            if o.get("user") and o.get("profile_key")
        }
        # Spot-check one entry against the raw JSON directly.
        assert expected["profile_3"] == "Object Name 3"
        # Full mapping, independently built from the raw objects list.
        assert report.profiles == expected

    def test_scene_analyses_has_one_entry_per_scene(self, report, raw_scenes):
        assert len(report.scene_analyses) == len(raw_scenes)
        assert {s.scene_key for s in report.scene_analyses} == {
            s["key"] for s in raw_scenes
        }


class TestReportTotalsOnAHandBuiltApp:
    """Every summary figure, on an app small enough to count by eye.

    The sample app has no public page, no legacy ``profile_keys`` and no page
    open to more than five roles, so its totals cannot tell these apart.
    """

    @pytest.fixture
    def report(self):
        roles = [f"profile_{n}" for n in range(1, 7)]
        scenes = [
            Scene(
                key="scene_1", name="Menu", slug="menu", type="menu", authenticated=True
            ),
            Scene(key="scene_2", name="Public", slug="public", authenticated=False),
            Scene(key="scene_3", name="Members", slug="members", authenticated=True),
            # Older metadata names its roles under profile_keys.
            Scene(key="scene_4", name="Legacy", slug="legacy", profile_keys=roles[:1]),
            Scene(key="scene_5", name="Five", slug="five", allowed_profiles=roles[:5]),
            Scene(key="scene_6", name="Six", slug="six", allowed_profiles=roles),
            Scene(
                key="scene_7",
                name="Account",
                slug="account",
                type="user",
                authenticated=True,
            ),
            Scene(key="scene_8", name="Detail", slug="detail", parent="legacy"),
            Scene(key="scene_9", name="Leaflet", slug="leaflet", parent="public"),
        ]
        app = Application(
            id="app_totals",
            name="Totals",
            slug="totals",
            home_scene={"key": "scene_1", "slug": "menu"},
            scenes=scenes,
            objects=[],
        )
        return generate_security_report(app)

    def test_summary_counts(self, report):
        assert report.total_scenes == 9
        assert report.public_scenes == 2  # Public and Leaflet, below it
        assert report.login_required_scenes == 7
        # Login but no role list: Members and Account. The Menu is a list of
        # links, not a page, so it is not counted.
        assert report.unrestricted_authenticated_scenes == 2
        assert report.scenes_with_parents == 2  # Detail, Leaflet
        assert report.scenes_inheriting_security == 1  # Detail, from Legacy
        assert report.menu_scenes == 1
        assert report.utility_pages == 1  # Account

    def test_profile_access_counts(self, report):
        # profile_1: Legacy, Five, Six and Detail (inherited).
        assert report.profile_access_counts == {
            "profile_1": 4,
            "profile_2": 2,
            "profile_3": 2,
            "profile_4": 2,
            "profile_5": 2,
            "profile_6": 1,
        }

    def test_legacy_profile_keys_restrict_the_page_and_its_child(self, report):
        by_key = {s.scene_key: s for s in report.scene_analyses}
        assert by_key["scene_4"].allowed_profiles == ["profile_1"]
        assert by_key["scene_8"].allowed_profiles == ["profile_1"]

    def test_many_roles_is_flagged_above_five(self, report):
        by_key = {s.scene_key: s for s in report.scene_analyses}
        assert "MANY_ROLES" not in by_key["scene_5"].security_concern
        assert (
            "MANY_ROLES: Accessible by 6 different roles"
            in by_key["scene_6"].security_concern
        )


class TestAnalyzeSceneSecurityDirect:
    def test_matches_generate_security_report_for_same_scene(
        self, application, report, analyses_by_key
    ):
        # analyze_scene_security is the per-scene building block that
        # generate_security_report calls in a loop; calling it directly
        # with the same profiles/hierarchy inputs should reproduce the
        # exact same SceneSecurity the full report produced for scene_3.
        profiles = get_profile_mapping(application)
        hierarchy = build_navigation_hierarchy(application.scenes)
        scene_3 = next(s for s in application.scenes if s.key == "scene_3")

        direct = analyze_scene_security(scene_3, profiles, hierarchy)
        via_report = analyses_by_key["scene_3"]

        assert direct == via_report

    def test_scene_3_matches_what_the_raw_json_says(
        self, application, raw_scenes, raw_objects
    ):
        # The comparison above passes whatever the analyzer says, as long as
        # it says it twice. These values are read from the raw JSON instead:
        # scene_3 sets no restriction of its own; its parent slug is scene_4,
        # a login page in menu scene_45 whose login view is limited to
        # profile_10; and profile_10 is the object named "Object Name 10".
        by_key = {s["key"]: s for s in raw_scenes}
        scene_3, scene_4, menu = (
            by_key["scene_3"],
            by_key["scene_4"],
            by_key["scene_45"],
        )
        assert scene_3["authenticated"] is False
        assert not scene_3.get("allowed_profiles")
        assert scene_3["parent"] == scene_4["slug"]
        assert not scene_4.get("parent")
        assert scene_4["menu"] == "scene_45"
        (login,) = [v for v in scene_4["views"] if v["type"] == "login"]
        assert (login["limit_profile_access"], login["allowed_profiles"]) == (
            True,
            ["profile_10"],
        )
        role = next(o for o in raw_objects if o.get("profile_key") == "profile_10")
        assert role["name"] == "Object Name 10"

        app = application
        analysis = analyze_scene_security(
            next(s for s in app.scenes if s.key == "scene_3"),
            get_profile_mapping(app),
            build_navigation_hierarchy(app.scenes),
        )

        assert analysis.requires_login is True
        assert analysis.inherits_security is True
        assert analysis.allowed_profiles == ["Object Name 10"]
        assert analysis.page_nav == " > ".join(
            [menu["name"], scene_4["name"], scene_3["name"]]
        )
        assert analysis.page_nav == (
            "Data Maintenance > System Admin Home Login > Organizational Ref Data"
        )


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

    def test_child_without_own_auth_inherits_from_restricted_parent(
        self, analyses_by_key
    ):
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

    def _login_gated_chain(self):
        # Mirrors issue #27: a login page whose login view limits access to
        # Admin, a child that sets authenticated=True itself with no profiles
        # of its own, and a grandchild with no security settings at all.
        login = Scene(
            key="scene_login",
            name="Reporting Login",
            slug="reporting-login",
            type="authentication",
            views=[
                {
                    "key": "view_login",
                    "name": "Login",
                    "type": "login",
                    "limit_profile_access": True,
                    "allowed_profiles": ["profile_admin"],
                }
            ],
        )
        bare_auth = Scene(
            key="scene_bare",
            name="Financial Reporting",
            slug="financial-reporting",
            parent="reporting-login",
            authenticated=True,
            allowed_profiles=None,
        )
        grandchild = Scene(
            key="scene_grandchild",
            name="Report Detail",
            slug="report-detail",
            parent="financial-reporting",
        )
        return login, bare_auth, grandchild

    def test_own_bare_authentication_does_not_hide_login_ancestor_profiles(self):
        login, bare_auth, grandchild = self._login_gated_chain()
        hierarchy = build_navigation_hierarchy([login, bare_auth, grandchild])

        analysis = analyze_scene_security(
            bare_auth, {"profile_admin": "Admin"}, hierarchy
        )

        assert analysis.requires_login is True
        assert analysis.inherits_security is True
        assert analysis.allowed_profiles == ["Admin"]
        assert "Reporting Login" in analysis.security_concern

    def test_bare_authentication_ancestor_passes_through_login_profiles(self):
        login, bare_auth, grandchild = self._login_gated_chain()
        hierarchy = build_navigation_hierarchy([login, bare_auth, grandchild])

        analysis = analyze_scene_security(
            grandchild, {"profile_admin": "Admin"}, hierarchy
        )

        assert analysis.requires_login is True
        assert analysis.inherits_security is True
        assert analysis.allowed_profiles == ["Admin"]
        assert "Reporting Login" in analysis.security_concern

    def test_bare_authentication_without_restricted_ancestor_stays_login_only(self):
        parent = Scene(
            key="scene_parent",
            name="Public Parent",
            slug="public-parent",
            authenticated=False,
        )
        bare_auth = Scene(
            key="scene_bare",
            name="Members Area",
            slug="members-area",
            parent="public-parent",
            authenticated=True,
        )
        child = Scene(
            key="scene_child",
            name="Member Page",
            slug="member-page",
            parent="members-area",
        )
        hierarchy = build_navigation_hierarchy([parent, bare_auth, child])

        for scene in (bare_auth, child):
            analysis = analyze_scene_security(scene, {}, hierarchy)
            assert analysis.requires_login is True
            assert analysis.allowed_profiles == []


ADMIN_ONLY = {"profile_admin": "Admin"}


class TestInertProfileLists:
    """A profile list only restricts while ``limit_profile_access`` is on.

    Knack keeps ``allowed_profiles`` when the builder's "limit to roles"
    switch is turned off. Reading that leftover list as a restriction reports
    a page as role-locked when any logged-in user can open it (issue #24).
    """

    @staticmethod
    def _login_scene(**view_flags):
        return Scene(
            key="scene_login",
            name="Login",
            slug="login",
            type="authentication",
            authenticated=True,
            views=[
                {
                    "key": "view_login",
                    "name": "Login",
                    "type": "login",
                    "allowed_profiles": ["profile_admin"],
                    **view_flags,
                }
            ],
        )

    @pytest.mark.parametrize(
        "view_flags",
        [{"limit_profile_access": False}, {"limit_profile_access": None}, {}],
        ids=["off", "null", "absent"],
    )
    def test_view_list_without_the_limit_is_not_a_restriction(self, view_flags):
        login = self._login_scene(**view_flags)
        child = Scene(key="scene_child", name="Child", slug="child", parent="login")
        hierarchy = build_navigation_hierarchy([login, child])

        for scene in (login, child):
            analysis = analyze_scene_security(scene, ADMIN_ONLY, hierarchy)
            assert analysis.requires_login is True, scene.key
            assert analysis.allowed_profiles == [], scene.key
        own = analyze_scene_security(login, ADMIN_ONLY, hierarchy)
        assert "UNRESTRICTED" in own.security_concern

    @pytest.mark.parametrize("authenticated", [None, False])
    def test_login_view_with_the_limit_off_is_still_a_login_gate(self, authenticated):
        # Switching the role limit off opens the page to every role, not to
        # the public: the login view is still there. Knack does not always
        # set `authenticated` on the login page itself.
        login = Scene(
            key="scene_login",
            name="Login",
            slug="login",
            type="authentication",
            authenticated=authenticated,
            views=[
                {
                    "key": "view_login",
                    "name": "Login",
                    "type": "login",
                    "limit_profile_access": False,
                    "allowed_profiles": ["profile_admin"],
                }
            ],
        )
        child = Scene(key="scene_child", name="Child", slug="child", parent="login")
        hierarchy = build_navigation_hierarchy([login, child])

        own = analyze_scene_security(login, ADMIN_ONLY, hierarchy)
        below = analyze_scene_security(child, ADMIN_ONLY, hierarchy)

        assert (own.requires_login, own.allowed_profiles) == (True, [])
        assert "UNRESTRICTED" in own.security_concern
        assert "PUBLIC" not in own.security_concern
        assert (below.requires_login, below.allowed_profiles) == (True, [])
        assert below.inherits_security is True
        assert "PUBLIC" not in below.security_concern

    def test_view_list_with_the_limit_on_restricts_the_scene_and_its_children(self):
        login = self._login_scene(limit_profile_access=True)
        child = Scene(key="scene_child", name="Child", slug="child", parent="login")
        hierarchy = build_navigation_hierarchy([login, child])

        for scene in (login, child):
            analysis = analyze_scene_security(scene, ADMIN_ONLY, hierarchy)
            assert analysis.allowed_profiles == ["Admin"], scene.key

    def test_scene_list_with_the_limit_off_is_not_a_restriction(self):
        scene = Scene(
            key="scene_page",
            name="Page",
            slug="page",
            authenticated=True,
            limit_profile_access=False,
            allowed_profiles=["profile_admin"],
        )
        hierarchy = build_navigation_hierarchy([scene])

        analysis = analyze_scene_security(scene, ADMIN_ONLY, hierarchy)

        assert analysis.requires_login is True
        assert analysis.allowed_profiles == []
        assert "UNRESTRICTED" in analysis.security_concern

    @pytest.mark.parametrize(
        "scene_flags",
        [{"limit_profile_access": True}, {"limit_profile_access": None}, {}],
        ids=["on", "null", "absent"],
    )
    def test_scene_list_restricts_unless_the_limit_is_off(self, scene_flags):
        # Real metadata always pairs the list with the flag. Hand-written or
        # older metadata may omit it, and is taken at its word.
        scene = Scene(
            key="scene_page",
            name="Page",
            slug="page",
            authenticated=True,
            allowed_profiles=["profile_admin"],
            **scene_flags,
        )
        hierarchy = build_navigation_hierarchy([scene])

        analysis = analyze_scene_security(scene, ADMIN_ONLY, hierarchy)

        assert analysis.allowed_profiles == ["Admin"]

    def test_views_for_profile_ignores_a_scene_list_with_the_limit_off(self):
        scene = Scene(
            key="scene_page",
            name="Page",
            slug="page",
            limit_profile_access=False,
            allowed_profiles=["profile_admin"],
            views=[{"key": "view_1", "name": "Table", "type": "table"}],
        )

        names, keys = get_views_for_profile(scene, "profile_other", "Other")

        assert (names, keys) == (["Table"], ["view_1"])


# ---------------------------------------------------------------------------
# C. Navigation path / hierarchy
# ---------------------------------------------------------------------------


class TestNavigationPath:
    def test_child_scene_page_nav_contains_parent_then_child_in_order(
        self, analyses_by_key
    ):
        analysis = analyses_by_key["scene_3"]
        assert analysis.nav_level == "Child"
        page_nav = analysis.page_nav
        assert "System Admin Home Login" in page_nav
        assert "Organizational Ref Data" in page_nav
        assert page_nav.index("System Admin Home Login") < page_nav.index(
            "Organizational Ref Data"
        )

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
    def test_menu_scenes_list_matches_raw_menu_type_scenes(
        self, application, raw_scenes
    ):
        hierarchy = build_navigation_hierarchy(application.scenes)
        expected_keys = {s["key"] for s in raw_scenes if s.get("type") == "menu"}
        assert (
            {s.key for s in hierarchy["menu_scenes"]}
            == expected_keys
            == {"scene_45", "scene_46"}
        )

    def test_duplicate_slug_collision_documented(self, application, raw_scenes):
        # Two scenes share the slug "users": scene_6 ("Users") appears
        # earlier in the JSON scene list, scene_14 ("Object Name 3") later.
        # Both scenes remain available; neither is silently discarded.
        slug_owners = [s["key"] for s in raw_scenes if s["slug"] == "users"]
        assert slug_owners == ["scene_6", "scene_14"]

        hierarchy = build_navigation_hierarchy(application.scenes)
        assert [
            scene.key for scene in hierarchy["scenes_by_slug"]["users"]
        ] == slug_owners

        scene_13 = hierarchy["scenes_by_key"]["scene_13"]
        nav = build_navigation_path(scene_13, hierarchy)
        assert "Users (scene_6) / Object Name 3 (scene_14)" in nav["page_nav"]

    def test_path_scoped_duplicate_slug_is_not_a_conflict(self):
        # Knack slugs are path-scoped, so the same child slug under two
        # different parents is a normal layout, not an error. Both branches
        # here end at an authenticated root, so the child inherits cleanly.
        orders = Scene(
            key="scene_orders", name="Orders", slug="orders", authenticated=True
        )
        invoices = Scene(
            key="scene_invoices", name="Invoices", slug="invoices", authenticated=True
        )
        detail_a = Scene(
            key="scene_detail_a", name="Order Detail", slug="detail", parent="orders"
        )
        detail_b = Scene(
            key="scene_detail_b",
            name="Invoice Detail",
            slug="detail",
            parent="invoices",
        )
        child = Scene(
            key="scene_child", name="Line Item", slug="line-item", parent="detail"
        )
        hierarchy = build_navigation_hierarchy(
            [orders, invoices, detail_a, detail_b, child]
        )

        analysis = analyze_scene_security(child, {}, hierarchy)

        assert analysis.requires_login is True
        assert analysis.inherits_security is True
        assert "AMBIGUOUS PARENT" not in analysis.security_concern

    def test_conflicting_duplicate_parent_reports_least_restrictive_access(self):
        # When duplicate parents genuinely disagree, the report must not claim
        # the scene is protected: a reachable public path is the finding, so
        # report it and disclose the ambiguity rather than aborting.
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

        analysis = analyze_scene_security(child, {}, hierarchy)

        assert analysis.requires_login is False
        assert analysis.inherits_security is False
        assert "AMBIGUOUS PARENT" in analysis.security_concern
        assert "scene_restricted" in analysis.security_concern
        assert "scene_public" in analysis.security_concern
        assert "PUBLIC" in analysis.security_concern

    def test_conflicting_duplicate_parents_union_their_profiles(self):
        # Both routes are role-restricted but to *different* roles, so real
        # access is "role A or role B". Reporting only one would hide the
        # other role's route -- the false-secure direction.
        role_a = Scene(
            key="scene_a", name="A", slug="duplicate", allowed_profiles=["profile_a"]
        )
        role_b = Scene(
            key="scene_b", name="B", slug="duplicate", allowed_profiles=["profile_b"]
        )
        child = Scene(key="scene_child", name="Child", slug="child", parent="duplicate")
        hierarchy = build_navigation_hierarchy([role_a, role_b, child])

        analysis = analyze_scene_security(
            child, {"profile_a": "Role A", "profile_b": "Role B"}, hierarchy
        )

        assert analysis.requires_login is True
        assert analysis.inherits_security is True
        assert sorted(analysis.allowed_profiles) == ["Role A", "Role B"]
        assert "AMBIGUOUS PARENT" in analysis.security_concern

    def test_login_only_ancestor_beats_role_restricted_ancestor(self):
        # Duplicate parents where one demands only login and the other a
        # specific role: any logged-in user gets in via the first, so the
        # report must not claim the page is limited to that role.
        login_only = Scene(
            key="scene_login", name="Login Only", slug="duplicate", authenticated=True
        )
        role_locked = Scene(
            key="scene_role",
            name="Role Locked",
            slug="duplicate",
            allowed_profiles=["profile_x"],
        )
        child = Scene(key="scene_child", name="Child", slug="child", parent="duplicate")
        hierarchy = build_navigation_hierarchy([login_only, role_locked, child])

        analysis = analyze_scene_security(child, {"profile_x": "Role X"}, hierarchy)

        assert analysis.requires_login is True
        assert analysis.allowed_profiles == []
        assert "AMBIGUOUS PARENT" in analysis.security_concern

    def test_duplicate_slugs_do_not_make_the_walk_exponential(self):
        # Each level of duplicate slugs forks the ancestor chain. Without
        # memoization the walk doubles per level -- a depth-24 chain is ~17M
        # paths and the report never finishes. Ancestors of a slug don't depend
        # on the route taken to reach it, so the walk must reuse them.

        depth = 24
        scenes = [Scene(key="scene_root", name="Root", slug="level_0")]
        for level in range(1, depth + 1):
            for side in ("a", "b"):
                scenes.append(
                    Scene(
                        key=f"scene_{level}_{side}",
                        name=f"Level {level}{side}",
                        slug=f"level_{level}",
                        parent=f"level_{level - 1}",
                    )
                )
        leaf = Scene(
            key="scene_leaf", name="Leaf", slug="leaf", parent=f"level_{depth}"
        )
        scenes.append(leaf)
        hierarchy = build_navigation_hierarchy(scenes)

        started = time.perf_counter()
        analysis = analyze_scene_security(leaf, {}, hierarchy)
        elapsed = time.perf_counter() - started

        assert analysis.requires_login is False
        assert elapsed < 2.0, f"ancestor walk took {elapsed:.1f}s -- not memoized"

    @pytest.mark.parametrize("authenticated", [True, None])
    def test_cyclic_duplicate_slugs_do_not_make_the_walk_exponential(
        self, authenticated
    ):
        # A duplicate slug can point back down the chain, so resolving parents
        # by slug alone produces a cycle. A cycle must not switch memoization
        # off for the whole chain, or the walk doubles per level again. Bare
        # authentication is no longer a stopping point (issue #27), so login-
        # only chains reach the cycle as readily as unauthenticated ones.

        depth = 20
        scenes = [
            Scene(
                key="scene_root",
                name="Root",
                slug="level_0",
                allowed_profiles=["profile_admin"],
            )
        ]
        for level in range(1, depth + 1):
            for side in ("a", "b"):
                scenes.append(
                    Scene(
                        key=f"scene_{level}_{side}",
                        name=f"Level {level}{side}",
                        slug=f"level_{level}",
                        parent=f"level_{level - 1}",
                        authenticated=authenticated,
                    )
                )
        # Reuses the root's slug but hangs below the deepest level.
        scenes.append(
            Scene(
                key="scene_loop", name="Loop", slug="level_0", parent=f"level_{depth}"
            )
        )
        leaf = Scene(
            key="scene_leaf", name="Leaf", slug="leaf", parent=f"level_{depth}"
        )
        scenes.append(leaf)
        hierarchy = build_navigation_hierarchy(scenes)

        started = time.perf_counter()
        analysis = analyze_scene_security(leaf, {"profile_admin": "Admin"}, hierarchy)
        elapsed = time.perf_counter() - started

        # The only route that reaches a root goes through the Admin-only scene.
        assert analysis.requires_login is True
        assert analysis.allowed_profiles == ["Admin"]
        assert elapsed < 2.0, (
            f"ancestor walk took {elapsed:.1f}s -- cycle defeated memoization"
        )

    def test_login_only_scenes_that_only_loop_keep_their_own_login(self):
        # Two login-only scenes that name each other as parent have no route
        # to a root, so nothing is inherited from above. Each one still asks
        # for a login itself, exactly as it would at the top of a chain; the
        # loop must not turn that into "no restriction".
        first = Scene(
            key="scene_first",
            name="First",
            slug="first",
            parent="second",
            authenticated=True,
        )
        second = Scene(
            key="scene_second",
            name="Second",
            slug="second",
            parent="first",
            authenticated=True,
        )
        leaf = Scene(key="scene_leaf", name="Leaf", slug="leaf", parent="first")
        hierarchy = build_navigation_hierarchy([first, second, leaf])

        for scene in (first, second, leaf):
            analysis = analyze_scene_security(scene, {}, hierarchy)
            assert analysis.requires_login is True, scene.key
            assert analysis.allowed_profiles == [], scene.key

        leaf_analysis = analyze_scene_security(leaf, {}, hierarchy)
        assert leaf_analysis.inherits_security is True
        assert "AMBIGUOUS PARENT" not in (leaf_analysis.security_concern or "")

    def test_many_scenes_sharing_a_slug_stay_fast_across_the_report(self):
        # Hundreds of scenes behind one shared slug all contribute a label to
        # the same restriction, and every scene in the chain below inherits
        # it. Re-deriving that per scene, or merging labels by list scans,
        # turns the full report quadratic or worse.

        width = depth = 200
        scenes = [
            Scene(
                key=f"scene_shared_{i}",
                name=f"Shared {i}",
                slug="shared",
                allowed_profiles=["profile_admin"],
            )
            for i in range(width)
        ]
        parent = "shared"
        for level in range(depth):
            scenes.append(
                Scene(
                    key=f"scene_chain_{level}",
                    name=f"Chain {level}",
                    slug=f"chain_{level}",
                    parent=parent,
                )
            )
            parent = f"chain_{level}"
        app = Application(
            id="app_wide",
            name="Wide",
            slug="wide",
            home_scene={"key": "scene_shared_0", "slug": "shared"},
            scenes=scenes,
            objects=[],
        )

        started = time.perf_counter()
        report = generate_security_report(app)
        elapsed = time.perf_counter() - started

        deepest = next(
            a
            for a in report.scene_analyses
            if a.scene_key == f"scene_chain_{depth - 1}"
        )
        assert deepest.allowed_profiles == ["profile_admin"]
        assert elapsed < 2.0, f"security report took {elapsed:.1f}s"

    def test_conflicting_duplicate_parent_does_not_abort_the_report(self):
        # The whole-report path is what users actually run; a per-scene
        # ambiguity must not take the entire security report down with it.
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
        child = Scene(key="scene_child", name="Child", slug="child", parent="duplicate")
        app = Application(
            id="app_ambiguous",
            name="Ambiguous",
            slug="ambiguous",
            home_scene={"key": "scene_restricted", "slug": "duplicate"},
            scenes=[restricted, public, child],
            objects=[],
        )

        report = generate_security_report(app)

        assert report.total_scenes == 3
        child_row = next(
            s for s in report.scene_analyses if s.scene_key == "scene_child"
        )
        assert "AMBIGUOUS PARENT" in child_row.security_concern

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


class TestMalformedMenuReference:
    @pytest.mark.parametrize("menu", [["scene_404"], {"key": "scene_404"}, 7, ""])
    def test_a_menu_that_is_not_a_key_reads_as_no_menu(self, menu):
        # `menu` is undeclared metadata. An unhashable value used to raise
        # TypeError from a dict lookup and take the whole report down.
        scenes = [
            Scene(key="scene_1", name="Home", slug="home", menu=menu),
            Scene(key="scene_2", name="Page", slug="page", parent="home"),
        ]
        app = Application(
            id="app_menu",
            name="Menu",
            slug="menu",
            home_scene={"key": "scene_1", "slug": "home"},
            scenes=scenes,
            objects=[],
        )

        report = generate_security_report(app)

        assert (report.total_scenes, report.menu_scenes) == (2, 0)
        assert all("Menu" not in s.page_nav for s in report.scene_analyses)
        assert KnackSleuth(KnackAppMetadata(application=app)).generate_app_summary()[
            "ui_architecture"
        ]["scene_patterns"] == {
            "authenticated_scenes": 0,
            "public_scenes": 2,
            "total_scenes": 2,
        }


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

        expected = sum(
            1 for s in raw_scenes if s["key"] != "scene_4" and is_descendant(s)
        )
        assert expected == 33

        assert count_children("scene_4", report.scene_analyses) == expected

    def test_leaf_scene_has_no_children(self, report):
        # scene_13 ("Account Details") has no other scene whose parent
        # chain passes through it in the raw JSON.
        assert count_children("scene_13", report.scene_analyses) == 0

    def test_count_ignores_pages_that_only_share_part_of_a_name(self):
        # "Jobs" is a substring of "Jobs Archive", whose pages are not below
        # Jobs. Matching names in the navigation path counted them anyway.
        menu = Scene(key="scene_menu", name="Jobs Menu", slug="menu", type="menu")
        scenes = [
            menu,
            Scene(key="scene_1", name="Jobs", slug="jobs", menu="scene_menu"),
            Scene(key="scene_2", name="Job Details", slug="job", parent="jobs"),
            Scene(key="scene_3", name="Jobs Archive", slug="archive"),
            Scene(key="scene_4", name="Archived Job", slug="old", parent="archive"),
            Scene(key="scene_5", name="Notes", slug="notes", parent="old"),
        ]
        hierarchy = build_navigation_hierarchy(scenes)
        analyses = [analyze_scene_security(s, {}, hierarchy) for s in scenes]

        counts = {s.key: count_children(s.key, analyses) for s in scenes}

        assert counts == {
            "scene_menu": 1,  # Job Details, below its member page Jobs
            "scene_1": 1,  # Job Details
            "scene_2": 0,
            "scene_3": 2,  # Archived Job and Notes
            "scene_4": 1,  # Notes
            "scene_5": 0,
        }

    def test_a_deleted_menu_on_the_child_does_not_hide_it_from_its_real_menu(self):
        # Root belongs to the menu; Child still names a menu that was
        # deleted. The path reads "Menu > Root > Child", so the menu has one
        # page below its member page.
        scenes = [
            Scene(key="scene_menu", name="Menu", slug="menu", type="menu"),
            Scene(key="scene_1", name="Root", slug="root", menu="scene_menu"),
            Scene(
                key="scene_2",
                name="Child",
                slug="child",
                parent="root",
                menu="scene_deleted",
            ),
        ]
        hierarchy = build_navigation_hierarchy(scenes)
        analyses = [analyze_scene_security(s, {}, hierarchy) for s in scenes]

        assert analyses[2].page_nav == "Menu > Root > Child"
        assert [count_children(s.key, analyses) for s in scenes] == [1, 1, 0]

    @pytest.mark.parametrize(
        "child_first", [True, False], ids=["child-first", "parent-first"]
    )
    def test_page_below_a_namesake_finds_its_parent_whatever_the_order(
        self, child_first
    ):
        # Knack slugs are path-scoped, so a page can share its parent's slug.
        # Listed first, the child resolved "jobs" to itself: its path lost the
        # menu and the menu lost the child.
        menu = Scene(key="scene_m", name="Menu", slug="m", type="menu")
        parent = Scene(key="scene_1", name="Jobs", slug="jobs", menu="scene_m")
        child = Scene(key="scene_2", name="Job", slug="jobs", parent="jobs")
        scenes = [menu, child, parent] if child_first else [menu, parent, child]
        hierarchy = build_navigation_hierarchy(scenes)
        analyses = {s.key: analyze_scene_security(s, {}, hierarchy) for s in scenes}

        assert analyses["scene_2"].page_nav == "Menu > Jobs > Job"
        assert analyses["scene_2"].ancestor_keys == ["scene_1", "scene_m"]
        counts = {s.key: count_children(s.key, list(analyses.values())) for s in scenes}
        assert counts == {"scene_m": 1, "scene_1": 1, "scene_2": 0}

    def test_page_that_names_only_itself_as_parent_has_no_ancestors(self):
        scene = Scene(key="scene_1", name="Loop", slug="loop", parent="loop")
        hierarchy = build_navigation_hierarchy([scene])

        analysis = analyze_scene_security(scene, {}, hierarchy)

        assert analysis.page_nav == "Loop"
        assert analysis.ancestor_keys == []

    def test_count_includes_every_scene_sharing_a_duplicate_parent_slug(self):
        scenes = [
            Scene(key="scene_1", name="Home", slug="home"),
            Scene(key="scene_2", name="Home", slug="home"),
            Scene(key="scene_3", name="Page", slug="page", parent="home"),
        ]
        hierarchy = build_navigation_hierarchy(scenes)
        analyses = [analyze_scene_security(s, {}, hierarchy) for s in scenes]

        assert [count_children(s.key, analyses) for s in scenes] == [1, 1, 0]


# ---------------------------------------------------------------------------
# E. get_views_for_profile
# ---------------------------------------------------------------------------


class TestGetViewsForProfile:
    def test_unrestricted_scene_all_views_accessible_to_any_profile(
        self, scenes_by_key, raw_scenes
    ):
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

    def test_view_restricted_login_scene_only_allowed_profiles_see_view(
        self, scenes_by_key, raw_scenes
    ):
        # scene_52 ("Catalog Login") restricts its single Login Form view
        # to profile_3, profile_4, and profile_10 (limit_profile_access=true).
        scene_52_raw = next(s for s in raw_scenes if s["key"] == "scene_52")
        login_view = scene_52_raw["views"][0]
        assert login_view["limit_profile_access"] is True
        assert set(login_view["allowed_profiles"]) == {
            "profile_3",
            "profile_4",
            "profile_10",
        }

        scene = scenes_by_key["scene_52"]

        names, keys = get_views_for_profile(scene, "profile_3", "Object Name 3")
        assert names == ["Login Form"]
        assert keys == [login_view["key"]]
        assert len(names) == len(keys)

        # 'all_users' is not in the view's allowed_profiles list.
        names_excluded, keys_excluded = get_views_for_profile(
            scene, "all_users", "Object Name 2"
        )
        assert names_excluded == []
        assert keys_excluded == []


# ---------------------------------------------------------------------------
# F. profile_access_counts sanity
# ---------------------------------------------------------------------------


class TestProfileAccessCountsSanity:
    def test_every_count_within_total_scenes(self, report):
        for _profile_name, count in report.profile_access_counts.items():
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
        assert report.profile_access_counts.get("Object Name 10", 0) >= len(
            scenes_referencing_profile_10
        )

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
            cli,
            ["role-access-review", str(SAMPLE_FILE), "-o", str(full_path)],
            env=WIDE,
        )
        summary_result = runner.invoke(
            cli,
            [
                "role-access-review",
                str(SAMPLE_FILE),
                "-o",
                str(summary_path),
                "--summary-only",
            ],
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
            [
                "role-access-summary",
                "--role",
                "Object Name 3",
                str(SAMPLE_FILE),
                "-o",
                str(out),
            ],
            env=WIDE,
        )
        assert result.exit_code == 0
        assert out.exists()
        with out.open(newline="") as f:
            header = next(csv.reader(f))
        assert "scene_key" in header

    def test_role_name_saved_with_a_stray_space_is_found(self, tmp_path):
        # Knack keeps a trailing space typed into a role's name; nobody can
        # see it to type it back.
        data = json.loads(SAMPLE_FILE.read_text())
        role = next(
            o for o in data["application"]["objects"] if o["name"] == "Object Name 3"
        )
        role["name"] = "Object Name 3 "
        meta = tmp_path / "app.json"
        meta.write_text(json.dumps(data))

        result = runner.invoke(
            cli,
            [
                "role-access-summary",
                "--role",
                "object  name 3",
                str(meta),
                "-o",
                str(tmp_path / "out.csv"),
            ],
            env=WIDE,
        )

        assert result.exit_code == 0, result.output
        assert "not found" not in result.output

    def test_role_name_differing_only_by_case_beats_a_whitespace_near_match(
        self, tmp_path
    ):
        # "Job  Admin" comes first in the export; "job admin" is "Job Admin".
        data = json.loads(SAMPLE_FILE.read_text())
        roles = [o for o in data["application"]["objects"] if o.get("profile_key")]
        roles[0]["name"], roles[1]["name"] = "Job  Admin", "Job Admin"
        meta = tmp_path / "app.json"
        meta.write_text(json.dumps(data))

        result = runner.invoke(
            cli,
            [
                "role-access-summary",
                "--role",
                "job admin",
                str(meta),
                "-o",
                str(tmp_path / "out.csv"),
            ],
            env=WIDE,
        )

        assert result.exit_code == 0, result.output
        assert f"Profile: Job Admin ({roles[1]['profile_key']})" in result.output
        assert "Multiple profiles match" not in result.output

    def test_rows_say_why_the_role_can_open_the_scene(self, tmp_path, report):
        # Issue #27: a blank profile list used to read as "this role can open
        # it" with no way to tell a genuine login-only page from a resolver
        # gap. Every row now carries the basis for its access.
        out = tmp_path / "role_summary.csv"
        result = runner.invoke(
            cli,
            [
                "role-access-summary",
                "--role",
                "Object Name 3",
                str(SAMPLE_FILE),
                "-o",
                str(out),
            ],
            env=WIDE,
        )
        assert result.exit_code == 0
        with out.open(newline="") as f:
            rows = list(csv.DictReader(f))

        analyses = {a.scene_key: a for a in report.scene_analyses}
        expected = {}
        for key, a in analyses.items():
            if "Object Name 3" in a.allowed_profiles:
                expected[key] = "role"
            elif not a.requires_login:
                expected[key] = "public"
            elif not a.allowed_profiles:
                expected[key] = "any_login"
            if key in expected and a.scene_type == "user":
                expected[key] = "utility"
        assert {row["scene_key"]: row["access_basis"] for row in rows} == expected
        assert "role" in expected.values()
        for basis in ("role", "any_login", "public"):
            count = sum(1 for v in expected.values() if v == basis)
            assert f"{basis}: {count}" in result.output

    @pytest.mark.parametrize("authenticated", [None, True])
    def test_utility_page_without_roles_is_open_to_any_login(
        self, tmp_path, authenticated
    ):
        # Utility pages (type "user") are in the logged-in user's menu. With
        # no role list they are open to every logged-in user, never public.
        app = {
            "application": {
                "id": "app_utility",
                "name": "Utility",
                "slug": "utility",
                "home_scene": {"key": "scene_home", "slug": "home"},
                "objects": [
                    {
                        "key": "object_1",
                        "name": "Staff",
                        "user": True,
                        "profile_key": "profile_staff",
                        "fields": [],
                    }
                ],
                "scenes": [
                    {"key": "scene_home", "name": "Home", "slug": "home", "views": []},
                    {
                        "key": "scene_utility",
                        "name": "Account Settings",
                        "slug": "account-settings",
                        "type": "user",
                        "authenticated": authenticated,
                        "views": [],
                    },
                ],
            }
        }
        app_file = tmp_path / "app.json"
        app_file.write_text(json.dumps(app))
        out = tmp_path / "summary.csv"

        result = runner.invoke(
            cli,
            [
                "role-access-summary",
                "--profile-key",
                "profile_staff",
                str(app_file),
                "-o",
                str(out),
            ],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        with out.open(newline="") as f:
            rows = {row["scene_key"]: row["access_basis"] for row in csv.DictReader(f)}
        assert rows["scene_utility"] == "any_login"
        assert "any_login: 1" in result.output
        assert "utility:" not in result.output

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
