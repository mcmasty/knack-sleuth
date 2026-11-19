"""Security analysis for Knack applications.

This module provides functions to analyze which user profiles (roles) can
access which scenes (pages) in a Knack application.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, NamedTuple, NotRequired, TypedDict

from pydantic import BaseModel

from knack_sleuth.models import Application, Scene, SceneSecurity, SecurityReport

# Pages open to more roles than this get a MANY_ROLES concern.
MANY_ROLES_THRESHOLD = 5


def _extra(model: BaseModel) -> dict[str, Any]:
    """Fields Knack sends that the model does not declare (``extra="allow"``)."""
    return model.model_extra or {}


def _menu_ref(scene: Scene) -> str | None:
    """The key of the menu a scene says it belongs to, if it is a key at all.

    ``menu`` is undeclared metadata, so it can hold anything; a list or dict
    there must read as "no menu", not crash a dictionary lookup.
    """
    menu = _extra(scene).get("menu")
    return menu if isinstance(menu, str) and menu else None


def _menu_name(scene: Scene, scenes_by_key: dict[str, Scene]) -> str | None:
    """Name of the menu a scene belongs to, if its ``menu`` reference resolves."""
    menu_scene = scenes_by_key.get(_menu_ref(scene) or "")
    return menu_scene.name if menu_scene else None


def get_profile_mapping(app: Application) -> dict[str, str]:
    """Extract user profile (role) information from objects.

    Args:
        app: Knack application metadata

    Returns:
        Dict mapping profile_key -> profile_name
    """
    profiles = {}
    for obj in app.objects:
        if obj.user and obj.profile_key:
            profiles[obj.profile_key] = obj.name
    return profiles


class NavigationHierarchy(TypedDict):
    """What ``build_navigation_hierarchy`` returns: the scenes, indexed.

    The two underscore keys are caches the analysis adds as it goes; a
    hierarchy is built once per report and reused for every scene.
    """

    scenes_by_key: dict[str, Scene]
    # Slugs are path-scoped in Knack, so one slug can name several scenes.
    scenes_by_slug: dict[str, list[Scene]]
    menu_scenes: list[Scene]
    scenes_by_menu: dict[str, list[Scene]]
    _resolved_slugs: NotRequired[dict[str, tuple[Scene | None, str | None]]]
    _inherited_restrictions: NotRequired[dict[str, "_Found"]]


def build_navigation_hierarchy(scenes: list[Scene]) -> NavigationHierarchy:
    """Build navigation hierarchy showing menu > page relationships.

    Args:
        scenes: List of scenes from the application

    Returns:
        Dict with scenes_by_key, scenes_by_slug, menu_scenes, scenes_by_menu.
        ``scenes_by_slug`` maps each slug to every matching scene so duplicate
        slugs remain visible instead of silently overwriting an earlier scene.
    """
    scenes_by_key = {s.key: s for s in scenes}
    scenes_by_slug = defaultdict(list)
    for scene in scenes:
        scenes_by_slug[scene.slug].append(scene)

    # Find menu scenes
    menu_scenes = [s for s in scenes if s.type == "menu"]

    # Group scenes by their menu (using extra attributes if they exist)
    scenes_by_menu = defaultdict(list)
    for scene in scenes:
        menu_ref = _menu_ref(scene)
        if menu_ref:
            scenes_by_menu[menu_ref].append(scene)

    return {
        "scenes_by_key": scenes_by_key,
        "scenes_by_slug": dict(scenes_by_slug),
        "menu_scenes": menu_scenes,
        "scenes_by_menu": scenes_by_menu,
    }


def _scene_profile_limit(scene: Scene) -> list[Any]:
    """The profiles a scene itself is limited to, as Knack would enforce them.

    Knack keeps the list when "limit access to roles" is switched off, so a
    list beside ``limit_profile_access: false`` restricts nothing. Metadata
    without the flag (and the older ``profile_keys``) is taken at its word.
    """
    extra = _extra(scene)
    if extra.get("limit_profile_access") is False:
        return []
    return extra.get("allowed_profiles") or extra.get("profile_keys") or []


def _view_profile_limit(view: BaseModel) -> list[Any]:
    """The profiles a view is limited to; none unless the limit is switched on."""
    extra = _extra(view)
    if not extra.get("limit_profile_access"):
        return []
    return extra.get("allowed_profiles") or []


def _asks_for_login(scene: Scene) -> bool | None:
    """Whether the scene itself demands a login, whoever may then log in.

    A login view is a login gate even when its role limit is switched off, and
    Knack does not always set ``authenticated`` on the page that carries it.
    A utility page (type ``user``) is open to all logged-in users, or to the
    roles it names, and never to the public.
    Otherwise the scene's own flag stands, None (absent) included.
    """
    if scene.authenticated is True:
        return True
    if any(view.type == "login" for view in scene.views):
        return True
    # A utility page lives in the user menu, which only a logged-in user has.
    if scene.type == "user":
        return True
    return scene.authenticated


def _gates_what_is_below(scene: Scene) -> bool:
    """Whether the scene's own login protects the pages under it.

    A dropdown menu's login decides who sees the menu. It is not a page a
    visitor passes through, so a page that names it as parent is not behind
    that login: the page's own settings are what count.
    """
    return _asks_for_login(scene) is True and not is_dropdown_menu(
        scene.type, scene.views
    )


def _get_allowed_profile_keys(scene: Scene) -> list[str]:
    """Return direct scene/view profile restrictions in stable order."""
    allowed_profiles = _scene_profile_limit(scene)
    if not allowed_profiles:
        allowed_profiles = [
            profile for view in scene.views for profile in _view_profile_limit(view)
        ]
    # A null entry restricts nothing; keeping it would fail SceneSecurity.
    return [key for key in dict.fromkeys(allowed_profiles) if isinstance(key, str)]


def _scene_label(scene: Scene) -> str:
    """Name a scene unambiguously; duplicate slugs make names alone useless."""
    return f"{scene.name} ({scene.key})"


def _resolve_scene_by_slug(
    slug: str,
    hierarchy: NavigationHierarchy,
) -> tuple[Scene | None, str | None]:
    """Resolve a slug for *navigation* display without discarding duplicates.

    Knack slugs are path-scoped, so one slug legitimately maps to several
    scenes. Navigation output is descriptive rather than a security claim:
    disclose every candidate in the label and continue the walk from the first
    so the path stays deterministic. Security inheritance does not come through
    here -- see ``_inherited_restrictions``, which explores every branch.
    """
    # Cached per slug: a path walk resolves the same slugs for every scene
    # under it, and a heavily duplicated slug has a long label to join.
    cache = hierarchy.setdefault("_resolved_slugs", {})
    resolved = cache.get(slug)
    if resolved is None:
        candidates = hierarchy["scenes_by_slug"].get(slug, [])
        if not candidates:
            resolved = (None, None)
        elif len(candidates) == 1:
            resolved = (candidates[0], candidates[0].name)
        else:
            label = " / ".join(_scene_label(scene) for scene in candidates)
            resolved = (candidates[0], label)
        cache[slug] = resolved
    return resolved


# (allowed profile keys, requires authentication, where it came from)
Restriction = tuple[tuple[str, ...], bool, str | None]


def _restriction_strength(restriction: Restriction) -> int:
    """Order restrictions from most permissive to most restrictive."""
    profiles, authenticated, _ = restriction
    if profiles:
        return 2
    return 1 if authenticated else 0


# (profiles, bare login) -> labels; a dict keeps discovery order with O(1) dedupe
_Found = dict[tuple[tuple[str, ...], bool], dict[str, None]]
# What a scene inherits above the top of a chain, or past a dangling parent
# reference: no restriction, and no label (the scene names itself).
_TOP_OF_CHAIN: _Found = {((), False): {}}


def _parents_first_order(
    scenes_by_slug: dict[str, list[Scene]],
) -> tuple[list[str], bool]:
    """Every slug with its parents before it, and whether the graph has a cycle.

    A parent that is still open on the DFS path is a back edge: the slug graph
    has a cycle, and one sweep in this order is not enough.
    """
    order: list[str] = []
    seen: set[str] = set()
    finished: set[str] = set()
    cyclic = False
    for root in scenes_by_slug:
        stack: list[tuple[str, bool]] = [(root, False)]
        while stack:
            slug, expanded = stack.pop()
            if expanded:
                order.append(slug)
                finished.add(slug)
                continue
            if slug in seen:
                continue
            seen.add(slug)
            stack.append((slug, True))
            for candidate in reversed(scenes_by_slug[slug]):
                parent = candidate.parent
                if not parent or parent not in scenes_by_slug:
                    continue
                if parent not in seen:
                    stack.append((parent, False))
                elif parent not in finished:
                    cyclic = True
    return order, cyclic


@dataclass
class _InheritanceSolver:
    """The slug equations of one hierarchy, and the solution so far.

    ``values`` and ``looping_logins`` are updated in place: a slug solved
    earlier in a sweep is what the slugs after it read.
    """

    scenes_by_slug: dict[str, list[Scene]]
    # Every slug, parents before children.
    order: list[str]
    # Scene key -> the profiles the scene itself is limited to.
    own_profiles: dict[str, tuple[str, ...]]
    values: dict[str, _Found]
    # Login-only scenes whose every route upward only loops: their own login
    # stands, as it would at the top of a chain.
    looping_logins: set[str] = field(default_factory=set)

    def solve(self, slug: str) -> _Found:
        """One slug's restrictions, from what its parents hold right now."""
        found: _Found = {}
        for candidate in self.scenes_by_slug[slug]:
            label = _scene_label(candidate)
            profiles = self.own_profiles[candidate.key]
            if profiles:
                found.setdefault((profiles, False), {}).setdefault(label)
                continue
            # A bare login requirement does not end the walk: the scene still
            # sits behind every ancestor, so a login page above it that limits
            # profiles still decides which roles get in (issue #27).
            bare_auth = _gates_what_is_below(candidate)
            if candidate.key in self.looping_logins:
                found.setdefault(((), True), {}).setdefault(label)
            # An unsolved parent (only possible inside a cycle) is an empty
            # dict here and contributes nothing on this sweep.
            inherited = (
                self.values.get(candidate.parent, _TOP_OF_CHAIN)
                if candidate.parent
                else _TOP_OF_CHAIN
            )
            for (
                inherited_profiles,
                inherited_auth,
            ), inherited_labels in inherited.items():
                if bare_auth and not inherited_profiles:
                    # Nothing stricter above: this scene's own login is the
                    # restriction, so name it.
                    found.setdefault(((), True), {}).setdefault(label)
                    continue
                # Name this scene when the branch above it named nobody, so
                # an unprotected route can still say where it ran out.
                bucket = found.setdefault((inherited_profiles, inherited_auth), {})
                for inherited_label in inherited_labels or (label,):
                    bucket.setdefault(inherited_label)
        return found

    def sweep(self) -> bool:
        """Re-solve every slug in order; report whether anything changed."""
        changed = False
        for slug in self.order:
            solved = self.solve(slug)
            if solved != self.values[slug]:
                changed = True
            # Store even when equal: dict equality ignores label order, and
            # the report uses the order of the last sweep.
            self.values[slug] = solved
        return changed

    def stranded_logins(self) -> set[str]:
        """Login-only scenes, not yet counted, whose parent solved to nothing."""
        return {
            candidate.key
            for slug in self.order
            for candidate in self.scenes_by_slug[slug]
            if _gates_what_is_below(candidate)
            and not self.own_profiles[candidate.key]
            and candidate.parent in self.values
            and not self.values[candidate.parent]
        } - self.looping_logins


