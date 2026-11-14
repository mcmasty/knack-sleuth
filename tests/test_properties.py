"""Property-based tests (hypothesis).

Example tests check the cases someone thought of; these check invariants over
generated inputs, which is where text sanitisers and graph code tend to break.
The real sample app is loaded once at module level because hypothesis reruns
each test many times and function-scoped fixtures would not reset between runs.
"""

import copy
import json
import re
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from knack_sleuth.db_schema import (
    _sanitize_entity_name,
    _sanitize_field_name,
    _strip_html,
    build_subgraph,
)
from knack_sleuth.diff import _sort_key, diff_applications
from knack_sleuth.lookup import resolve_fields, resolve_object
from knack_sleuth.models import KnackAppMetadata

SAMPLE = json.loads(Path("tests/data/sample_knack_app_meta.json").read_text())
APP = KnackAppMetadata(**SAMPLE).application
OBJECT_KEYS = [obj.key for obj in APP.objects]
FIELD_KEYS = [field.key for obj in APP.objects for field in obj.fields]


def _app_without(object_keys: set[str]):
    data = copy.deepcopy(SAMPLE)
    data["application"]["objects"] = [
        obj for obj in data["application"]["objects"] if obj["key"] not in object_keys
    ]
    return KnackAppMetadata(**data).application


@st.composite
def random_case(draw, text: str) -> str:
    flips = draw(st.lists(st.booleans(), min_size=len(text), max_size=len(text)))
    return "".join(
        c.upper() if f else c.lower() for c, f in zip(text, flips, strict=True)
    )


class TestSanitizers:
    @given(st.text())
    def test_entity_name_is_a_single_token(self, name):
        result = _sanitize_entity_name(name)
        assert result
        assert re.fullmatch(r"[\w-]+", result)
        assert "--" not in result
        assert not result.startswith("-")
        assert not result.endswith("-")
        assert not result[0].isdigit()

    @given(st.text())
    def test_entity_name_is_idempotent(self, name):
        once = _sanitize_entity_name(name)
        assert _sanitize_entity_name(once) == once

    @given(st.text(alphabet=st.characters(codec="ascii")))
    def test_field_name_is_an_identifier(self, name):
        # ASCII only, for now: non-ASCII letters pass through unchanged, and
        # str.lower()/capitalize() turn a few into combining marks ('İd' ->
        # 'i̇d'), which are not \w. Whether Mermaid accepts those is unverified.
        result = _sanitize_field_name(name)
        assert result
        assert re.fullmatch(r"\w+", result)
        assert not result[0].isdigit()

    @given(st.text())
    def test_strip_html_normalises_whitespace(self, text):
        result = _strip_html(text)
        assert result == result.strip()
        assert not re.search(r"\s\s", result)


class TestSortKey:
    @given(st.lists(st.integers(min_value=0, max_value=10**6), unique=True))
    def test_knack_keys_sort_numerically(self, numbers):
        keys = [f"object_{n}" for n in numbers]
        assert sorted(keys, key=_sort_key) == [f"object_{n}" for n in sorted(numbers)]


class TestDiff:
    @given(st.sets(st.sampled_from(OBJECT_KEYS)))
    def test_removing_objects_is_reported_both_ways(self, removed):
        smaller = _app_without(removed)

        forward = diff_applications(APP, smaller)
        backward = diff_applications(smaller, APP)

        assert {o["key"] for o in forward["objects"]["removed"]} == removed
        assert {o["key"] for o in backward["objects"]["added"]} == removed
        assert forward["objects"]["added"] == []
        assert forward["has_changes"] == bool(removed)


class TestSubgraph:
    @given(
        st.sampled_from(OBJECT_KEYS),
        st.integers(min_value=0, max_value=6),
    )
    def test_depth_grows_monotonically(self, start, depth):
        shallow = build_subgraph(APP, start, depth)
        deeper = build_subgraph(APP, start, depth + 1)
        assert start in shallow
        assert shallow <= deeper
        assert deeper <= set(OBJECT_KEYS)

    @given(st.sampled_from(OBJECT_KEYS))
    def test_depth_zero_is_just_the_start(self, start):
        assert build_subgraph(APP, start, 0) == {start}


class TestLookup:
    @given(
        st.sampled_from(OBJECT_KEYS).flatmap(
            lambda k: st.tuples(st.just(k), random_case(k))
        )
    )
    def test_object_key_lookup_ignores_case(self, pair):
        key, typed = pair
        obj = resolve_object(APP, typed)
        assert obj is not None
        assert obj.key == key

    @given(
        st.sampled_from([o.name for o in APP.objects]).flatmap(
            lambda n: st.tuples(st.just(n), random_case(n))
        )
    )
    def test_object_name_lookup_ignores_case(self, pair):
        name, typed = pair
        obj = resolve_object(APP, typed)
        assert obj is not None
        assert obj.name.lower() == name.lower()

    @given(
        st.sampled_from(FIELD_KEYS).flatmap(
            lambda k: st.tuples(st.just(k), random_case(k))
        )
    )
    def test_field_key_lookup_is_exact_and_unique(self, pair):
        key, typed = pair
        matches = resolve_fields(APP, typed)
        assert [field.key for _, field in matches] == [key]
