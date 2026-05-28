"""Markdown export + Claude-ready project bundles + NON-DESTRUCTIVE dedup report.

Critical guarantee: nothing in this module ever deletes, overwrites, or modifies
the user's source Takeout. Dedup produces a *report* (a markdown file listing
duplicate groups by id) — the originals stay where they are.

Outputs are written to a folder the caller specifies; the function returns the
written paths so the UI can show or open them.
"""

import re
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from typing import Optional

from parser import Conversation
from reconstruct import ProjectThread
from insights import ProjectSummary, ProjectReview

logger = logging.getLogger(__name__)


# ── Filenames ────────────────────────────────────────────────────────

_SAFE_NAME_RE = re.compile(r"[^\w\-. ]+", re.UNICODE)


def _slug(name: str, fallback: str = "project") -> str:
    cleaned = _SAFE_NAME_RE.sub("", name).strip().replace(" ", "_")
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:80] or fallback


# ── Conversation → markdown ──────────────────────────────────────────

def conversation_to_markdown(conv: Conversation, *, include_meta: bool = True) -> str:
    """Render one conversation as markdown. Preserves embedded code fences."""
    lines: list[str] = []
    title = conv.title or f"Conversation {conv.id}"
    lines.append(f"# {title}")
    if include_meta:
        meta = []
        if conv.create_time:
            meta.append(f"**Date:** {conv.create_time.isoformat(timespec='seconds')}")
        if conv.activity_type:
            meta.append(f"**Activity:** {conv.activity_type}")
        if conv.category:
            cat = conv.category + (f" / {conv.subcategory}" if conv.subcategory else "")
            meta.append(f"**Category:** {cat}")
        if conv.tags:
            meta.append(f"**Tags:** {', '.join(conv.tags)}")
        if conv.coding_project_name:
            meta.append(f"**Project:** {conv.coding_project_name}")
        if meta:
            lines.append("")
            lines.append(" · ".join(meta))
    lines.append("")

    for msg in conv.messages:
        who = "**You**" if msg.role == "user" else "**Gemini**"
        ts = f" · _{msg.timestamp.isoformat(timespec='seconds')}_" if msg.timestamp else ""
        lines.append(f"### {who}{ts}")
        if msg.attachments:
            lines.append(f"_attachments: {', '.join(msg.attachments)}_")
        lines.append("")
        lines.append((msg.text or "").strip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── Project bundle (Claude-ready) ────────────────────────────────────

def project_bundle_markdown(
    thread: ProjectThread,
    *,
    summary: Optional[ProjectSummary] = None,
    review: Optional[ProjectReview] = None,
) -> str:
    """Multi-section markdown bundle designed to paste straight into Claude."""
    lines: list[str] = []
    display_name = (summary.name_suggestion or thread.name) if summary else thread.name
    lines.append(f"# Project: {display_name}")
    lines.append("")
    lines.append(f"_Reconstructed from {thread.size} Gemini chat fragments._")
    if thread.first_activity and thread.last_activity:
        lines.append(
            f"_Spanning {thread.first_activity.date()} → {thread.last_activity.date()} "
            f"({thread.span_days} days)._"
        )
    if thread.languages:
        lines.append(f"_Languages seen: {', '.join(thread.languages)}._")
    lines.append("")

    if summary:
        lines.append("## What this project is")
        if summary.what_it_is:
            lines.append(summary.what_it_is)
        lines.append("")
        if summary.status:
            lines.append(f"**Status:** {summary.status}")
        if summary.next_step:
            lines.append(f"**Recommended next step:** {summary.next_step}")
        if summary.key_files:
            lines.append(f"**Key files:** {', '.join(summary.key_files)}")
        lines.append("")

    if review and review.markdown:
        lines.append("## Review")
        lines.append(review.markdown)
        lines.append("")

    lines.append("## Code recovered")
    any_code = False
    for c in thread.conversations:
        blocks = c.all_code_blocks
        if not blocks:
            continue
        any_code = True
        lines.append(f"### From: {c.title}")
        if c.create_time:
            lines.append(f"_{c.create_time.isoformat(timespec='seconds')}_")
        for b in blocks:
            lang = b.get("language", "text")
            code = b.get("code", "").rstrip()
            lines.append(f"```{lang}")
            lines.append(code)
            lines.append("```")
        lines.append("")
    if not any_code:
        lines.append("_No code blocks were extracted from this project._")
        lines.append("")

    lines.append("## Conversations (chronological)")
    for c in thread.conversations:
        when = c.create_time.isoformat(timespec="seconds") if c.create_time else "?"
        lines.append(f"- {when} — {c.title} (`{c.id}`)")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_project_bundle(
    thread: ProjectThread,
    out_dir: Path,
    *,
    summary: Optional[ProjectSummary] = None,
    review: Optional[ProjectReview] = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    display_name = (summary.name_suggestion if summary and summary.name_suggestion else thread.name)
    slug = _slug(display_name)
    content = project_bundle_markdown(thread, summary=summary, review=review)

    # Atomic uniquify: open with 'x' (exclusive create). If another writer wins
    # the race we get FileExistsError, bump the counter, and try the next name.
    candidate = out_dir / f"{slug}.md"
    counter = 1
    while True:
        try:
            with open(candidate, "x", encoding="utf-8") as f:
                f.write(content)
            break
        except FileExistsError:
            candidate = out_dir / f"{slug}_{counter}.md"
            counter += 1
            if counter > 10_000:  # don't spin forever on a pathological dir
                raise RuntimeError(f"Could not find a free filename for {slug} after 10000 attempts")

    logger.info("Wrote project bundle: %s (%d convs)", candidate.name, thread.size)
    return candidate


def write_project_bundles(
    threads: list[ProjectThread],
    out_dir: Path,
    summaries: Optional[dict[str, ProjectSummary]] = None,
    reviews: Optional[dict[str, ProjectReview]] = None,
) -> list[Path]:
    paths = []
    summaries = summaries or {}
    reviews = reviews or {}
    for t in threads:
        key = t.name
        try:
            paths.append(write_project_bundle(
                t, out_dir,
                summary=summaries.get(key),
                review=reviews.get(key),
            ))
        except (OSError, RuntimeError) as e:
            # One bad bundle must not abort the whole batch — log it, keep going.
            logger.error("write_project_bundles: skipping %s: %s", t.name, e)
    return paths


# ── Non-destructive dedup ────────────────────────────────────────────

@dataclass
class DedupGroup:
    content_hash: str
    conversation_ids: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)


_NORMALIZE_TS = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4},\s+"
    r"\d{1,2}:\d{2}(?::\d{2})?\s*(?: |\s)*[AP]M(?:\s+\w+)?",
    re.IGNORECASE,
)


