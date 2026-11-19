"""Role-based access reports: role-access-review and role-access-summary."""

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.markup import escape

from knack_sleuth.lookup import normalise_name
from knack_sleuth.models import Scene, SceneSecurity, SecurityReport
from knack_sleuth.security import (
    count_children,
    generate_security_report,
    get_views_for_profile,
)

from ._common import (
    cli,
    console,
    err_console,
    load_app_metadata,
    timestamp,
    write_csv,
)
from ._options import AppId, MetadataFile, Refresh

RULE = "=" * 80

REVIEW_COLUMNS = [
    "root_nav",
    "scene_name",
    "nav_level",
    "allowed_profile_count",
    "allowed_profiles",
    "page_nav",
    "scene_key",
    "scene_slug",
    "scene_type",
    "view_names",
    "view_keys",
    "security_concern",
    "requires_login",
    "inherits_security",
]
SUMMARY_COLUMNS = [
    "root_nav",
    "scene_name",
    "page_nav",
    "scene_key",
    "scene_slug",
    "view_names",
    "view_keys",
    "access_basis",
]
ACCESS_BASES = ("role", "any_login", "public", "utility")


def _analyze(file_path: Path | None, app_id: str | None, refresh: bool):
    app_export = load_app_metadata(file_path, app_id, refresh)
    console.print("[dim]Analyzing scene security with navigation hierarchy...[/dim]")
    return app_export, generate_security_report(app_export.application)


def _banner(title: str) -> None:
    console.print(RULE)
    console.print(f"[bold cyan]{title}[/bold cyan]")
    console.print(RULE)


# --- role-access-review ---------------------------------------------------------


def _print_review(report: SecurityReport) -> None:
    console.print()
    _banner(f"ROLE ACCESS REVIEW: {escape(report.app_name)}")
    console.print(f"\nTotal Scenes: {report.total_scenes}")
    console.print(f"  Menu Scenes: {report.menu_scenes}")
    console.print(f"  Utility Pages (Require Knack Account): {report.utility_pages}")
    console.print(
        f"  Scenes with Parent (Inherit Security): {report.scenes_with_parents}"
    )
    console.print(
        f"  Scenes Inheriting Security from Parent: {report.scenes_inheriting_security}"
    )
    console.print(
        f"  Top-Level Scenes (No Parent): {report.total_scenes - report.scenes_with_parents}"
    )
    console.print(f"\nPublic Scenes (No Login Required): {report.public_scenes}")
    console.print(f"Login Required Scenes: {report.login_required_scenes}")
    console.print(
        f"Unrestricted Authenticated Scenes: {report.unrestricted_authenticated_scenes}"
    )
    console.print(f"\nTotal User Profiles (Roles): {report.total_profiles}")

    console.print()
    _banner("USER PROFILES (ROLES)")
    for profile_key, profile_name in report.profiles.items():
        access_count = report.profile_access_counts.get(profile_name, 0)
        console.print(
            escape(f"  {profile_name:30} ({profile_key:20})")
            + f" - Access to {access_count} scenes"
        )

    console.print()
    _banner("SECURITY CONCERNS")
    if report.public_scenes > 0:
        console.print(
            f"⚠️  {report.public_scenes} scenes are publicly accessible without login"
        )
    if report.unrestricted_authenticated_scenes > 0:
        console.print(
            f"⚠️  {report.unrestricted_authenticated_scenes} scenes require login but have no profile restrictions"
        )
    if report.public_scenes == 0 and report.unrestricted_authenticated_scenes == 0:
        console.print("✓ No obvious security concerns in scene access controls")


def _review_row(scene: SceneSecurity) -> dict[str, Any]:
    row = scene.model_dump()
    row["allowed_profiles"] = ", ".join(scene.allowed_profiles)
    row["view_names"] = ", ".join(scene.view_names)
    row["view_keys"] = ", ".join(scene.view_keys)
    return row


