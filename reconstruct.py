"""Project reconstruction + timeline.

Google Takeout records each Gemini prompt as a SEPARATE activity entry, so one
real project ends up shattered across dozens of disconnected conversations. This
module stitches those fragments back into coherent, chronologically-ordered
project threads using two signals:

  1. shared project name (from categorizer's regex detection), and
  2. shared *distinctive* code identifiers (filenames, class/def names) — weighted
     by rarity so a common token like ``main.py`` doesn't merge unrelated projects.

Non-destructive: ProjectThreads REFERENCE conversations. Nothing is ever mutated
or deleted. Only coding/named conversations are *considered* for projects (research
and creative chats are out of scope by design); none are modified either way.
"""

import re
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from parser import Conversation

logger = logging.getLogger(__name__)

# Identifiers that are too generic to prove two conversations share a project.
_GENERIC_IDENTIFIERS = {
    "main.py", "app.py", "index.js", "index.html", "index.ts", "main.js",
    "main.cpp", "main.c", "test.py", "utils.py", "config.py", "setup.py",
    "__init__.py", "style.css", "styles.css", "script.js", "server.py",
}

_FILE_RE = re.compile(
    r"\b([\w\-]{2,40}\.(?:py|js|ts|tsx|jsx|java|c|cpp|cs|rs|go|rb|php|html|css|json|sh|bat|kv|ui))\b",
    re.IGNORECASE,
)
_CLASS_RE = re.compile(r"\bclass\s+([A-Z]\w{2,40})")
_DEF_RE = re.compile(r"\bdef\s+([a-z_]\w{3,40})")

# How many chars of a conversation to scan for identifiers (bounded for speed).
_SCAN_CHARS = 4000
# An identifier only counts as a merge signal if it recurs (>= _MIN_DF) but stays
# distinctive: appearing in no more than a tiny fraction of conversations AND no
# more than _MAX_DF_ABS in absolute terms. Common tokens cause transitive
# chaining that collapses unrelated projects into one blob, so the cap is strict.
_MIN_DF = 2
_MAX_DF_FRACTION = 0.005
_MAX_DF_ABS = 20

# Detected "project names" that are really keywords/filler, not real projects.
_PROJECT_NAME_STOPWORDS = {
    "from", "select", "where", "import", "return", "class", "def", "none",
    "true", "false", "null", "main", "test", "data", "app", "the", "this",
    "that", "program", "tool", "game", "project", "code", "python", "string",
    "int", "void", "public", "private", "function", "const", "var", "let",
    "yes", "no", "new", "ready", "ok", "okay", "done", "hello", "sure", "thanks",
}
# A real project name doesn't start with a verb/question word (sentence fragment)
# and doesn't contain these tell-tale fragment words.
_FRAGMENT_STARTERS = {
    "check", "make", "create", "build", "help", "write", "get", "look", "can",
    "how", "what", "why", "is", "are", "do", "does", "please", "give", "show",
    "tell", "find", "add", "explain", "fix",
}
_FRAGMENT_WORDS = {"if", "usage", "example", "input", "the", "a", "an"}


@dataclass
class ProjectThread:
    name: str
    conversations: list[Conversation] = field(default_factory=list)  # chronological
    first_activity: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    languages: list[str] = field(default_factory=list)
    code_block_count: int = 0
    merge_basis: str = ""  # "project_name" | "shared_code_identity" | "singleton"

    @property
    def size(self) -> int:
        return len(self.conversations)

    @property
    def span_days(self) -> Optional[int]:
        if self.first_activity and self.last_activity:
            return (self.last_activity - self.first_activity).days
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "size": self.size,
            "first_activity": self.first_activity.isoformat() if self.first_activity else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "span_days": self.span_days,
            "languages": self.languages,
            "code_block_count": self.code_block_count,
            "merge_basis": self.merge_basis,
            "conversation_ids": [c.id for c in self.conversations],
        }


# ── Union-Find ───────────────────────────────────────────────────────

class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ── Identifier extraction ────────────────────────────────────────────

def _extract_identifiers(conv: Conversation) -> set[str]:
    """Distinctive tokens that hint at which project a conversation belongs to."""
    text = conv.full_text[:_SCAN_CHARS]
    ids: set[str] = set()

    for m in _FILE_RE.findall(text):
        low = m.lower()
        if low not in _GENERIC_IDENTIFIERS:
            ids.add(f"file:{low}")
    for m in _CLASS_RE.findall(text):
        ids.add(f"class:{m}")
    for m in _DEF_RE.findall(text):
        ids.add(f"def:{m}")

    return ids


def _normalize_project_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def _is_real_project_name(name: str) -> bool:
    norm = _normalize_project_name(name)
    if len(norm) < 3:
        return False
    words = norm.split()
    if norm in _PROJECT_NAME_STOPWORDS:
        return False
    if len(words) > 4:  # sentence fragment, not a name
        return False
    if words[0] in _FRAGMENT_STARTERS:
        return False
    if any(w in _FRAGMENT_WORDS for w in words):
        return False
    return True


# ── Reconstruction ───────────────────────────────────────────────────