def _solve_inheritance(hierarchy: NavigationHierarchy) -> dict[str, _Found]:
    """Restrictions for every slug, solved once per hierarchy and cached.

    Resolving parents by slug alone can close a cycle (a duplicate slug that
    hangs below its namesake). A recursive walk then has to choose between
    route-dependent memo entries and re-exploring every fork, which doubles per
    level. Instead, solve the slug equations as a fixpoint: each slug's
    restrictions are the union over its scenes, every sweep only adds, so it
    terminates, and a route that only loops contributes nothing. Slugs are
    swept parents-first, so an acyclic graph is exact after one sweep.

    Solving for the whole app at once (rather than per scene) keeps a report
    linear in the number of scenes even when one slug feeds hundreds of labels
    to every descendant.
    """
    cached = hierarchy.get("_inherited_restrictions")
    if cached is not None:
        return cached

    scenes_by_slug: dict[str, list[Scene]] = hierarchy["scenes_by_slug"]
    order, cyclic = _parents_first_order(scenes_by_slug)
    solver = _InheritanceSolver(
        scenes_by_slug=scenes_by_slug,
        order=order,
        own_profiles={
            candidate.key: tuple(_get_allowed_profile_keys(candidate))
            for candidates in scenes_by_slug.values()
            for candidate in candidates
        },
        values={slug: {} for slug in order},
    )

    solver.sweep()
    # Parents-first order makes one sweep exact on an acyclic graph, and no
    # route can loop there, so the fixpoint iteration only runs for cycles.
    while cyclic:
        while solver.sweep():
            pass
        newly_looping = solver.stranded_logins()
        if not newly_looping:
            break
        solver.looping_logins |= newly_looping

    hierarchy["_inherited_restrictions"] = solver.values
    return solver.values


