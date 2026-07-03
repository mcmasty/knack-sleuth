"""Structural diff between two Knack application metadata snapshots.

Knack keys (``object_N``, ``field_N``, ``scene_N``, ``view_N``) are stable
identifiers, so entities are matched by key: a rename shows up as a rename,
not as a removal plus an addition.

Noise rules:
- Fields of an added/removed object are NOT also reported as added/removed
  fields — the object-level entry covers them.
- Views of an added/removed scene are NOT also reported as added/removed
  views, for the same reason.

Record counts are data, not structure, and are deliberately excluded.
"""

from typing import Any

from knack_sleuth.models import Application, KnackField

# Field attributes compared for change detection (beyond the relationship,
# which is handled separately for connection fields).
_FIELD_ATTRS = ("name", "type", "required", "unique")


def _sort_key(key: str) -> tuple[str, int]:
    """Natural sort for Knack keys: object_10 sorts after object_2."""
    prefix, _, num = key.rpartition("_")
    return (prefix, int(num)) if num.isdigit() else (key, 0)


def _relationship_repr(field: KnackField) -> dict[str, str] | None:
    """Comparable representation of a connection field's relationship."""
    rel = field.relationship
    if rel is None:
        return None
    return {"object": rel.object, "has": rel.has, "belongs_to": rel.belongs_to}


def _diff_fields(old_obj, new_obj) -> tuple[list[dict], list[dict], list[dict]]:
    """Diff the fields of one object present in both snapshots."""
    old_fields = {f.key: f for f in old_obj.fields}
    new_fields = {f.key: f for f in new_obj.fields}

    added = [
        {
            "object_key": new_obj.key,
            "object_name": new_obj.name,
            "key": key,
            "name": new_fields[key].name,
            "type": new_fields[key].type,
        }
        for key in sorted(set(new_fields) - set(old_fields), key=_sort_key)
    ]
    removed = [
        {
            "object_key": old_obj.key,
            "object_name": old_obj.name,
            "key": key,
            "name": old_fields[key].name,
            "type": old_fields[key].type,
        }
        for key in sorted(set(old_fields) - set(new_fields), key=_sort_key)
    ]

    changed = []
    for key in sorted(set(old_fields) & set(new_fields), key=_sort_key):
        old_f, new_f = old_fields[key], new_fields[key]
        changes: dict[str, dict[str, Any]] = {}

        for attr in _FIELD_ATTRS:
            old_val, new_val = getattr(old_f, attr), getattr(new_f, attr)
            if old_val != new_val:
                changes[attr] = {"old": old_val, "new": new_val}

        old_rel, new_rel = _relationship_repr(old_f), _relationship_repr(new_f)
        if old_rel != new_rel:
            changes["relationship"] = {"old": old_rel, "new": new_rel}

        if changes:
            changed.append(
                {
                    "object_key": new_obj.key,
                    "object_name": new_obj.name,
                    "key": key,
                    "name": new_f.name,
                    "changes": changes,
                }
            )

    return added, removed, changed


def _diff_views(old_scene, new_scene) -> tuple[list[dict], list[dict], list[dict]]:
    """Diff the views of one scene present in both snapshots."""
    old_views = {v.key: v for v in old_scene.views}
    new_views = {v.key: v for v in new_scene.views}

    added = [
        {
            "scene_key": new_scene.key,
            "scene_name": new_scene.name,
            "key": key,
            "name": new_views[key].name,
            "type": new_views[key].type,
        }
        for key in sorted(set(new_views) - set(old_views), key=_sort_key)
    ]
    removed = [
        {
            "scene_key": old_scene.key,
            "scene_name": old_scene.name,
            "key": key,
            "name": old_views[key].name,
            "type": old_views[key].type,
        }
        for key in sorted(set(old_views) - set(new_views), key=_sort_key)
    ]

    changed = []
    for key in sorted(set(old_views) & set(new_views), key=_sort_key):
        old_v, new_v = old_views[key], new_views[key]
        changes: dict[str, dict[str, Any]] = {}
        for attr in ("name", "type"):
            old_val, new_val = getattr(old_v, attr), getattr(new_v, attr)
            if old_val != new_val:
                changes[attr] = {"old": old_val, "new": new_val}
        if changes:
            changed.append(
                {
                    "scene_key": new_scene.key,
                    "scene_name": new_scene.name,
                    "key": key,
                    "name": new_v.name,
                    "changes": changes,
                }
            )

    return added, removed, changed