def reconstruct_projects(
    conversations: list[Conversation],
    min_size: int = 2,
    include_singletons: bool = False,
) -> list[ProjectThread]:
    """Group coding conversations into project threads.

    Only conversations categorized as coding (or carrying a detected project name)
    are considered — research/creative chats aren't "projects". Every considered
    conversation lands in exactly one thread; nothing is lost.

    min_size: threads smaller than this are dropped UNLESS they carry a real
        project name (a named one-shot project is still worth showing).
    include_singletons: if True, return every unmatched coding conversation as its
        own 1-item thread too.
    """
    coding = [
        c for c in conversations
        if c.category == "Coding & Programming" or c.coding_project_name
    ]
    if not coding:
        return []
    logger.debug(
        "Reconstruction scope: %d of %d conversations are coding/named "
        "(non-coding chats excluded by design, not lost)",
        len(coding), len(conversations),
    )

    n = len(coding)
    uf = _UnionFind(n)

    # Collect signals per conversation.
    conv_ids: list[set[str]] = []
    for c in coding:
        sig = _extract_identifiers(c)
        if c.coding_project_name and _is_real_project_name(c.coding_project_name):
            sig.add(f"project:{_normalize_project_name(c.coding_project_name)}")
        conv_ids.append(sig)

    # Document frequency per identifier.
    df: Counter[str] = Counter()
    for sig in conv_ids:
        for ident in sig:
            df[ident] += 1

    max_df = max(_MIN_DF, min(int(n * _MAX_DF_FRACTION), _MAX_DF_ABS))

    # An identifier is a merge signal if it recurs but stays distinctive.
    # Project names are ALWAYS a merge signal regardless of frequency.
    ident_to_convs: dict[str, list[int]] = defaultdict(list)
    for i, sig in enumerate(conv_ids):
        for ident in sig:
            is_project = ident.startswith("project:")
            if is_project or (_MIN_DF <= df[ident] <= max_df):
                ident_to_convs[ident].append(i)

    for ident, members in ident_to_convs.items():
        if len(members) < 2:
            continue
        first = members[0]
        for other in members[1:]:
            uf.union(first, other)

    # Build components AFTER all unions are done (roots are now final).
    components: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        components[uf.find(i)].append(i)

    # Determine basis per component from final membership — not during union,
    # where re-parenting could orphan an earlier basis assignment.
    threads: list[ProjectThread] = []
    for members in components.values():
        has_project = any(
            any(idn.startswith("project:") for idn in conv_ids[i])
            for i in members
        )
        if len(members) > 1:
            basis = "project_name" if has_project else "shared_code_identity"
        else:
            basis = "project_name" if has_project else "singleton"
        convs = [coding[i] for i in members]
        threads.append(_build_thread(convs, basis))

    # A "reconstructed project" means 2+ fragments were stitched together. A lone
    # conversation with a detected name isn't a reconstruction — it's just one chat,
    # so it's excluded by default and only returned when include_singletons is set.
    if include_singletons:
        kept = list(threads)
    else:
        kept = [t for t in threads if t.size >= min_size]

    kept.sort(key=lambda t: t.size, reverse=True)
    logger.info(
        "Reconstructed %d multi-fragment project threads from %d coding "
        "conversations (%d returned)",
        len([t for t in threads if t.size >= 2]), n, len(kept),
    )
    return kept


def _build_thread(convs: list[Conversation], basis: str) -> ProjectThread:
    # Chronological order; conversations without a timestamp sort last but are kept.
    convs_sorted = sorted(
        convs,
        key=lambda c: (c.create_time is None, c.create_time or datetime.min),
    )
    times = [c.create_time for c in convs_sorted if c.create_time]
    name = _pick_name(convs_sorted)
    langs: Counter[str] = Counter()
    code_blocks = 0
    for c in convs_sorted:
        for t in c.tags:
            if t not in ("coding", "has-code", "app-creation") and not t.startswith("project:"):
                langs[t] += 1
        code_blocks += len(c.all_code_blocks)

    return ProjectThread(
        name=name,
        conversations=convs_sorted,
        first_activity=min(times) if times else None,
        last_activity=max(times) if times else None,
        languages=[l for l, _ in langs.most_common(5)],
        code_block_count=code_blocks,
        merge_basis=basis,
    )


def _pick_name(convs: list[Conversation]) -> str:
    """Prefer a detected project name; else a distinctive CamelCase token; else title."""
    names = Counter(
        _normalize_project_name(c.coding_project_name)
        for c in convs
        if c.coding_project_name and _is_real_project_name(c.coding_project_name)
    )
    if names:
        # return the original-cased version of the most common normalized name
        target = names.most_common(1)[0][0]
        for c in convs:
            if c.coding_project_name and _normalize_project_name(c.coding_project_name) == target:
                return c.coding_project_name
    # fall back to the earliest conversation's title
    return convs[0].title or "Untitled project"


# ── Timeline ─────────────────────────────────────────────────────────

def build_timeline(
    conversations: list[Conversation],
    period: str = "month",
) -> list[dict]:
    """Bucket activity over time. period = 'day' | 'month' | 'year'.

    Conversations without a timestamp are grouped under the 'unknown' bucket so
    they're visible, not silently discarded.
    """
    fmt = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}.get(period, "%Y-%m")
    buckets: dict[str, dict] = {}

    for c in conversations:
        key = c.create_time.strftime(fmt) if c.create_time else "unknown"
        b = buckets.setdefault(key, {"period": key, "total": 0, "by_category": Counter()})
        b["total"] += 1
        b["by_category"][c.category] += 1

    ordered_keys = sorted(k for k in buckets if k != "unknown")
    if "unknown" in buckets:
        ordered_keys.append("unknown")

    out = []
    for k in ordered_keys:
        b = buckets[k]
        out.append({
            "period": b["period"],
            "total": b["total"],
            "by_category": dict(b["by_category"].most_common()),
        })
    return out