def _inherited_restrictions(
    start_slug: str, hierarchy: NavigationHierarchy
) -> list[Restriction]:
    """Every distinct restriction reachable by walking up from ``start_slug``.

    A duplicate slug forks the ancestor chain. Walking one arbitrary branch can
    attribute a parent's protection to a scene that is also reachable by an
    unprotected route, so explore all branches and let the caller see the
    disagreement. Branches that are security-equivalent collapse into a single
    entry with their labels combined -- differing *names* are not a conflict.
    """
    values = _solve_inheritance(hierarchy)
    if start_slug not in values:
        return [((), False, None)]  # dangling parent reference
    restrictions = [
        (profiles, auth, " / ".join(labels) or None)
        for (profiles, auth), labels in values[start_slug].items()
    ]
    # Every route was a cycle: nothing is actually inherited.
    return restrictions or [((), False, None)]


def _resolve_parent(
    slug: str, hierarchy: NavigationHierarchy, child_key: str | None
) -> tuple[Scene | None, str | None, bool]:
    """Resolve a parent slug for the walk up from the scene ``child_key``.

    As ``_resolve_scene_by_slug``, except that the scene the walk started from
    is never a candidate: a page can share its parent's slug, and when it comes
    first in the export it would otherwise resolve to itself. Returns the
    scene to continue from, its label, and whether the slug exists at all.
    """
    everyone = hierarchy["scenes_by_slug"].get(slug, [])
    others = [scene for scene in everyone if scene.key != child_key]
    if len(others) == len(everyone):
        scene, label = _resolve_scene_by_slug(slug, hierarchy)
        return scene, label, bool(everyone)
    if not others:
        return None, None, True
    label = (
        others[0].name
        if len(others) == 1
        else " / ".join(_scene_label(scene) for scene in others)
    )
    return others[0], label, True


