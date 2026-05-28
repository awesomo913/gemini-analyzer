"""LLM-powered insights: per-conversation refinement, project summaries, reviews.

Wraps llm_client + llm_cache with prompts designed for the free-tier OpenRouter
models. Every public function FAILS SOFT — if no API key is set or the call
errors, it returns None (or a fallback dict) so the UI keeps working with
keyword-only categorization. Nothing here ever raises out to the caller.

Cached results are keyed by content signature; re-running uses zero API calls
on items already processed.
"""

import json
import re
import logging
from dataclasses import dataclass, asdict, field
from typing import Optional, Callable

from parser import Conversation
from reconstruct import ProjectThread
from llm_client import LLMClient
from llm_cache import LLMCache

logger = logging.getLogger(__name__)

# Prompt-schema versions — bump if you change a prompt so old cache entries are
# treated as misses instead of fed back as stale answers.
_REFINE_NAMESPACE = "refine_conv_v1"
_SUMMARY_NAMESPACE = "project_summary_v1"
_REVIEW_NAMESPACE = "project_review_v1"

# Char caps so we don't push huge contexts at free-tier rate limits.
_CONV_PROMPT_CHARS = 800
_CONV_RESPONSE_CHARS = 2000
_PROJECT_DIGEST_PER_CONV = 350
_PROJECT_MAX_CONVS_IN_DIGEST = 25


# ── Result types ─────────────────────────────────────────────────────

@dataclass
class ConversationInsight:
    category: str = ""
    subcategory: str = ""
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    project_name_suggestion: str = ""
    model: str = ""


@dataclass
class ProjectSummary:
    name_suggestion: str = ""
    what_it_is: str = ""
    languages: list[str] = field(default_factory=list)
    status: str = ""
    next_step: str = ""
    key_files: list[str] = field(default_factory=list)
    model: str = ""


@dataclass
class ProjectReview:
    markdown: str = ""
    model: str = ""


# ── Helpers ──────────────────────────────────────────────────────────

def default_client_from_config(config) -> LLMClient:
    return LLMClient(
        model=config.get("llm_model"),
        fallback_models=config.get("llm_fallback_models") or [],
        temperature=config.get("llm_temperature", 0.2),
        max_tokens=config.get("llm_max_tokens", 1024),
        timeout=config.get("llm_timeout", 60),
    )


def _truncate(text: str, n: int) -> str:
    if not text:
        return ""
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _parse_json_object(text: str) -> Optional[dict]:
    """Be forgiving: free models sometimes wrap JSON in ```json fences or prose."""
    if not text:
        return None
    text = text.strip()
    # strip code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # last-ditch: pull the first {...} span
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _coerce_str_list(value, cap: int = 8) -> list[str]:
    if isinstance(value, list):
        out = [str(x).strip() for x in value if str(x).strip()]
        return out[:cap]
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()][:cap]
    return []


# ── Per-conversation refinement ──────────────────────────────────────

_REFINE_SYSTEM = (
    "You are a precise classifier of AI chat conversations. "
    "Output ONLY a JSON object — no prose, no markdown fences. "
    "Schema: "
    '{"category": "<short top-level category>", '
    '"subcategory": "<short>", '
    '"tags": ["<short tag>", ...], '
    '"summary": "<one sentence, max 80 chars>", '
    '"project_name_suggestion": "<short name or empty string>"}'
)


