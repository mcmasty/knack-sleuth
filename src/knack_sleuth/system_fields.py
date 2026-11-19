"""Knack's own audit connections, and a view of an app without them.

Knack adds system fields to every object. Three of them, Created By, Updated
By and Owned By, are connections to the Accounts object. They record who
touched a record; they say nothing about how the app's data is modelled, and
left in they connect every object to Accounts three times over, which turns
every object into a hub and the whole app into one cluster.

Relationship analysis therefore works on a view of the app with those
connections removed. The fields themselves are untouched: they are still
fields, and still appear wherever fields are listed.
"""

from knack_sleuth.models import Application, KnackAppMetadata


def system_connection_keys(app: Application) -> set[str]:
    """Field keys of the connections Knack itself adds to objects."""
    return {
        field.key
        for obj in app.objects
        for field in obj.fields
        if field.isSystemField and field.type == "connection"
    }


def without_system_connections(app: Application) -> tuple[Application, int]:
    """The app with system connections removed, and how many there were.

    Returns the app itself when it has none. Only each object's
    ``connections`` change; everything else is shared with the original.
    """
    keys = system_connection_keys(app)
    if not keys:
        return app, 0
    removed: set[str] = set()
    objects = []
    for obj in app.objects:
        connections = obj.connections
        if not connections:
            objects.append(obj)
            continue
        listed = [*connections.inbound, *connections.outbound]
        removed.update(conn.key for conn in listed if conn.key in keys)
        kept = connections.model_copy(
            update={
                "inbound": [c for c in connections.inbound if c.key not in keys],
                "outbound": [c for c in connections.outbound if c.key not in keys],
            }
        )
        objects.append(obj.model_copy(update={"connections": kept}))
    if not removed:
        return app, 0
    return app.model_copy(update={"objects": objects}), len(removed)


def metadata_without_system_connections(
    app_export: KnackAppMetadata,
) -> tuple[KnackAppMetadata, int]:
    """As ``without_system_connections``, for a whole metadata export."""
    app, removed = without_system_connections(app_export.application)
    if not removed:
        return app_export, 0
    return app_export.model_copy(update={"application": app}), removed