def _walk_ancestors(
    parent_slug: str,
    hierarchy: NavigationHierarchy,
    child_key: str | None = None,
) -> tuple[list[str], str | None, str | None]:
    """Walk the parent chain once for everything a navigation path needs.

    Returns the ancestor labels root-first, the name of the nearest menu an
    ancestor belongs to, and the label of the top-most ancestor (the root
    login page for a "Direct" chain). A slug that does not resolve ends the
    chain with the slug itself, and a repeated slug ends it silently, as does
    a slug that only the starting scene (``child_key``) has.
    """
    scenes_by_key = hierarchy["scenes_by_key"]
    chain: list[str] = []
    menu_name: str | None = None
    root_login_name: str | None = None
    current_slug: str | None = parent_slug
    visited_slugs: set[str] = set()

    while current_slug and current_slug not in visited_slugs:
        visited_slugs.add(current_slug)
        current_scene, current_label, known = _resolve_parent(
            current_slug, hierarchy, child_key
        )
        if not current_scene:
            if not known:
                chain.append(current_slug)
            break
        chain.append(current_label or current_slug)
        if not current_scene.parent:
            root_login_name = current_label
        if menu_name is None:
            menu_name = _menu_name(current_scene, scenes_by_key)
        current_slug = current_scene.parent

    chain.reverse()
    return chain, menu_name, root_login_name