def refine_conversation(
    conv: Conversation,
    client: LLMClient,
    cache: Optional[LLMCache] = None,
) -> Optional[ConversationInsight]:
    if cache is not None:
        cached = cache.get(_REFINE_NAMESPACE, client.model, conv.id)
        if cached:
            try:
                return ConversationInsight(**cached)
            except TypeError as e:
                logger.warning("Stale ConversationInsight cache for %s — refetching: %s", conv.id, e)

    user_msg = " ".join(m.text for m in conv.user_messages)[:_CONV_PROMPT_CHARS]
    model_msg = " ".join(m.text for m in conv.model_messages)[:_CONV_RESPONSE_CHARS]
    prompt = (
        f"Title: {conv.title}\n"
        f"Activity type: {conv.activity_type}\n"
        f"User said: {_truncate(user_msg, _CONV_PROMPT_CHARS)}\n"
        f"Model replied: {_truncate(model_msg, _CONV_RESPONSE_CHARS)}\n"
        f"Existing keyword guess: {conv.category} / {conv.subcategory or '-'}\n"
        f"Classify and summarize this conversation."
    )
    result = client.complete(prompt, system=_REFINE_SYSTEM)
    if not result.success:
        logger.debug("refine_conversation skipped (%s): %s", conv.id, result.error)
        return None

    data = _parse_json_object(result.text)
    if not data:
        logger.debug("refine_conversation: non-JSON response from %s", result.model)
        return None

    insight = ConversationInsight(
        category=str(data.get("category", "")).strip(),
        subcategory=str(data.get("subcategory", "")).strip(),
        tags=_coerce_str_list(data.get("tags")),
        summary=str(data.get("summary", "")).strip()[:120],
        project_name_suggestion=str(data.get("project_name_suggestion", "")).strip()[:60],
        model=result.model,
    )
    if cache is not None:
        cache.set(_REFINE_NAMESPACE, client.model, conv.id, asdict(insight))
    return insight