@cli.command(name="role-access-review")
def role_access_review(
    file_path: MetadataFile = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output CSV file path (default: role_access_review.csv in current directory)",
        ),
    ] = None,
    summary_only: Annotated[
        bool,
        typer.Option(
            "--summary-only",
            help="Show only top-level and login pages with child counts (exclude individual child pages)",
        ),
    ] = False,
):
    """
    Generate a role access review showing which user profiles can access which scenes.

    This command analyzes:

    - Scene navigation hierarchy (menus, login pages, utility pages)

    - Parent-child security inheritance

    - Profile (role) restrictions on each scene

    - Public vs authenticated access

    The output CSV shows:

    - Navigation structure (menu > parent > child)

    - Which roles have access to each scene

    - Security inheritance relationships

    - Public scenes and potential concerns

    Examples:

        knack-sleuth role-access-review app.json

        knack-sleuth role-access-review --app-id YOUR_APP_ID

        knack-sleuth role-access-review app.json -o my_review.csv

        knack-sleuth role-access-review app.json --summary-only  # Show only top-level pages
    """
    _, report = _analyze(file_path, app_id, refresh)

    scenes = report.scene_analyses
    columns = list(REVIEW_COLUMNS)
    if summary_only:
        # Only Menu and Top-Level scenes, each with its number of children
        scenes = [s for s in scenes if s.nav_level in ("Menu", "Top-Level")]
        for scene in scenes:
            scene.child_count = count_children(scene.scene_key, report.scene_analyses)
        columns.insert(columns.index("page_nav") + 1, "child_count")

    _print_review(report)

    output = output or Path(f"role_access_review_{timestamp()}.csv")
    write_csv(output, columns, (_review_row(s) for s in scenes))

    console.print()
    if summary_only:
        children_omitted = report.total_scenes - len(scenes)
        console.print(
            f"[green]✓[/green] Summary report exported to [bold]{escape(str(output))}[/bold]"
        )
        console.print(
            f"[dim]  {len(scenes)} top-level scenes ({children_omitted} children omitted)[/dim]"
        )
    else:
        console.print(
            f"[green]✓[/green] Report exported to [bold]{escape(str(output))}[/bold]"
        )
        console.print(f"[dim]  {len(scenes)} scenes[/dim]")
    console.print()


# --- role-access-summary --------------------------------------------------------


def _exit_unknown_profile(
    message: str, report: SecurityReport, by_key: bool
) -> NoReturn:
    err_console.print(f"[red]Error:[/red] {escape(message)}")
    console.print(f"\n[cyan]Available {'profiles' if by_key else 'roles'}:[/cyan]")
    for pk, pn in report.profiles.items():
        console.print(escape(f"  {pk}: {pn}" if by_key else f"  {pn} ({pk})"))
    raise typer.Exit(1)


def _resolve_profile(
    report: SecurityReport, role: str | None, profile_key: str | None
) -> tuple[str, str]:
    """(profile key, profile name) from --profile-key or --role, or exit."""
    if profile_key:
        name = report.profiles.get(profile_key)
        if not name:
            _exit_unknown_profile(
                f"Profile key '{profile_key}' not found in application", report, True
            )
        return profile_key, name

    # Closest reading first: as written, then ignoring case, then ignoring
    # stray whitespace too. A looser reading is used only when a stricter one
    # finds nothing.
    typed = role or ""
    readings = (
        lambda name: name == typed,
        lambda name: name.lower() == typed.lower(),
        lambda name: normalise_name(name) == normalise_name(typed),
    )
    matches: list[tuple[str, str]] = []
    for same in readings:
        matches = [(k, v) for k, v in report.profiles.items() if same(v)]
        if matches:
            break
    if not matches:
        _exit_unknown_profile(f"Role '{role}' not found in application", report, False)

    if len(matches) > 1:
        err_console.print(
            f"[yellow]Warning:[/yellow] Multiple profiles match '{escape(str(role))}':"
        )
        for pk, pn in matches:
            console.print(escape(f"  {pk}: {pn}"))
        console.print("\nUsing first match. Use --profile-key to specify exactly.")
    return matches[0]


def _access_basis(analysis: SceneSecurity, profile_name: str) -> str | None:
    """Why the profile can open a scene, so a reader can tell a scene that names
    this role from one any logged-in user can open (issue #27); None if it can't.
    """
    if profile_name in analysis.allowed_profiles:
        basis = "role"
    elif not analysis.requires_login:
        basis = "public"
    elif analysis.allowed_profile_count == 0:
        basis = "any_login"
    else:
        return None
    # Utility pages need a Knack system-level account on top of whatever the
    # app grants, so neither public nor any_login fits.
    return "utility" if analysis.scene_type == "user" else basis


