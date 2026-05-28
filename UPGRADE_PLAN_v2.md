# GeminiAnalyzer v2 — Upgrade Plan (handoff for next session)

Status: SCOPE LOCKED by owner. Not started. Next session (Opus + opusplan) should
turn this into a formal plan, let the plan-review swarm vet it, then build backend-first.

## Owner decisions (locked)
- Scope = "Recovery upgrade" + richer categories + LLM-powered insights/reviews.
- Data posture = **cloud-first via OpenRouter, FREE models only** (owner accepted that
  free models may log/train on prompts; money is not a concern, privacy tradeoff accepted).
- API key = `OPENROUTER_API_KEY` env var. Never hardcode, never commit.
- Model = config setting, default a free reasoner. Free IDs seen May 2026:
  `deepseek/deepseek-v4-flash:free` (1M ctx), `google/gemma-4-31b-it:free`,
  `nvidia/nemotron-3-super-120b-a12b:free`. Lineup shifts — keep configurable.

## App today (baseline — already works, ~11s load, 8,653 convos, no external deps)
- `parser.py` — Takeout ZIP/folder/MyActivity.html/JSON → Conversation objects.
  ALREADY parses `timestamp`, `create_time`, `update_time`, `attachments[]` (currently unused).
- `categorizer.py` — keyword bag-of-words, 7 categories + subcats, regex project-name detect.
  `categorize_conversation()` returns CategoryResult; `categorize_all()` is the batch entry.
- `ui_app.py` (1648 lines) — tkinter dark UI, 4 tabs (Conversation / Code Extractor /
  Projects & Apps / Overview), threaded load, copy + per-project export.
- `main.py` CLI+GUI, `config_manager.py`, `diagnostics.py`.

## Build plan (backend-first, verify each phase before next)

### Phase 1 — LLM backend + richer categories
- `llm_client.py` — OpenRouter chat call. Key from env, model from config, free default.
  Boundary-logged, retries, FAILS CLOSED if no key (no silent fallback).
- `llm_cache.py` — disk cache conv-id → result, in user config dir, gitignored.
  Each conversation hits API at most once.
- Expand static taxonomy in `categorizer.py` (more categories + subcategories) for the
  instant free first-pass.
- Verify on a sample of the real Takeout; show proof before moving on.

### Phase 2 — Reconstruction + timeline
- `reconstruct.py` — stitch fragmented activity entries into per-project threads
  (group by project name + code/file identity), order by existing timestamps.
- This is the highest-leverage piece (blind-spot reviewer): Takeout shatters one real
  project into dozens of disjoint entries; app categorizes fragments but never reassembles.

### Phase 3 — LLM insights + export
- `insights.py` — LLM richer category + dynamic topic tags per conversation; on-demand
  "review/insight on this project."
- `export.py` — full-conversation markdown + Claude-ready per-project bundle
  (prompt + code + context).
- Non-destructive dedup: full-content hash, write NEW collapsed view, NEVER delete source,
  flag-for-review not auto-remove.

### Phase 4 — UI wiring (after backend verified)
- New **Timeline** tab. Surface **attachments** (parsed, hidden today).
- Per-project **"Deep insight / Review"** button → OpenRouter.
- Dedup action + Claude-ready bundle export buttons.
- All LLM work threaded, OFF the 11s load path; progress + cache status shown.

### Phase 5 — Plumbing (workspace rules)
- pytest tests for parser + categorizer + reconstruct.
- crash-logger telemetry BUT log IDs/counts only, NEVER conversation text (PII guardrail).
- Rebuild exe → `Desktop/My Apps/GeminiAnalyzer.exe`. Refresh BREAKDOWN/HANDOFF/TUTORIAL/PROOF.

## Guardrails (from review swarm)
- API key env-var only; in-app note that free models may log prompts.
- LLM results cached (no repeat cost/exposure).
- Dedup non-destructive (new file, full-content hash, never delete).
- Telemetry logs never capture conversation `.text`.
- All per-conversation heavy work opt-in / background; never regress the 11s load.

## Cut / deferred (swarm consensus)
- Multi-source (ChatGPT/Claude parser) — CUT, no second export exists, scrambles order.
- Embeddings/vector search — DEFERRED; if search needed, plain full-text first (no API).
- (Owner overrode the "local-only" privacy recommendation in favor of free cloud models.)
