"""Shared object/field resolution by key or name, with fuzzy suggestions.

Every command that accepts an "object or field, by key or by name" argument
should resolve it through this module so lookup semantics stay consistent:
keys (``object_12`` / ``field_116``) match case-insensitively and exactly;
anything else is treated as a name and matched case-insensitively.
"""

from difflib import get_close_matches

from knack_sleuth.models import Application, KnackField, KnackObject


def resolve_object(app: Application, identifier: str) -> KnackObject | None:
    """Find an object by key (e.g. 'object_12') or name, case-insensitively.

    Returns None if nothing matches.
    """
    ident = identifier.lower()

    if ident.startswith("object_"):
        for obj in app.objects:
            if obj.key.lower() == ident:
                return obj

    for obj in app.objects:
        if obj.name.lower() == ident:
            return obj

    return None


def resolve_fields(
    app: Application, identifier: str
) -> list[tuple[KnackObject, KnackField]]:
    """Find fields by key (e.g. 'field_116') or name, case-insensitively.

    A key match returns at most one ``(object, field)`` pair. A name match can
    legitimately be ambiguous — field names repeat across objects — so all
    matches are returned and the caller decides how to disambiguate.
    """
    ident = identifier.lower()

    if ident.startswith("field_"):
        for obj in app.objects:
            for field in obj.fields:
                if field.key.lower() == ident:
                    return [(obj, field)]
        return []

    matches: list[tuple[KnackObject, KnackField]] = []
    for obj in app.objects:
        for field in obj.fields:
            if field.name.lower() == ident:
                matches.append((obj, field))
    return matches


def suggest_object_names(
    app: Application, identifier: str, limit: int = 3
) -> list[str]:
    """Return up to ``limit`` object names/keys similar to a failed lookup."""
    candidates = [obj.name for obj in app.objects] + [obj.key for obj in app.objects]
    return get_close_matches(identifier, candidates, n=limit, cutoff=0.6)


def suggest_field_names(
    app: Application, identifier: str, limit: int = 3
) -> list[str]:
    """Return up to ``limit`` field names/keys similar to a failed lookup."""
    candidates: set[str] = set()
    for obj in app.objects:
        for field in obj.fields:
            candidates.add(field.name)
            candidates.add(field.key)
    return get_close_matches(identifier, sorted(candidates), n=limit, cutoff=0.6)
