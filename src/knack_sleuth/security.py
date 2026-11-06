"""Security analysis for Knack applications.

This module provides functions to analyze which user profiles (roles) can
access which scenes (pages) in a Knack application.
"""

from collections import defaultdict
from typing import Any

from knack_sleuth.models import Application, Scene, SceneSecurity, SecurityReport


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


def build_navigation_hierarchy(scenes: list[Scene]) -> dict[str, Any]:
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
    menu_scenes = [s for s in scenes if s.type == 'menu']
    
    # Group scenes by their menu (using extra attributes if they exist)
    scenes_by_menu = defaultdict(list)
    for scene in scenes:
        # Access menu via model_extra if available
        menu_ref = scene.model_extra.get('menu') if hasattr(scene, 'model_extra') and scene.model_extra else None
        if menu_ref:
            scenes_by_menu[menu_ref].append(scene)
    
    return {
        'scenes_by_key': scenes_by_key,
        'scenes_by_slug': dict(scenes_by_slug),
        'menu_scenes': menu_scenes,
        'scenes_by_menu': scenes_by_menu,
    }


def _get_allowed_profile_keys(scene: Scene) -> list[str]:
    """Return direct scene/view profile restrictions in stable order."""
    allowed_profiles: list[str] = []
    if scene.model_extra:
        allowed_profiles = scene.model_extra.get('allowed_profiles', []) or []
        if not allowed_profiles:
            allowed_profiles = scene.model_extra.get('profile_keys', []) or []

    if allowed_profiles:
        return list(dict.fromkeys(allowed_profiles))

    view_profiles = []
    for view in scene.views:
        if view.model_extra:
            view_profiles.extend(view.model_extra.get('allowed_profiles', []) or [])
    return list(dict.fromkeys(view_profiles))


def _scene_label(scene: Scene) -> str:
    """Name a scene unambiguously; duplicate slugs make names alone useless."""
    return f"{scene.name} ({scene.key})"