def _normalize_for_dedup(text: str) -> str:
    text = _NORMALIZE_TS.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _content_hash(conv: Conversation) -> str:
    """Hash the FULL normalized user-message sequence — not titles or IDs."""
    payload = " || ".join(_normalize_for_dedup(m.text) for m in conv.user_messages)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def find_duplicates(conversations: list[Conversation]) -> list[DedupGroup]:
    """Group conversations by normalized user-message content. Returns only
    groups with 2+ members. NEVER modifies source conversations."""
    groups: dict[str, DedupGroup] = {}
    for c in conversations:
        if not c.user_messages:
            continue
        h = _content_hash(c)
        g = groups.setdefault(h, DedupGroup(content_hash=h))
        g.conversation_ids.append(c.id)
        g.titles.append(c.title)
    dups = [g for g in groups.values() if len(g.conversation_ids) >= 2]
    dups.sort(key=lambda g: len(g.conversation_ids), reverse=True)
    logger.info(
        "find_duplicates: %d duplicate groups (%d redundant conversations across them)",
        len(dups), sum(len(g.conversation_ids) - 1 for g in dups),
    )
    return dups


def write_dedup_report(conversations: list[Conversation], out_dir: Path) -> Path:
    """Write a markdown report of duplicate groups. SOURCE FILES UNTOUCHED."""
    dups = find_duplicates(conversations)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"dedup_report_{stamp}.md"

    redundant = sum(len(g.conversation_ids) - 1 for g in dups)
    lines = [
        "# Duplicate-conversation report",
        "",
        f"_Generated {datetime.now().isoformat(timespec='seconds')}._",
        f"_Total conversations scanned: {len(conversations)}._",
        f"_Duplicate groups found: {len(dups)}._",
        f"_Redundant conversations (would be removed if you collapsed each group): {redundant}._",
        "",
        "> Your source Takeout is unchanged. This is a report only. To collapse, ",
        "> use the report as a guide to manually decide which copies to keep.",
        "",
    ]
    for i, g in enumerate(dups, 1):
        lines.append(f"## Group {i} — {len(g.conversation_ids)} copies (hash `{g.content_hash}`)")
        for cid, title in zip(g.conversation_ids, g.titles):
            lines.append(f"- `{cid}` — {title}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote dedup report: %s", path.name)
    return path
