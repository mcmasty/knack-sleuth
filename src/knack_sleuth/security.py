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
        Dict with scenes_by_key, scenes_by_slug, menu_scenes, scenes_by_menu
    """
    scenes_by_key = {s.key: s for s in scenes}
    scenes_by_slug = {s.slug: s for s in scenes}
    
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
        'scenes_by_slug': scenes_by_slug,
        'menu_scenes': menu_scenes,
        'scenes_by_menu': scenes_by_menu,
    }


def build_navigation_path(scene: Scene, hierarchy: dict[str, Any]) -> dict[str, str]:
    """Build navigation path for a scene showing menu > parent > page.
    
    Args:
        scene: Scene to analyze
        hierarchy: Navigation hierarchy from build_navigation_hierarchy()
        
    Returns:
        Dict with root_nav, page_nav, nav_level
    """
    scenes_by_key = hierarchy['scenes_by_key']
    scenes_by_slug = hierarchy['scenes_by_slug']
    
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
    if root_nav == "Direct" and parent_slug:
        current_slug = parent_slug
        root_login_scene = None  # Track the topmost scene (potential login page)
        
        while current_slug and root_nav == "Direct":
            current_scene = scenes_by_slug.get(current_slug)
            if current_scene:
                # Track this as potential root login page
                if not current_scene.parent:
                    root_login_scene = current_scene
                
                # Check for menu in parent
                parent_menu_ref = current_scene.model_extra.get('menu') if hasattr(current_scene, 'model_extra') and current_scene.model_extra else None
                if parent_menu_ref:
                    menu_scene = scenes_by_key.get(parent_menu_ref)
                    if menu_scene:
                        root_nav = menu_scene.name
                        break
                # Move to next parent
                current_slug = current_scene.parent
            else:
                break
        
        # If still Direct and we found a root login page, use its name
        if root_nav == "Direct" and root_login_scene:
            root_scene_name = root_login_scene.name
    
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
        # Build full parent chain recursively
        parent_chain = []
        current_slug = parent_slug
        
        # Walk up the parent chain
        while current_slug:
            current_scene = scenes_by_slug.get(current_slug)
            if current_scene:
                parent_chain.append(current_scene.name)
                current_slug = current_scene.parent
            else:
                parent_chain.append(current_slug)
                break
        
        # Reverse to get root-to-leaf order
        parent_chain.reverse()
        
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
    scenes_by_slug = hierarchy['scenes_by_slug']
    
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
    
    # Get allowed profiles from scene level (via extra attributes)
    allowed_profile_keys = []
    if hasattr(scene, 'model_extra') and scene.model_extra:
        allowed_profile_keys = scene.model_extra.get('allowed_profiles', [])
        if not allowed_profile_keys:
            allowed_profile_keys = scene.model_extra.get('profile_keys', [])
    
    # Check view-level security
    view_profiles = set()
    for view in scene.views:
        if hasattr(view, 'model_extra') and view.model_extra:
            view_allowed = view.model_extra.get('allowed_profiles', [])
            if view_allowed:
                view_profiles.update(view_allowed)
            if view.model_extra.get('limit_profile_access'):
                view_profiles.update(view_allowed)
    
    if view_profiles and not allowed_profile_keys:
        allowed_profile_keys = list(view_profiles)
    
    # Check parent security
    has_parent = bool(parent_slug)
    inherits_security = False
    parent_name = None
    
    if has_parent:
        # Walk up the parent chain to find profiles
        current_slug = parent_slug
        parent_name = None
        inherited_profiles = []
        inherited_auth = None
        
        while current_slug and not inherited_profiles:
            current_parent = scenes_by_slug.get(current_slug)
            if current_parent:
                if parent_name is None:  # Store direct parent name
                    parent_name = current_parent.name
                
                parent_auth = current_parent.authenticated
                parent_profiles = []
                if hasattr(current_parent, 'model_extra') and current_parent.model_extra:
                    parent_profiles = current_parent.model_extra.get('allowed_profiles', [])
                
                # Check parent view-level security
                parent_view_profiles = set()
                for view in current_parent.views:
                    if hasattr(view, 'model_extra') and view.model_extra:
                        view_allowed = view.model_extra.get('allowed_profiles', [])
                        if view_allowed:
                            parent_view_profiles.update(view_allowed)
                        if view.model_extra.get('limit_profile_access'):
                            parent_view_profiles.update(view_allowed)
                
                if parent_view_profiles and not parent_profiles:
                    parent_profiles = list(parent_view_profiles)
                
                if parent_profiles:
                    inherited_profiles = parent_profiles
                    inherited_auth = parent_auth
                    break
                
                if parent_auth is not None:
                    inherited_auth = parent_auth
                
                # Move to next parent
                current_slug = current_parent.parent
            else:
                break
        
        if inherited_profiles or inherited_auth is not None:
            inherits_security = True
            # Always inherit parent profiles for display in child scenes
            if not allowed_profile_keys:
                allowed_profile_keys = inherited_profiles or []
            if authenticated is None:
                authenticated = inherited_auth if inherited_auth is not None else True
    
    # Map profile keys to names
    allowed_profile_names = [profiles.get(pk, pk) for pk in allowed_profile_keys]
    
    # Determine if login is required (considering inheritance and profiles)
    requires_login = authenticated is True or bool(allowed_profile_keys) or (has_parent and inherits_security)
    
    # Security concerns
    concerns = []
    
    if is_utility_page:
        concerns.append("UTILITY PAGE: Requires Knack system-level account (beyond app profiles)")
    
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
        security_note = f"Inherits security from parent: {parent_name}"
    
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
    count = 0
    for scene in all_scenes:
        # Check if this scene's page_nav contains the parent's name
        # This is a simplified check - could be more sophisticated
        parent_scene = next((s for s in all_scenes if s.scene_key == scene_key), None)
        if parent_scene and parent_scene.scene_name in scene.page_nav and scene.scene_key != scene_key:
            # Make sure it's actually a descendant, not just mentioned in the path
            if scene.nav_level == "Child":
                count += 1
    return count


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
