"""Regression tests for GeminiAnalyzer.

Run from the project root:
    python -m pytest tests/ -q

The tests cover the surface most prone to silent breakage:
- parser: timestamp + code-block + HTML/JSON robustness
- categorizer: routing into the expanded taxonomy
- reconstruct: union-find correctness + non-destructiveness + name filter
- export: markdown round-trip + atomic uniquify + dedup non-destructiveness
- llm_client: fail-closed contract
- llm_cache: round-trip + namespace isolation
"""

import sys
import json
from pathlib import Path

# Make project root importable when pytest runs from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from parser import (Conversation, Message, _parse_timestamp,
                    parse_html_activity, parse_json_file)
from categorizer import categorize_conversation, CATEGORIES, categorize_all
from reconstruct import (reconstruct_projects, build_timeline,
                         _is_real_project_name)
from export import (conversation_to_markdown, project_bundle_markdown,
                    write_project_bundle, find_duplicates)
from llm_client import LLMClient, is_available, ENV_KEY
from llm_cache import LLMCache


# ── Parser ───────────────────────────────────────────────────────────

def test_timestamp_parses_takeout_format():
    ts = _parse_timestamp("Apr 1, 2026, 2:12:20 PM EDT")
    assert ts is not None and ts.year == 2026 and ts.month == 4 and ts.day == 1


def test_timestamp_parses_iso():
    ts = _parse_timestamp("2026-04-01T14:12:20Z")
    assert ts is not None and ts.year == 2026


def test_timestamp_handles_garbage():
    assert _parse_timestamp("nope") is None
    assert _parse_timestamp(None) is None


def test_message_extracts_code_blocks():
    m = Message(role="model", text="here:\n```python\nprint(1)\n```\nand done")
    blocks = m.extract_code_blocks()
    assert len(blocks) == 1
    assert blocks[0]["language"] == "python"
    assert "print(1)" in blocks[0]["code"]


def test_message_no_code():
    m = Message(role="user", text="just words")
    assert not m.has_code()
    assert m.extract_code_blocks() == []


# ── Categorizer ──────────────────────────────────────────────────────

def _conv(text, title="t"):
    return Conversation(id="x", title=title,
                        messages=[Message(role="user", text=text)])


def test_taxonomy_has_13_categories():
    assert len(CATEGORIES) == 13
    expected_new = {
        "Writing & Editing", "Productivity & Planning", "Finance & Money",
        "Media & Design", "Hardware & Electronics", "Gaming",
    }
    assert expected_new.issubset(CATEGORIES.keys())


@pytest.mark.parametrize("text,expected", [
    ("Help me plan my monthly budget and savings", "Finance & Money"),
    ("Proofread and rephrase this email to sound concise", "Writing & Editing"),
    ("Build a character loadout for the rpg boss fight", "Gaming"),
    ("Help me organize my todo list and prioritize tasks", "Productivity & Planning"),
    ("Generate an image with a clean color palette logo", "Media & Design"),
    ("Read a gpio sensor on raspberry pi", "Hardware & Electronics"),
])
def test_categorizer_routes_into_new_categories(text, expected):
    r = categorize_conversation(_conv(text))
    assert r.category == expected, f"got {r.category} for: {text!r}"


def test_categorizer_returns_uncategorized_for_unknown():
    r = categorize_conversation(_conv("blah xyz qrst"))
    assert r.category == "Uncategorized"


def test_categorizer_code_block_boost_wins():
    text = "look at this:\n```python\ndef f():\n    return 1\n```"
    r = categorize_conversation(_conv(text))
    assert r.category == "Coding & Programming"
    assert "has-code" in r.tags


# ── Reconstruct ──────────────────────────────────────────────────────

def test_is_real_project_name_filters_fragments():
    assert _is_real_project_name("Screen Agent")
    assert _is_real_project_name("Agentic Fleet")
    assert not _is_real_project_name("FROM")         # SQL keyword
    assert not _is_real_project_name("Yes")          # filler
    assert not _is_real_project_name("Check if the input is a list")  # verb start
    assert not _is_real_project_name("Example usage")  # fragment word
    assert not _is_real_project_name("how does this look")  # >4 words + verb-ish


def test_reconstruct_merges_by_shared_project_name():
    convs = [
        Conversation(id=f"c{i}", title=f"t{i}", category="Coding & Programming",
                     coding_project_name="MyApp",
                     messages=[Message(role="user", text="build MyApp")])
        for i in range(3)
    ]
    threads = reconstruct_projects(convs, min_size=2)
    assert len(threads) == 1
    assert threads[0].size == 3
    assert threads[0].merge_basis == "project_name"


def test_reconstruct_non_destructive():
    convs = [
        Conversation(id=f"c{i}", title=f"t{i}", category="Coding & Programming",
                     coding_project_name="MyTestApp",
                     messages=[Message(role="user", text="hi")])
        for i in range(4)
    ]
    ids_before = [c.id for c in convs]
    titles_before = [c.title for c in convs]
    threads = reconstruct_projects(convs)
    assert [c.id for c in convs] == ids_before
    assert [c.title for c in convs] == titles_before
    assert threads and threads[0].size == 4