def build_navigation_path(
    scene: Scene, hierarchy: NavigationHierarchy
) -> dict[str, str]:
    """Build navigation path for a scene showing menu > parent > page.

    Args:
        scene: Scene to analyze
        hierarchy: Navigation hierarchy from build_navigation_hierarchy()

    Returns:
        Dict with root_nav, page_nav, nav_level
    """
    scene_name = scene.name
    scene_type = scene.type
    parent_slug = scene.parent

    # Determine root navigation: a menu scene is its own root, otherwise the
    # menu the scene belongs to.
    root_scene_name = None  # Track root login page for Direct pages
    if scene_type == "menu":
        root_nav = scene_name
    else:
        root_nav = _menu_name(scene, hierarchy["scenes_by_key"]) or "Direct"

    # If no direct menu but has parent, walk up parent chain to find menu or root login page
    parent_chain: list[str] = []
    if parent_slug:
        parent_chain, menu_name, root_login_name = _walk_ancestors(
            parent_slug, hierarchy, scene.key
        )
        if root_nav == "Direct":
            if menu_name:
                root_nav = menu_name
            elif root_login_name:
                root_scene_name = root_login_name

    # If this scene itself is a top-level (no parent, no menu) authentication page, use its name
    if root_nav == "Direct" and not parent_slug and scene_type == "authentication":
        root_scene_name = scene_name

    # Use root_scene_name for Direct pages if available, or "Utility Page" for utility pages
    if scene_type == "user":
        display_root_nav = "Utility Page"
    else:
        display_root_nav = root_scene_name or root_nav

    # Navigation level and path: [Menu/Root >] Grandparent > Parent > Page
    if scene_type == "menu":
        nav_level = "Menu"
        page_nav = scene_name
    else:
        nav_level = "Child" if parent_slug else "Top-Level"
        page_nav = " > ".join([*parent_chain, scene_name])
        if root_nav != "Direct":
            page_nav = f"{root_nav} > {page_nav}"

    return {
        "root_nav": display_root_nav,
        "page_nav": page_nav,
        "nav_level": nav_level,
    }


def _ancestor_keys(scene: Scene, hierarchy: NavigationHierarchy) -> list[str]:
    """Keys of the scenes above ``scene``, nearest first, then its menu.

    Follows the same route as the navigation path: parents by slug, continuing
    from the first scene of a duplicate slug, and the nearest menu on the way
    up. Every scene sharing a duplicate slug is included, as each of them is
    named in the path. A menu reference that points at no scene is skipped,
    as the path skips it, so a menu further up is still found.
    """
    scenes_by_key = hierarchy["scenes_by_key"]

    def menu_of(member: Scene) -> str | None:
        ref = _menu_ref(member)
        return ref if ref in scenes_by_key else None

    keys: dict[str, None] = {}
    menu_key = menu_of(scene)
    slug = scene.parent
    visited: set[str] = set()
    while slug and slug not in visited:
        visited.add(slug)
        # The scene is never its own ancestor, even where it shares the slug.
        candidates = [
            candidate
            for candidate in hierarchy["scenes_by_slug"].get(slug, [])
            if candidate.key != scene.key
        ]
        if not candidates:
            break
        for candidate in candidates:
            keys.setdefault(candidate.key)
        menu_key = menu_key or menu_of(candidates[0])
        slug = candidates[0].parent
    if menu_key:
        keys.setdefault(menu_key)
    return list(keys)


class _Access(NamedTuple):
    """Who can open a scene once inheritance from its ancestors is applied."""

    profile_keys: list[str]
    authenticated: bool | None
    inherits: bool
    inherited_from: str | None
    ambiguous_parents: str | None  # labels of disagreeing ancestors, if any
    # Nothing above asks for a login: a top-level page, or one whose least
    # restricted route up is public. A login here is where the gate starts.
    ancestors_public: bool = True