def refine_all(
    conversations: list[Conversation],
    client: LLMClient,
    cache: Optional[LLMCache] = None,
    max_to_refine: Optional[int] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict[str, ConversationInsight]:
    """Bulk refine. Per-conversation failures are skipped, never crash the batch.
    Returns a dict keyed by conversation id (only successful refinements)."""
    out: dict[str, ConversationInsight] = {}
    targets = conversations[:max_to_refine] if max_to_refine else conversations
    total = len(targets)
    for i, conv in enumerate(targets):
        try:
            insight = refine_conversation(conv, client, cache)
        except Exception as e:  # never let one bad conv break the batch
            logger.warning("refine_all: skipping %s: %s", conv.id, e)
            insight = None
        if insight is not None:
            out[conv.id] = insight
        if on_progress is not None:
            try:
                on_progress(i + 1, total)
            except Exception as e:
                logger.debug("refine_all: on_progress callback raised: %s", e)
    logger.info("refine_all: %d/%d conversations refined", len(out), total)
    return out


# ── Project-level summary ────────────────────────────────────────────

_SUMMARY_SYSTEM = (
    "You are summarizing a software project reconstructed from many AI chat "
    "fragments. Output ONLY a JSON object — no prose, no fences. Schema: "
    '{"name_suggestion": "<short proper-noun project name>", '
    '"what_it_is": "<one sentence>", '
    '"languages": ["<lang>", ...], '
    '"status": "<short, e.g. early prototype / in progress / shipped / abandoned>", '
    '"next_step": "<actionable one-liner, max 120 chars>", '
    '"key_files": ["<filename>", ...]}'
)


def _project_signature(thread: ProjectThread) -> str:
    first = thread.conversations[0].id if thread.conversations else ""
    last = thread.conversations[-1].id if thread.conversations else ""
    return f"{thread.name}|{thread.size}|{first}|{last}"


def _project_digest(thread: ProjectThread) -> str:
    """Compact representation: per-conv title + first user line, bounded total size."""
    lines = []
    for c in thread.conversations[:_PROJECT_MAX_CONVS_IN_DIGEST]:
        first_user = next((m.text for m in c.user_messages), "")
        chunk = f"- [{c.id}] {c.title}\n  user: {_truncate(first_user, _PROJECT_DIGEST_PER_CONV)}"
        lines.append(chunk)
    if thread.size > _PROJECT_MAX_CONVS_IN_DIGEST:
        lines.append(f"… and {thread.size - _PROJECT_MAX_CONVS_IN_DIGEST} more conversations omitted")
    return "\n".join(lines)


def summarize_project(
    thread: ProjectThread,
    client: LLMClient,
    cache: Optional[LLMCache] = None,
) -> Optional[ProjectSummary]:
    if not thread.conversations:
        return None
    sig = _project_signature(thread)
    if cache is not None:
        cached = cache.get(_SUMMARY_NAMESPACE, client.model, sig)
        if cached:
            try:
                return ProjectSummary(**cached)
            except TypeError as e:
                logger.warning("Stale ProjectSummary cache for %s — refetching: %s", thread.name, e)

    span = f"{thread.span_days}d" if thread.span_days is not None else "unknown"
    prompt = (
        f"Reconstructed project name (best guess): {thread.name}\n"
        f"Fragments stitched together: {thread.size}\n"
        f"Time span: {span}\n"
        f"Languages detected (keyword pass): {', '.join(thread.languages) or 'none'}\n"
        f"Code blocks seen: {thread.code_block_count}\n"
        f"Conversation digest:\n{_project_digest(thread)}\n\n"
        f"Summarize this project. Suggest a clean name if the current one looks like a "
        f"sentence fragment. Identify status and one realistic next step to ship it."
    )
    result = client.complete(prompt, system=_SUMMARY_SYSTEM)
    if not result.success:
        logger.debug("summarize_project skipped (%s): %s", thread.name, result.error)
        return None
    data = _parse_json_object(result.text)
    if not data:
        return None

    summary = ProjectSummary(
        name_suggestion=str(data.get("name_suggestion", "")).strip()[:80],
        what_it_is=str(data.get("what_it_is", "")).strip()[:300],
        languages=_coerce_str_list(data.get("languages"), cap=8),
        status=str(data.get("status", "")).strip()[:60],
        next_step=str(data.get("next_step", "")).strip()[:160],
        key_files=_coerce_str_list(data.get("key_files"), cap=10),
        model=result.model,
    )
    if cache is not None:
        cache.set(_SUMMARY_NAMESPACE, client.model, sig, asdict(summary))
    return summary


# ── Deeper "review" — markdown, on demand ────────────────────────────

_REVIEW_SYSTEM = (
    "You are a senior engineer reviewing a software project reconstructed from "
    "scattered AI chat sessions. Reply in concise Markdown (no JSON). Sections: "
    "## What this project actually is, ## Blind spots & risks, "
    "## Highest-leverage next move, ## Claude-ready handoff. "
    "Be specific. Avoid generic advice."
)


def review_project(
    thread: ProjectThread,
    client: LLMClient,
    cache: Optional[LLMCache] = None,
) -> Optional[ProjectReview]:
    if not thread.conversations:
        return None
    sig = _project_signature(thread)
    if cache is not None:
        cached = cache.get(_REVIEW_NAMESPACE, client.model, sig)
        if cached:
            try:
                return ProjectReview(**cached)
            except TypeError as e:
                logger.warning("Stale ProjectReview cache for %s — refetching: %s", thread.name, e)

    span = f"{thread.span_days}d" if thread.span_days is not None else "unknown"
    prompt = (
        f"Project: {thread.name}\n"
        f"Stitched from {thread.size} chat fragments over {span}.\n"
        f"Languages: {', '.join(thread.languages) or 'none detected'}\n"
        f"Code blocks: {thread.code_block_count}\n\n"
        f"Fragments:\n{_project_digest(thread)}\n\n"
        f"Give a real, specific review with the four required sections."
    )
    # Reviews want more room than refinements.
    result = client.chat(
        [{"role": "system", "content": _REVIEW_SYSTEM},
         {"role": "user", "content": prompt}],
        max_tokens=1800,
        temperature=0.3,
    )
    if not result.success:
        logger.debug("review_project skipped (%s): %s", thread.name, result.error)
        return None
    review = ProjectReview(markdown=result.text.strip(), model=result.model)
    if cache is not None:
        cache.set(_REVIEW_NAMESPACE, client.model, sig, asdict(review))
    return review