def _accessible_scenes(
    report: SecurityReport,
    scenes: list[Scene],
    profile_key: str,
    profile_name: str,
) -> list[dict[str, Any]]:
    scenes_by_key = {s.key: s for s in scenes}
    rows = []
    for analysis in report.scene_analyses:
        basis = _access_basis(analysis, profile_name)
        scene = scenes_by_key.get(analysis.scene_key)
        if not basis or not scene:
            continue
        view_names, view_keys = get_views_for_profile(scene, profile_key, profile_name)
        rows.append(
            {
                "root_nav": analysis.root_nav,
                "scene_name": analysis.scene_name,
                "page_nav": analysis.page_nav,
                "scene_key": analysis.scene_key,
                "scene_slug": analysis.scene_slug,
                "view_names": ", ".join(view_names),
                "view_keys": ", ".join(view_keys),
                "view_count": len(view_names),
                "access_basis": basis,
            }
        )
    return rows


def _print_access_summary(
    app_name: str, profile_key: str, profile_name: str, rows: list[dict]
) -> int:
    """Print the console summary; returns the total number of accessible views."""
    console.print()
    _banner(f"ROLE ACCESS SUMMARY: {escape(app_name)}")
    console.print(f"\nProfile: [bold]{escape(profile_name)}[/bold] ({profile_key})")
    console.print(f"Accessible Scenes: {len(rows)}")

    total_views = sum(r["view_count"] for r in rows)
    console.print(f"Accessible Views: {total_views}")

    with_views = sum(1 for r in rows if r["view_count"] > 0)
    console.print(f"  Scenes with Views: {with_views}")
    console.print(f"  Scenes without Views: {len(rows) - with_views}")
    console.print(
        "Access basis (role = profile named on the scene, any_login = any logged-in user, "
        "public = no login, utility = Knack system-level account):"
    )
    for basis in ACCESS_BASES:
        count = sum(1 for r in rows if r["access_basis"] == basis)
        console.print(f"  {basis}: {count}")
    return total_views


@cli.command(name="role-access-summary")
def role_access_summary(
    file_path: MetadataFile = None,
    role: Annotated[
        str | None,
        typer.Option(
            "--role",
            help="User profile (role) name to filter by (e.g., 'Admin', 'Manager')",
        ),
    ] = None,
    profile_key: Annotated[
        str | None,
        typer.Option(
            "--profile-key", help="Profile key to filter by (e.g., 'profile_1')"
        ),
    ] = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output CSV file path (default: role_access_summary_<role>_<timestamp>.csv)",
        ),
    ] = None,
):
    """
    Show all pages and views accessible by a specific user profile (role).

    This command helps troubleshoot access issues by showing exactly which pages
    and views a particular role can access. Perfect for answering questions like:
    "Why can't Joe (Manager role) see the Inventory List view?"

    You must specify either --role (profile name) or --profile-key.

    The output shows:
    - Navigation hierarchy (menu > parent > child)
    - All scenes (pages) the role can access
    - All views within each scene that the role can access
    - Scene keys and slugs for reference

    Examples:
        knack-sleuth role-access-summary --role "Manager" app.json
        knack-sleuth role-access-summary --profile-key "profile_1" --app-id YOUR_APP_ID
        knack-sleuth role-access-summary --role "Admin" app.json -o admin_access.csv
    """
    if not role and not profile_key:
        err_console.print(
            "[red]Error:[/red] You must specify either --role or --profile-key"
        )
        raise typer.Exit(1)

    app_export, report = _analyze(file_path, app_id, refresh)
    target_key, target_name = _resolve_profile(report, role, profile_key)

    console.print(
        f"[dim]Filtering scenes accessible by '{escape(target_name)}' ({target_key})...[/dim]"
    )
    rows = _accessible_scenes(
        report, app_export.application.scenes, target_key, target_name
    )
    total_views = _print_access_summary(report.app_name, target_key, target_name, rows)

    if not output:
        safe_role_name = target_name.replace(" ", "_").replace("/", "_")
        output = Path(f"role_access_summary_{safe_role_name}_{timestamp()}.csv")
    write_csv(output, SUMMARY_COLUMNS, rows)

    console.print()
    console.print(
        f"[green]✓[/green] Summary exported to [bold]{escape(str(output))}[/bold]"
    )
    console.print(f"[dim]  {len(rows)} scenes, {total_views} views[/dim]")
    console.print()
