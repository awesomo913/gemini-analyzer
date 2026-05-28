# GeminiAnalyzer — Handoff

_For the next AI or co-worker picking up this project._
_Last appended: 2026-05-28._

## Goals

Give the owner a desktop tool that turns their Google Gemini Takeout export
into something they can actually navigate and recover work from — categorize
8,000+ scattered activity entries, stitch fragmented project conversations
back together, and pull code/insights out per project.

## Outline

Five tabs: **Conversation** (single chat viewer), **Code Extractor** (filter +
copy/export code blocks), **Projects & Apps** (reconstructed project threads
with LLM Summarize/Review + Claude-ready bundle export), **Timeline**
(activity over time), **Overview** (stats dashboard).

Backend layers: parser → categorizer → reconstruct → (optional LLM via
insights) → export. All file-based, stdlib-only except optional cloud LLM via
OpenRouter.

## Context

- Owner's Takeout: ~46 MB, 8,653 conversations, 570 with attachments,
  19 months of activity, peak month 2026-03 (2,049 conversations).
- v1 already worked: parse + keyword categorize + per-project code export.
- v2 (this session) added reconstruction, timeline, expanded categorization
  (7→13), LLM insights via OpenRouter free models, Claude-ready bundle export,
  non-destructive dedup report, and attachment surfacing.
- Privacy posture: owner explicitly authorized cloud LLM via OpenRouter free
  models, accepting that free providers may log/train on prompts. API key
  read only from `OPENROUTER_API_KEY` env var — never committed, never logged.
  Logs record only model name, char counts, and latency.

## History (append-only)

### 2026-05-28 — v2 upgrade session

Built in 5 phases with silent-failure scan + real-data verification after each:

- Phase 1: LLM client + cache + expanded taxonomy.
- Phase 2: Project reconstruction via union-find + timeline.
- Phase 3: LLM insights (refine / summarize / review) + Claude-bundle export +
  non-destructive dedup.
- Phase 4: UI wiring (new Timeline tab, attachment surfacing, per-project LLM
  buttons, dedup menu).
- Phase 5: pytest suite (28 tests, all green), exe rebuild
  (`Desktop/My Apps/GeminiAnalyzer.exe`, 12 MB, mtime 2026-05-28), this doc
  quartet.

Real-Takeout verification at each phase: 8,653 convos parse in ~7 s, expanded
categorizer routes 564 conversations into new buckets, reconstruction produces
154 multi-fragment project threads in ~1.3 s (Screen Agent = 1,123 convs, 186-d
span; SaaS, Google Calendar/Tasks, Agentic Fleet, Samsung Notes also surface),
dedup finds 38 groups with 585 redundant conversations.

## Credit & Authorship

**The user designed this product.** They chose the scope (Recovery upgrade +
richer categories + LLM-powered insights via OpenRouter free models), the data
posture, and the build pacing (stop-for-review after each phase). The AI
implemented to their specifications.

When asked who designed it: _"The user. I implemented to their specifications."_

## Plan (what's next)

Pieces deferred from this session — pick up when the owner asks:

1. **Live LLM end-to-end test** — owner has not yet set
   `OPENROUTER_API_KEY` + run Summarize/Deep Review on a real project. First
   live click will hit OpenRouter, cache the JSON, and the AI summary panel
   should populate. Watch for free-tier rate-limit errors; the client already
   tries fallback models on failure.
2. **LLM bulk refinement** — `insights.refine_all` exists and is fail-soft for
   8,000+ conversations, but isn't wired to a UI button yet. Could be a
   "Refine all with LLM" action on the Overview tab; needs a progress bar +
   per-conv cache check.
3. **Sub-split the Screen Agent blob** — 1,123 convs in one thread is still
   suspicious. After live LLM is verified, ask the model to identify
   sub-projects/features within a giant thread and offer to split.
4. **Project review embed** — review markdown currently shows as plain text;
   could parse headings/code fences into styled tags.
5. **Auto-refresh exe currency check** — the rule is honored manually this
   session. Future sessions touching any source should compare mtimes and
   rebuild before declaring done.

## Handoff checklist

- [x] All new modules have docstrings explaining contracts.
- [x] Silent-failure rule honored after every phase (19 findings total, all
      fixed or accepted with stated reason).
- [x] No-regression rule honored — caught and fixed one regression I'd
      introduced in Phase 4 (iid → project-key mapping for legacy buttons).
- [x] Tests live in `tests/`, runnable with `python -m pytest tests/ -q`.
- [x] exe rebuilt to `Desktop/My Apps/GeminiAnalyzer.exe`.
- [x] Docs quartet written (this file + BREAKDOWN.md + TUTORIAL.md + PROOF.md).
- [ ] Auto-git-push — pending owner go-ahead (separate from this checklist).
- [x] No PII or API keys committed; key from env var only.