def _effective_access(scene: Scene, hierarchy: NavigationHierarchy) -> _Access:
    """The scene's own restriction, or what it inherits from above.

    Only a profile restriction is final. A bare authenticated=True still
    inherits any profile restriction from a login page above it (issue #27).
    """
    allowed = _get_allowed_profile_keys(scene)
    authenticated = _asks_for_login(scene)
    if not scene.parent or allowed:
        return _Access(allowed, authenticated, False, None, None)

    restrictions = _inherited_restrictions(scene.parent, hierarchy)
    # Least restrictive branches win. If any route to this scene is
    # unprotected, that is the finding; a stricter sibling route must not
    # mask it and report the scene as safe. Where the weakest branches are
    # role-restricted to *different* roles, access is the union of them --
    # picking one would hide the other role's route.
    weakest = min(_restriction_strength(r) for r in restrictions)
    effective = [r for r in restrictions if _restriction_strength(r) == weakest]
    inherited_profiles = list(
        dict.fromkeys(profile for profiles, _, _ in effective for profile in profiles)
    )
    inherited_auth = any(auth for _, auth, _ in effective)
    ambiguous = None
    if len(restrictions) > 1:
        ambiguous = " / ".join(sorted(label for _, _, label in restrictions if label))

    # A scene that already demands login only "inherits" when the ancestor
    # adds something: a profile restriction.
    if inherited_profiles or (inherited_auth and authenticated is not True):
        inherited_from = (
            " / ".join(dict.fromkeys(label for _, _, label in effective if label))
            or None
        )
        return _Access(
            inherited_profiles, authenticated, True, inherited_from, ambiguous, False
        )
    return _Access(allowed, authenticated, False, None, ambiguous, weakest == 0)


def is_dropdown_menu(scene_type: str | None, views: list[Any]) -> bool:
    """A menu scene with no views of its own: a list of links to other pages."""
    return scene_type == "menu" and not views


def _security_concerns(
    scene: Scene, access: _Access, requires_login: bool, role_count: int
) -> list[str]:
    """The findings to flag for one scene, in report order."""
    has_parent = bool(scene.parent)
    is_utility_page = scene.type == "user"
    concerns = []
    if is_utility_page:
        concerns.append("UTILITY PAGE: In the logged-in user's menu, not the page menu")
    if access.ambiguous_parents:
        # The fork is not necessarily at the parent slug -- it can be any
        # duplicate slug further up -- so name the disagreeing scenes.
        concerns.append(
            f"AMBIGUOUS PARENT: ancestors reached via {scene.parent!r} disagree on "
            f"security ({access.ambiguous_parents}); reporting the least "
            "restrictive access"
        )
    if not requires_login:
        where = "parent also public" if has_parent else "no parent"
        concerns.append(f"PUBLIC: Accessible without login ({where})")
    # A login with no role list, at the point where the login starts. A page
    # below a login-only page is covered by the flag on that page.
    # A dropdown menu is navigation, not a page: there is nothing on it to
    # open, and each page in it sets its own access.
    elif (
        not access.profile_keys
        and access.ancestors_public
        and not is_utility_page
        and not is_dropdown_menu(scene.type, scene.views)
    ):
        concerns.append(
            "UNRESTRICTED: Requires login but no specific profiles restricted"
        )
    if role_count > MANY_ROLES_THRESHOLD:
        concerns.append(f"MANY_ROLES: Accessible by {role_count} different roles")
    return concerns


def analyze_scene_security(
    scene: Scene, profiles: dict[str, str], hierarchy: NavigationHierarchy
) -> SceneSecurity:
    """Analyze security settings for a single scene with navigation context.

    Args:
        scene: Scene to analyze
        profiles: Mapping of profile_key -> profile_name
        hierarchy: Navigation hierarchy from build_navigation_hierarchy()

    Returns:
        SceneSecurity model with complete analysis
    """
    nav_info = build_navigation_path(scene, hierarchy)
    access = _effective_access(scene, hierarchy)
    allowed_profile_names = [profiles.get(pk, pk) for pk in access.profile_keys]
    requires_login = (
        access.authenticated is True or bool(access.profile_keys) or access.inherits
    )

    concerns = _security_concerns(
        scene, access, requires_login, len(allowed_profile_names)
    )
    security_note = ""
    if access.inherits:
        security_note = (
            f"Inherits security from parent/ancestor: {access.inherited_from}"
        )
    security_concern = "; ".join(concerns) if concerns else security_note or "OK"

    return SceneSecurity(
        root_nav=nav_info["root_nav"],
        scene_name=scene.name,
        nav_level=nav_info["nav_level"],
        allowed_profile_count=len(allowed_profile_names),
        allowed_profiles=allowed_profile_names,
        page_nav=nav_info["page_nav"],
        scene_key=scene.key,
        scene_slug=scene.slug,
        scene_type=scene.type or "N/A",
        security_concern=security_concern,
        requires_login=requires_login,
        inherits_security=access.inherits,
        ancestor_keys=_ancestor_keys(scene, hierarchy),
        view_names=[view.name for view in scene.views],
        view_keys=[view.key for view in scene.views],
    )