def test_reconstruct_ignores_non_coding():
    convs = [
        Conversation(id="a", title="recipe", category="Personal & Lifestyle",
                     messages=[Message(role="user", text="what's a recipe")]),
        Conversation(id="b", title="recipe2", category="Personal & Lifestyle",
                     messages=[Message(role="user", text="another recipe")]),
    ]
    assert reconstruct_projects(convs) == []


def test_build_timeline_buckets():
    from datetime import datetime
    convs = [
        Conversation(id="a", title="t", category="Coding & Programming",
                     create_time=datetime(2026, 1, 15),
                     messages=[Message(role="user", text="hi")]),
        Conversation(id="b", title="t", category="Coding & Programming",
                     create_time=datetime(2026, 1, 20),
                     messages=[Message(role="user", text="hi")]),
        Conversation(id="c", title="t", category="Gaming",
                     create_time=datetime(2026, 2, 1),
                     messages=[Message(role="user", text="game")]),
    ]
    tl = build_timeline(convs, "month")
    assert len(tl) == 2
    assert tl[0]["period"] == "2026-01" and tl[0]["total"] == 2
    assert tl[1]["period"] == "2026-02" and tl[1]["total"] == 1


# ── Export ───────────────────────────────────────────────────────────

def test_conversation_to_markdown_round_trips_code():
    c = Conversation(
        id="x", title="hello",
        messages=[
            Message(role="user", text="run this"),
            Message(role="model", text="```python\nprint('hi')\n```"),
        ],
    )
    md = conversation_to_markdown(c)
    assert "# hello" in md
    assert "**You**" in md and "**Gemini**" in md
    assert "```python" in md and "print('hi')" in md


def test_conversation_to_markdown_none_text_safe():
    c = Conversation(id="x", title="t",
                     messages=[Message(role="user", text=None)])  # type: ignore
    md = conversation_to_markdown(c)
    assert "**You**" in md  # didn't crash


def test_write_project_bundle_uniquifies(tmp_path):
    from reconstruct import ProjectThread
    t = ProjectThread(
        name="Same Name",
        conversations=[Conversation(id="x", title="t",
                                    messages=[Message(role="user", text="hi")])],
    )
    p1 = write_project_bundle(t, tmp_path)
    p2 = write_project_bundle(t, tmp_path)
    assert p1 != p2 and p1.exists() and p2.exists()


def test_find_duplicates_non_destructive():
    convs = [
        Conversation(id="a", title="a",
                     messages=[Message(role="user", text="same text here")]),
        Conversation(id="b", title="b",
                     messages=[Message(role="user", text="same text here")]),
        Conversation(id="c", title="c",
                     messages=[Message(role="user", text="different text")]),
    ]
    ids_before = [c.id for c in convs]
    titles_before = [c.title for c in convs]
    dups = find_duplicates(convs)
    assert [c.id for c in convs] == ids_before
    assert [c.title for c in convs] == titles_before
    assert len(dups) == 1 and len(dups[0].conversation_ids) == 2


def test_find_duplicates_normalizes_timestamps():
    """Same content with different leaked timestamps must dedupe."""
    convs = [
        Conversation(id="a", title="a",
                     messages=[Message(role="user",
                                       text="hello Apr 1, 2026, 2:12:20 PM EDT world")]),
        Conversation(id="b", title="b",
                     messages=[Message(role="user",
                                       text="hello May 5, 2026, 9:30:00 AM PST world")]),
    ]
    dups = find_duplicates(convs)
    assert len(dups) == 1


# ── LLM client ───────────────────────────────────────────────────────

def test_llm_client_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    assert is_available() is False
    r = LLMClient().complete("hi")
    assert r.success is False
    assert ENV_KEY in (r.error or "")


# ── LLM cache ────────────────────────────────────────────────────────

def test_cache_roundtrip():
    cache = LLMCache(enabled=True)
    cache.set("test_ns", "m1", "key_abc", {"value": 42})
    assert cache.get("test_ns", "m1", "key_abc") == {"value": 42}
    assert cache.clear("test_ns") >= 1


def test_cache_namespace_isolation():
    cache = LLMCache(enabled=True)
    cache.set("ns_a", "m1", "k", {"x": 1})
    cache.set("ns_b", "m1", "k", {"x": 2})
    assert cache.get("ns_a", "m1", "k") == {"x": 1}
    assert cache.get("ns_b", "m1", "k") == {"x": 2}
    cache.clear("ns_a")
    cache.clear("ns_b")


def test_cache_disabled_is_a_noop():
    cache = LLMCache(enabled=False)
    assert cache.set("x", "m", "k", {"v": 1}) is False
    assert cache.get("x", "m", "k") is None