def diff_applications(old: Application, new: Application) -> dict[str, Any]:
    """Compute a structural diff between two application snapshots.

    Returns a JSON-serializable dict with ``objects``, ``fields``, ``scenes``,
    and ``views`` sections (each with added/removed/renamed-or-changed lists),
    a ``summary`` section, and a top-level ``has_changes`` flag.
    """
    old_objects = {obj.key: obj for obj in old.objects}
    new_objects = {obj.key: obj for obj in new.objects}

    objects_added = [
        {
            "key": key,
            "name": new_objects[key].name,
            "field_count": len(new_objects[key].fields),
        }
        for key in sorted(set(new_objects) - set(old_objects), key=_sort_key)
    ]
    objects_removed = [
        {
            "key": key,
            "name": old_objects[key].name,
            "field_count": len(old_objects[key].fields),
        }
        for key in sorted(set(old_objects) - set(new_objects), key=_sort_key)
    ]
    objects_renamed = [
        {
            "key": key,
            "old_name": old_objects[key].name,
            "new_name": new_objects[key].name,
        }
        for key in sorted(set(old_objects) & set(new_objects), key=_sort_key)
        if old_objects[key].name != new_objects[key].name
    ]

    # Field diffs only for objects present in both snapshots (noise rule)
    fields_added: list[dict] = []
    fields_removed: list[dict] = []
    fields_changed: list[dict] = []
    for key in sorted(set(old_objects) & set(new_objects), key=_sort_key):
        added, removed, changed = _diff_fields(old_objects[key], new_objects[key])
        fields_added.extend(added)
        fields_removed.extend(removed)
        fields_changed.extend(changed)

    old_scenes = {scene.key: scene for scene in old.scenes}
    new_scenes = {scene.key: scene for scene in new.scenes}

    scenes_added = [
        {
            "key": key,
            "name": new_scenes[key].name,
            "slug": new_scenes[key].slug,
            "view_count": len(new_scenes[key].views),
        }
        for key in sorted(set(new_scenes) - set(old_scenes), key=_sort_key)
    ]
    scenes_removed = [
        {
            "key": key,
            "name": old_scenes[key].name,
            "slug": old_scenes[key].slug,
            "view_count": len(old_scenes[key].views),
        }
        for key in sorted(set(old_scenes) - set(new_scenes), key=_sort_key)
    ]
    scenes_renamed = [
        {
            "key": key,
            "old_name": old_scenes[key].name,
            "new_name": new_scenes[key].name,
        }
        for key in sorted(set(old_scenes) & set(new_scenes), key=_sort_key)
        if old_scenes[key].name != new_scenes[key].name
    ]

    # View diffs only for scenes present in both snapshots (noise rule)
    views_added: list[dict] = []
    views_removed: list[dict] = []
    views_changed: list[dict] = []
    for key in sorted(set(old_scenes) & set(new_scenes), key=_sort_key):
        added, removed, changed = _diff_views(old_scenes[key], new_scenes[key])
        views_added.extend(added)
        views_removed.extend(removed)
        views_changed.extend(changed)

    result = {
        "summary": {
            "old_app_name": old.name,
            "new_app_name": new.name,
            "old_counts": {
                "objects": len(old.objects),
                "fields": sum(len(o.fields) for o in old.objects),
                "scenes": len(old.scenes),
                "views": sum(len(s.views) for s in old.scenes),
            },
            "new_counts": {
                "objects": len(new.objects),
                "fields": sum(len(o.fields) for o in new.objects),
                "scenes": len(new.scenes),
                "views": sum(len(s.views) for s in new.scenes),
            },
        },
        "objects": {
            "added": objects_added,
            "removed": objects_removed,
            "renamed": objects_renamed,
        },
        "fields": {
            "added": fields_added,
            "removed": fields_removed,
            "changed": fields_changed,
        },
        "scenes": {
            "added": scenes_added,
            "removed": scenes_removed,
            "renamed": scenes_renamed,
        },
        "views": {
            "added": views_added,
            "removed": views_removed,
            "changed": views_changed,
        },
    }

    result["has_changes"] = any(
        entries
        for section in ("objects", "fields", "scenes", "views")
        for entries in result[section].values()
    )
    return result