def count_children(scene_key: str, all_scenes: list[SceneSecurity]) -> int:
    """Count the pages below a scene, at any depth.

    For a menu these are the pages below its member pages; the member pages
    themselves are top-level and are not counted.

    Args:
        scene_key: The scene key to count children for
        all_scenes: All scene security analyses

    Returns:
        Count of descendant scenes
    """
    return sum(
        1
        for scene in all_scenes
        if scene.nav_level == "Child" and scene_key in scene.ancestor_keys
    )


def get_views_for_profile(
    scene: Scene, profile_key: str, profile_name: str
) -> tuple[list[str], list[str]]:
    """Get views accessible by a specific profile on a scene.

    Args:
        scene: Scene to analyze
        profile_key: Profile key (e.g., "profile_1")
        profile_name: Profile name (e.g., "Admin")

    Returns:
        Tuple of (view_names, view_keys) that the profile can access
    """
    accessible_views_names = []
    accessible_views_keys = []

    # If scene has no restrictions, all views are accessible (if no view-level restrictions)
    # If scene has restrictions, profile must be in the list
    scene_allowed_profiles = _scene_profile_limit(scene)
    scene_accessible = (
        not scene_allowed_profiles or profile_key in scene_allowed_profiles
    )

    for view in scene.views:
        view_allowed_profiles = _view_profile_limit(view)
        if view_allowed_profiles:
            # View has explicit restrictions
            view_accessible = profile_key in view_allowed_profiles
        else:
            # View inherits scene-level access (no view-level restrictions)
            view_accessible = scene_accessible

        if view_accessible:
            accessible_views_names.append(view.name)
            accessible_views_keys.append(view.key)

    return accessible_views_names, accessible_views_keys


def generate_security_report(app: Application) -> SecurityReport:
    """Generate comprehensive security report for an application.

    Args:
        app: Knack application metadata

    Returns:
        SecurityReport with complete analysis
    """
    profiles = get_profile_mapping(app)
    hierarchy = build_navigation_hierarchy(app.scenes)

    scene_analyses = [
        analyze_scene_security(scene, profiles, hierarchy) for scene in app.scenes
    ]

    # Sort by navigation path for better readability
    # Put "Direct" and "Utility Page" pages after menu pages
    def sort_key(scene: SceneSecurity) -> tuple:
        root_nav = scene.root_nav
        # Put "Direct" at the end by prepending "zzz_" for sorting
        if root_nav == "Direct":
            return ("zzz_Direct", scene.page_nav)
        if root_nav == "Utility Page":
            return ("zzzz_Utility Page", scene.page_nav)
        return (root_nav, scene.page_nav)

    scene_analyses.sort(key=sort_key)

    # Calculate summary statistics
    total_scenes = len(scene_analyses)
    public_scenes = sum(1 for s in scene_analyses if not s.requires_login)
    login_required = sum(1 for s in scene_analyses if s.requires_login)
    unrestricted_auth = sum(
        1
        for s in scene_analyses
        if s.requires_login
        and s.allowed_profile_count == 0
        and not is_dropdown_menu(s.scene_type, s.view_keys)
    )
    scenes_with_parents = sum(1 for s in scene_analyses if s.nav_level == "Child")
    scenes_inheriting_security = sum(1 for s in scene_analyses if s.inherits_security)
    menu_scenes = sum(1 for s in scene_analyses if s.nav_level == "Menu")
    utility_pages = sum(1 for s in scene_analyses if s.scene_type == "user")

    # Profile access summary
    profile_access = Counter(
        profile for scene in scene_analyses for profile in scene.allowed_profiles
    )

    return SecurityReport(
        app_name=app.name,
        total_scenes=total_scenes,
        public_scenes=public_scenes,
        login_required_scenes=login_required,
        unrestricted_authenticated_scenes=unrestricted_auth,
        scenes_with_parents=scenes_with_parents,
        scenes_inheriting_security=scenes_inheriting_security,
        menu_scenes=menu_scenes,
        utility_pages=utility_pages,
        total_profiles=len(profiles),
        profiles=profiles,
        profile_access_counts=dict(profile_access),
        scene_analyses=scene_analyses,
    )
