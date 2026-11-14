"""Names vulture reports as unused that are used indirectly.

Reviewed by hand; regenerate candidates with `vulture --make-whitelist`.
Each entry needs a reason, so this file can't turn into a dumping ground.
"""

# ruff: noqa: B018, F821
# Pydantic fields: populated from Knack's metadata JSON and emitted by
# model_dump()/model_json_schema(), so attribute access never names them.
_.validation  # models.py
_.code  # models.py
_.immutable  # models.py
_.relationship_type  # models.py
_.authenticated_user  # models.py
_.links  # models.py
_.menu_pages  # models.py
_.home_scene  # models.py
_.design  # models.py
_.child_count  # models.py; written to the CSV through model_dump() in cli.py
