"""The findings analyze_scene_security reports, one rule at a time.

Each test builds the smallest set of scenes that exercises one rule, so a
change to that rule fails here by name rather than somewhere in a large
fixture.
"""

from typing import Any

import pytest

from knack_sleuth.models import Scene, SceneSecurity
from knack_sleuth.security import (
    MANY_ROLES_THRESHOLD,
    analyze_scene_security,
    build_navigation_hierarchy,
)


def scene(key: str, parent: str | None = None, **settings: Any) -> Scene:
    return Scene(key=key, name=key.title(), slug=key, parent=parent, **settings)


def analyze(*scenes: Scene) -> dict[str, SceneSecurity]:
    hierarchy = build_navigation_hierarchy(list(scenes))
    profiles = {f"profile_{n}": f"Role {n}" for n in range(1, 20)}
    return {s.key: analyze_scene_security(s, profiles, hierarchy) for s in scenes}


def roles(count: int) -> list[str]:
    return [f"profile_{n}" for n in range(1, count + 1)]


@pytest.mark.parametrize(
    ("count", "flagged"),
    [(MANY_ROLES_THRESHOLD, False), (MANY_ROLES_THRESHOLD + 1, True)],
)
def test_many_roles_above_threshold(count, flagged):
    result = analyze(scene("home", authenticated=True, allowed_profiles=roles(count)))
    concern = result["home"].security_concern
    assert ("MANY_ROLES" in concern) is flagged
    if flagged:
        assert f"Accessible by {count} different roles" in concern


def test_top_level_login_page_without_roles_is_unrestricted():
    result = analyze(scene("home", authenticated=True))
    assert result["home"].security_concern == (
        "UNRESTRICTED: Requires login but no specific profiles restricted"
    )


def test_dropdown_menu_is_not_an_unrestricted_page():
    # A menu holds links, not content. Every real page in it sets its own
    # access, so flagging the menu itself only buries the pages that matter.
    result = analyze(
        scene("menu", type="menu", authenticated=True),
        scene("page", authenticated=True, menu="menu"),
    )
    assert result["menu"].requires_login is True
    assert result["menu"].security_concern == "OK"
    assert "UNRESTRICTED" in result["page"].security_concern


def test_page_that_names_a_dropdown_menu_as_parent_is_not_behind_its_login():
    # The menu's login decides who sees the menu, not who opens the page. A
    # login-only page under it is where the login starts, so it is flagged;
    # a page with no login of its own is public.
    result = analyze(
        scene("menu", type="menu", authenticated=True),
        scene("members", parent="menu", authenticated=True),
        scene("leaflet", parent="menu"),
    )
    assert result["menu"].security_concern == "OK"
    assert "UNRESTRICTED" in result["members"].security_concern
    assert result["members"].inherits_security is False
    assert result["leaflet"].requires_login is False
    assert "PUBLIC" in result["leaflet"].security_concern


def test_menu_scene_with_views_of_its_own_is_still_a_page():
    result = analyze(
        scene(
            "menu",
            type="menu",
            authenticated=True,
            views=[{"key": "view_1", "name": "Notice", "type": "rich_text"}],
        )
    )
    assert "UNRESTRICTED" in result["menu"].security_concern


@pytest.mark.parametrize("authenticated", [True, False, None])
def test_utility_page_needs_a_login_whatever_its_flag_says(authenticated):
    # Knack's docs: utility pages sit in the user menu and are open to "all
    # logged-in users" or to specific roles. One with no role list is not
    # public, and not a finding either.
    result = analyze(scene("account", type="user", authenticated=authenticated))
    assert result["account"].requires_login is True
    assert result["account"].security_concern == (
        "UTILITY PAGE: In the logged-in user's menu, not the page menu"
    )


def test_utility_page_limited_to_roles_lists_them():
    result = analyze(
        scene(
            "account",
            type="user",
            authenticated=True,
            limit_profile_access=True,
            allowed_profiles=["profile_1"],
        )
    )
    assert result["account"].allowed_profiles == ["Role 1"]
    assert "PUBLIC" not in result["account"].security_concern


def test_child_login_page_without_roles_is_not_unrestricted():
    result = analyze(
        scene("parent", authenticated=True),
        scene("child", parent="parent", authenticated=True),
    )
    assert result["child"].security_concern == "OK"
    assert result["child"].inherits_security is False


def test_login_page_below_a_public_page_is_unrestricted():
    # The login starts here, not above, so this is the page to flag. Left as
    # "OK", the row disagreed with the report's own unrestricted count.
    result = analyze(
        scene("root", authenticated=False),
        scene("gate", parent="root", authenticated=True),
        scene(
            "form",
            parent="root",
            authenticated=False,
            views=[{"key": "view_1", "name": "Login", "type": "login"}],
        ),
    )
    for key in ("gate", "form"):
        assert result[key].requires_login is True
        assert result[key].inherits_security is False
        assert result[key].security_concern == (
            "UNRESTRICTED: Requires login but no specific profiles restricted"
        )


def test_public_page_says_whether_it_has_a_parent():
    result = analyze(scene("root"), scene("child", parent="root"))
    assert result["root"].security_concern == (
        "PUBLIC: Accessible without login (no parent)"
    )
    assert result["child"].security_concern == (
        "PUBLIC: Accessible without login (parent also public)"
    )


def test_page_without_its_own_login_inherits_the_parents():
    result = analyze(
        scene("parent", authenticated=True), scene("child", parent="parent")
    )
    child = result["child"]
    assert child.requires_login is True
    assert child.inherits_security is True
    assert child.security_concern == (
        "Inherits security from parent/ancestor: Parent (parent)"
    )


def test_roles_are_inherited_from_a_restricted_parent():
    result = analyze(
        scene("parent", authenticated=True, allowed_profiles=roles(2)),
        scene("child", parent="parent", authenticated=True),
    )
    assert result["child"].allowed_profiles == ["Role 1", "Role 2"]
    assert result["child"].inherits_security is True