def _resolve_scene_by_slug(
    slug: str,
    hierarchy: dict[str, Any],
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
    cache = hierarchy.setdefault('_resolved_slugs', {})
    resolved = cache.get(slug)
    if resolved is None:
        candidates = hierarchy['scenes_by_slug'].get(slug, [])
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


def _solve_inheritance(hierarchy: dict[str, Any]) -> dict[str, _Found]:
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
    cached = hierarchy.get('_inherited_restrictions')
    if cached is not None:
        return cached

    scenes_by_slug: dict[str, list[Scene]] = hierarchy['scenes_by_slug']
    own_profiles = {
        candidate.key: tuple(_get_allowed_profile_keys(candidate))
        for candidates in scenes_by_slug.values()
        for candidate in candidates
    }

    # Every slug, parents before children. A parent that is still open on the
    # DFS path is a back edge: the slug graph has a cycle, and one sweep is
    # not enough.
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

    values: dict[str, _Found] = {slug: {} for slug in order}
    sizes: dict[str, int] = {slug: 0 for slug in order}
    # Login-only scenes whose every route upward only loops: their own login
    # stands, as it would at the top of a chain.
    looping_logins: set[str] = set()

    def solve(slug: str) -> _Found:
        found: _Found = {}
        for candidate in scenes_by_slug[slug]:
            label = _scene_label(candidate)
            profiles = own_profiles[candidate.key]
            if profiles:
                found.setdefault((profiles, False), {}).setdefault(label)
                continue
            # A bare login requirement does not end the walk: the scene still
            # sits behind every ancestor, so a login page above it that limits
            # profiles still decides which roles get in (issue #27).
            bare_auth = candidate.authenticated is True
            if candidate.key in looping_logins:
                found.setdefault(((), True), {}).setdefault(label)
            # An unsolved parent (only possible inside a cycle) is an empty
            # dict here and contributes nothing on this sweep.
            inherited = values.get(candidate.parent, _TOP_OF_CHAIN)
            for (inherited_profiles, inherited_auth), inherited_labels in inherited.items():
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

    def sweep() -> bool:
        changed = False
        for slug in order:
            solved = solve(slug)
            # Sweeps only ever add, so a size change is a change.
            size = sum(len(labels) for labels in solved.values()) + len(solved)
            if size != sizes[slug]:
                changed = True
                sizes[slug] = size
            values[slug] = solved
        return changed

    sweep()
    # Parents-first order makes one sweep exact on an acyclic graph, and no
    # route can loop there, so the fixpoint iteration only runs for cycles.
    while cyclic:
        while sweep():
            pass
        newly_looping = {
            candidate.key
            for slug in order
            for candidate in scenes_by_slug[slug]
            if candidate.authenticated is True
            and not own_profiles[candidate.key]
            and candidate.parent in values
            and not values[candidate.parent]
        } - looping_logins
        if not newly_looping:
            break
        looping_logins |= newly_looping

    hierarchy['_inherited_restrictions'] = values
    return values


def _inherited_restrictions(start_slug: str, hierarchy: dict[str, Any]) -> list[Restriction]:
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


def _walk_ancestors(
    parent_slug: str,
    hierarchy: dict[str, Any],
) -> tuple[list[str], str | None, str | None]:
    """Walk the parent chain once for everything a navigation path needs.

    Returns the ancestor labels root-first, the name of the nearest menu an
    ancestor belongs to, and the label of the top-most ancestor (the root
    login page for a "Direct" chain). A slug that does not resolve ends the
    chain with the slug itself, and a repeated slug ends it silently.
    """
    scenes_by_key = hierarchy['scenes_by_key']
    chain: list[str] = []
    menu_name: str | None = None
    root_login_name: str | None = None
    current_slug: str | None = parent_slug
    visited_slugs: set[str] = set()

    while current_slug and current_slug not in visited_slugs:
        visited_slugs.add(current_slug)
        current_scene, current_label = _resolve_scene_by_slug(current_slug, hierarchy)
        if not current_scene:
            chain.append(current_slug)
            break
        chain.append(current_label)
        if not current_scene.parent:
            root_login_name = current_label
        if menu_name is None:
            menu_ref = current_scene.model_extra.get('menu') if current_scene.model_extra else None
            menu_scene = scenes_by_key.get(menu_ref) if menu_ref else None
            if menu_scene:
                menu_name = menu_scene.name
        current_slug = current_scene.parent

    chain.reverse()
    return chain, menu_name, root_login_name


def build_navigation_path(scene: Scene, hierarchy: dict[str, Any]) -> dict[str, str]:
    """Build navigation path for a scene showing menu > parent > page.
    
    Args:
        scene: Scene to analyze
        hierarchy: Navigation hierarchy from build_navigation_hierarchy()
        
    Returns:
        Dict with root_nav, page_nav, nav_level
    """
    scenes_by_key = hierarchy['scenes_by_key']
    scene_name = scene.name
    scene_type = scene.type
    parent_slug = scene.parent
    
    # Get menu reference from extra attributes
    menu_ref = scene.model_extra.get('menu') if hasattr(scene, 'model_extra') and scene.model_extra else None
    
    # Determine root navigation
    root_nav = "Direct"
    root_scene_name = None  # Track root login page for Direct pages
    
    # If this scene IS a menu, use its own name
    if scene_type == 'menu':
        root_nav = scene_name
    elif menu_ref:
        menu_scene = scenes_by_key.get(menu_ref)
        if menu_scene:
            root_nav = menu_scene.name
    
    # If no direct menu but has parent, walk up parent chain to find menu or root login page
    parent_chain: list[str] = []
    if parent_slug:
        parent_chain, menu_name, root_login_name = _walk_ancestors(parent_slug, hierarchy)
        if root_nav == "Direct":
            if menu_name:
                root_nav = menu_name
            elif root_login_name:
                root_scene_name = root_login_name

    # If this scene itself is a top-level (no parent, no menu) authentication page, use its name
    if root_nav == "Direct" and not parent_slug and scene_type == 'authentication':
        root_scene_name = scene_name
    
    # Use root_scene_name for Direct pages if available, or "Utility Page" for utility pages
    if scene_type == 'user':
        display_root_nav = "Utility Page"
    else:
        display_root_nav = root_scene_name if root_scene_name else root_nav
    
    # Determine navigation level
    if scene_type == 'menu':
        nav_level = "Menu"
        page_nav = scene_name
    elif parent_slug:
        nav_level = "Child"
        # Build path: [Menu/Root >] Grandparent > Parent > Page
        if root_nav != "Direct":
            page_nav = f"{root_nav} > {' > '.join(parent_chain)} > {scene_name}"
        elif root_scene_name:
            page_nav = f"{' > '.join(parent_chain)} > {scene_name}"
        else:
            page_nav = f"{' > '.join(parent_chain)} > {scene_name}"
    else:
        nav_level = "Top-Level"
        if root_nav != "Direct":
            page_nav = f"{root_nav} > {scene_name}"
        elif root_scene_name:
            page_nav = scene_name
        else:
            page_nav = scene_name
    
    return {
        'root_nav': display_root_nav,
        'page_nav': page_nav,
        'nav_level': nav_level,
    }


def analyze_scene_security(
    scene: Scene,
    profiles: dict[str, str],
    hierarchy: dict[str, Any]
) -> SceneSecurity:
    """Analyze security settings for a single scene with navigation context.
    
    Args:
        scene: Scene to analyze
        profiles: Mapping of profile_key -> profile_name
        hierarchy: Navigation hierarchy from build_navigation_hierarchy()
        
    Returns:
        SceneSecurity model with complete analysis
    """
    scene_key = scene.key
    scene_name = scene.name
    scene_slug = scene.slug
    scene_type = scene.type or 'N/A'
    is_utility_page = scene_type == 'user'
    parent_slug = scene.parent
    
    # Build navigation path
    nav_info = build_navigation_path(scene, hierarchy)
    
    # Check authentication requirement
    authenticated = scene.authenticated
    
    # Get direct scene/view restrictions.
    allowed_profile_keys = _get_allowed_profile_keys(scene)
    
    # Check parent security
    has_parent = bool(parent_slug)
    inherits_security = False
    inherited_from_name = None
    # Only a profile restriction is final. A bare authenticated=True still
    # inherits any profile restriction from a login page above it (issue #27).
    has_own_security = bool(allowed_profile_keys)
    
    ambiguous_parents = None
    if has_parent and not has_own_security:
        restrictions = _inherited_restrictions(parent_slug, hierarchy)
        # Least restrictive branches win. If any route to this scene is
        # unprotected, that is the finding; a stricter sibling route must not
        # mask it and report the scene as safe. Where the weakest branches are
        # role-restricted to *different* roles, access is the union of them --
        # picking one would hide the other role's route.
        weakest = min(_restriction_strength(r) for r in restrictions)
        effective = [r for r in restrictions if _restriction_strength(r) == weakest]
        inherited_profiles = tuple(
            dict.fromkeys(profile for profiles, _, _ in effective for profile in profiles)
        )
        inherited_auth = any(authenticated for _, authenticated, _ in effective)
        inherited_from_name = " / ".join(
            dict.fromkeys(label for _, _, label in effective if label)
        ) or None
        if len(restrictions) > 1:
            ambiguous_parents = " / ".join(
                sorted(label for _, _, label in restrictions if label)
            )

        # A scene that already demands login only "inherits" when the
        # ancestor adds something: a profile restriction.
        if inherited_profiles or (inherited_auth and authenticated is not True):
            inherits_security = True
            allowed_profile_keys = list(inherited_profiles)
            if authenticated is None:
                authenticated = inherited_auth
        else:
            inherited_from_name = None
    
    # Map profile keys to names
    allowed_profile_names = [profiles.get(pk, pk) for pk in allowed_profile_keys]
    
    # Determine if login is required (considering inheritance and profiles)
    requires_login = authenticated is True or bool(allowed_profile_keys) or inherits_security
    
    # Security concerns
    concerns = []
    
    if is_utility_page:
        concerns.append("UTILITY PAGE: Requires Knack system-level account (beyond app profiles)")

    if ambiguous_parents:
        # The fork is not necessarily at parent_slug -- it can be any duplicate
        # slug further up -- so name the disagreeing scenes, not a slug.
        concerns.append(
            f"AMBIGUOUS PARENT: ancestors reached via {parent_slug!r} disagree on "
            f"security ({ambiguous_parents}); reporting the least restrictive access"
        )

    # Public = does not require login
    if not requires_login and not has_parent:
        concerns.append("PUBLIC: Accessible without login (no parent)")
    elif not requires_login and has_parent:
        concerns.append("PUBLIC: Accessible without login (parent also public)")
    
    # Unrestricted = requires login but no specific roles
    if requires_login and not allowed_profile_keys and not has_parent and not is_utility_page:
        concerns.append("UNRESTRICTED: Requires login but no specific profiles restricted")
    
    if len(allowed_profile_names) > 5:
        concerns.append(f"MANY_ROLES: Accessible by {len(allowed_profile_names)} different roles")
    
    security_note = ""
    if inherits_security:
        security_note = f"Inherits security from parent/ancestor: {inherited_from_name}"
    
    security_concern = "; ".join(concerns) if concerns else security_note or "OK"

    # Extract all view names and keys from this scene
    view_names = [view.name for view in scene.views]
    view_keys = [view.key for view in scene.views]

    return SceneSecurity(
        root_nav=nav_info['root_nav'],
        scene_name=scene_name,
        nav_level=nav_info['nav_level'],
        allowed_profile_count=len(allowed_profile_names),
        allowed_profiles=allowed_profile_names,
        page_nav=nav_info['page_nav'],
        scene_key=scene_key,
        scene_slug=scene_slug,
        scene_type=scene_type,
        security_concern=security_concern,
        requires_login=requires_login,
        inherits_security=inherits_security,
        view_names=view_names,
        view_keys=view_keys,
    )


def count_children(scene_key: str, all_scenes: list[SceneSecurity]) -> int:
    """Count how many child pages a scene has.
    
    Args:
        scene_key: The scene key to count children for
        all_scenes: All scene security analyses
        
    Returns:
        Count of child scenes
    """
    parent_scene = next((s for s in all_scenes if s.scene_key == scene_key), None)
    if parent_scene is None:
        return 0
    # Check if this scene's page_nav contains the parent's name. This is a
    # simplified check - could be more sophisticated. "Child" makes sure it is
    # actually a descendant, not just mentioned in the path.
    return sum(
        1
        for scene in all_scenes
        if scene.scene_key != scene_key
        and scene.nav_level == "Child"
        and parent_scene.scene_name in scene.page_nav
    )


def get_views_for_profile(scene: Scene, profile_key: str, profile_name: str) -> tuple[list[str], list[str]]:
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

    # Check scene-level security first
    scene_allowed_profiles = []
    if hasattr(scene, 'model_extra') and scene.model_extra:
        scene_allowed_profiles = scene.model_extra.get('allowed_profiles', [])

    # If scene has no restrictions, all views are accessible (if no view-level restrictions)
    # If scene has restrictions, profile must be in the list
    scene_accessible = not scene_allowed_profiles or profile_key in scene_allowed_profiles

    for view in scene.views:
        view_accessible = False

        # Check view-level security
        view_allowed_profiles = []
        limit_profile_access = False

        if hasattr(view, 'model_extra') and view.model_extra:
            view_allowed_profiles = view.model_extra.get('allowed_profiles', [])
            limit_profile_access = view.model_extra.get('limit_profile_access', False)

        if limit_profile_access and view_allowed_profiles:
            # View has explicit restrictions
            view_accessible = profile_key in view_allowed_profiles
        elif scene_accessible:
            # View inherits scene-level access (no view-level restrictions)
            view_accessible = True

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

    scene_analyses = []
    for scene in app.scenes:
        analysis = analyze_scene_security(scene, profiles, hierarchy)
        scene_analyses.append(analysis)

    # Sort by navigation path for better readability
    # Put "Direct" and "Utility Page" pages after menu pages
    def sort_key(scene: SceneSecurity) -> tuple:
        root_nav = scene.root_nav
        # Put "Direct" at the end by prepending "zzz_" for sorting
        if root_nav == "Direct":
            return ("zzz_Direct", scene.page_nav)
        elif root_nav == "Utility Page":
            return ("zzzz_Utility Page", scene.page_nav)
        return (root_nav, scene.page_nav)

    scene_analyses.sort(key=sort_key)

    # Calculate summary statistics
    total_scenes = len(scene_analyses)
    public_scenes = sum(1 for s in scene_analyses if not s.requires_login)
    login_required = sum(1 for s in scene_analyses if s.requires_login)
    unrestricted_auth = sum(1 for s in scene_analyses if s.requires_login and s.allowed_profile_count == 0)
    scenes_with_parents = sum(1 for s in scene_analyses if s.nav_level == "Child")
    scenes_inheriting_security = sum(1 for s in scene_analyses if s.inherits_security)
    menu_scenes = sum(1 for s in scene_analyses if s.nav_level == 'Menu')
    utility_pages = sum(1 for s in scene_analyses if s.scene_type == 'user')

    # Profile access summary
    profile_access = defaultdict(int)
    for scene in scene_analyses:
        for profile in scene.allowed_profiles:
            profile_access[profile] += 1

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