def _format_change(attr: str, change: dict[str, Any]) -> str:
    """Render one attribute change as 'attr: old -> new'."""
    return f"{attr}: {change['old']!r} → {change['new']!r}"


def diff_to_markdown(diff: dict[str, Any]) -> str:
    """Render a diff result as a human-friendly markdown report."""
    summary = diff["summary"]
    lines = [
        f"# Metadata Diff: {summary['new_app_name']}",
        "",
        "| | Old | New |",
        "|---|---|---|",
    ]
    for label, kind in (
        ("Objects", "objects"),
        ("Fields", "fields"),
        ("Scenes", "scenes"),
        ("Views", "views"),
    ):
        lines.append(
            f"| {label} | {summary['old_counts'][kind]} | {summary['new_counts'][kind]} |"
        )
    lines.append("")

    if not diff["has_changes"]:
        lines.append("**No structural changes detected.**")
        return "\n".join(lines)

    if summary["old_app_name"] != summary["new_app_name"]:
        lines.append(
            f"**Application renamed:** {summary['old_app_name']} → {summary['new_app_name']}"
        )
        lines.append("")

    def section(title: str, entries: list[dict], render) -> None:
        if not entries:
            return
        lines.append(f"## {title} ({len(entries)})")
        lines.append("")
        for entry in entries:
            lines.append(f"- {render(entry)}")
        lines.append("")

    section(
        "Objects Added",
        diff["objects"]["added"],
        lambda e: f"**{e['name']}** (`{e['key']}`) — {e['field_count']} fields",
    )
    section(
        "Objects Removed",
        diff["objects"]["removed"],
        lambda e: f"**{e['name']}** (`{e['key']}`) — {e['field_count']} fields",
    )
    section(
        "Objects Renamed",
        diff["objects"]["renamed"],
        lambda e: f"`{e['key']}`: {e['old_name']} → {e['new_name']}",
    )
    section(
        "Fields Added",
        diff["fields"]["added"],
        lambda e: f"{e['object_name']} → **{e['name']}** (`{e['key']}`, {e['type']})",
    )
    section(
        "Fields Removed",
        diff["fields"]["removed"],
        lambda e: f"{e['object_name']} → **{e['name']}** (`{e['key']}`, {e['type']})",
    )
    section(
        "Fields Changed",
        diff["fields"]["changed"],
        lambda e: f"{e['object_name']} → **{e['name']}** (`{e['key']}`): "
        + "; ".join(_format_change(a, c) for a, c in e["changes"].items()),
    )
    section(
        "Scenes Added",
        diff["scenes"]["added"],
        lambda e: f"**{e['name']}** (`{e['key']}`, /{e['slug']}) — {e['view_count']} views",
    )
    section(
        "Scenes Removed",
        diff["scenes"]["removed"],
        lambda e: f"**{e['name']}** (`{e['key']}`, /{e['slug']}) — {e['view_count']} views",
    )
    section(
        "Scenes Renamed",
        diff["scenes"]["renamed"],
        lambda e: f"`{e['key']}`: {e['old_name']} → {e['new_name']}",
    )
    section(
        "Views Added",
        diff["views"]["added"],
        lambda e: f"{e['scene_name']} → **{e['name']}** (`{e['key']}`, {e['type']})",
    )
    section(
        "Views Removed",
        diff["views"]["removed"],
        lambda e: f"{e['scene_name']} → **{e['name']}** (`{e['key']}`, {e['type']})",
    )
    section(
        "Views Changed",
        diff["views"]["changed"],
        lambda e: f"{e['scene_name']} → **{e['name']}** (`{e['key']}`): "
        + "; ".join(_format_change(a, c) for a, c in e["changes"].items()),
    )

    return "\n".join(lines).rstrip() + "\n"
