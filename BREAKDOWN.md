# GeminiAnalyzer — Technical Breakdown

_Last updated: 2026-05-28._

## What it does

Turns a Google Takeout export of Gemini Apps activity into a navigable,
categorized desktop app. Beyond the v1 sort-and-extract baseline, v2 adds:

- **Project reconstruction** — stitches scattered activity entries into
  multi-fragment project threads with chronological order and time span.
- **Timeline view** — day / month / year buckets of activity over time with
  top-category breakdown.
- **Expanded categorization** — 13 categories (was 7); added Writing & Editing,
  Productivity & Planning, Finance & Money, Media & Design, Hardware &
  Electronics, Gaming.
- **LLM-powered insights** — OpenRouter free-model pass for per-project
  Summarize and Deep Review. Caches results to disk so each project is sent at
  most once.
- **Claude-ready bundle export** — per-project markdown bundle (header +
  summary + review + extracted code + chronological conversation list)
  designed to paste straight into Claude.
- **Non-destructive dedup report** — finds duplicate conversations and writes
  a markdown report; the source Takeout is never modified.
- **Attachment surfacing** — file attachments parsed by v1 but hidden in the
  UI are now visible in both the conversation viewer and the project detail.

## How to run

```bash
python main.py                     # default GUI
python main.py /path/to/Takeout    # auto-load on launch
python main.py --diagnostics       # write a diagnostic report to Desktop
```

Windows shortcut: `Start GeminiAnalyzer.bat` in the parent folder. Standalone
binary: `~/Desktop/My Apps/GeminiAnalyzer.exe`.

To enable cloud LLM features, set the API key first:

```powershell
setx OPENROUTER_API_KEY "your-key-here"   # then restart the app
```

Without a key, the app runs offline with keyword categorization, project
reconstruction, timeline, dedup report, and Claude-ready bundles. The
Summarize / Deep Review buttons surface a friendly notice.

## Architecture

```
main.py          CLI entry + GUI bootstrap
 └─ ui_app.py    tkinter dark UI (5 tabs)
     ├─ parser.py        Takeout HTML / JSON / ZIP → Conversation objects
     ├─ categorizer.py   Keyword-scored category + subcategory + tags + project name regex
     ├─ reconstruct.py   Union-find clustering → ProjectThread; build_timeline
     ├─ insights.py      LLM refine / summarize / review (cached, fail-soft)
     ├─ export.py        Markdown + Claude bundle + non-destructive dedup report
     ├─ llm_client.py    OpenRouter chat client (stdlib urllib, no deps)
     ├─ llm_cache.py     Disk cache under AppData (each project sent ≤ once)
     ├─ config_manager.py  Cross-platform settings persistence
     └─ diagnostics.py   Logging + diagnostic report to Desktop
```

`Conversation` and `Message` dataclasses are the lingua franca: parser writes
them, categorizer + reconstruct + export read them. Nothing mutates them after
parse + categorize.

### Reconstruction algorithm

Union-find clustering on coding conversations using two signals:

1. **Project-name match** — a categorizer-detected project name passes
   `_is_real_project_name` (rejects SQL keywords, sentence fragments, single-word
   stopwords) becomes the merge anchor.
2. **Rare code identifiers** — filenames, class names, def names extracted from
   the first 4 KB of each conversation. An identifier merges conversations only
   when it appears in ≥ 2 conversations but ≤ min(0.5%, 20) of the corpus —
   tight enough to avoid the transitive-chaining over-merge that pulled
   ~2,000 conversations into one blob in early iterations.

Threads with size < `min_size` (default 2) are dropped from the default return;
`include_singletons=True` returns lone conversations as one-item threads.

### LLM integration

`llm_client.LLMClient` posts to `https://openrouter.ai/api/v1/chat/completions`
via stdlib `urllib` (no `requests` dep). Key read from `OPENROUTER_API_KEY`
env var only; no other source. On any failure (no key, HTTP error, timeout,
malformed response) it returns `LLMResult(success=False, error=...)` — never
raises, never returns a fake success.

`insights` functions cache results in `AppData/Local/GeminiAnalyzer/llm_cache/`,
keyed by content signature so re-running zero re-bills.

## Key decisions + why

| Decision | Why |
|---|---|
| stdlib `urllib` over `requests` | Preserves the original "no external deps" promise. Lean exe. |
| Free OpenRouter models default | User authorized cloud calls but cost-sensitivity → use `:free` tier. |
| Cache by signature, not by id alone | Switching models re-runs deliberately; same model = no double-charge. |
| Dedup writes a report, not deletes | Hash collisions on titles + categorizer noise mean automatic delete is unsafe. Source Takeout must be inviolable. |
| Union-find tightened DF cap | Initial 2 % cap chained unrelated projects into a 2,092-conv blob. Cap dropped to min(0.5 %, 20). |
| Multi-fragment-only default | Lone "named singletons" added ~860 rows of noise. Real reconstruction = 2+ stitched fragments. |
| LLM ops threaded with stale-result guard | A fast click between projects must not let stale callbacks stomp the new project's UI status. |
| Project name stopwords + fragment filter | Categorizer's regex catches SQL keywords and prompt fragments; reconstruct guards against them. |

## Dev log

### 2026-05-28 — v2 upgrade (this session)

- **Phase 1**: `llm_client.py`, `llm_cache.py`; expanded `categorizer.py` 7→13
  categories. Verified on real Takeout (8,653 convos, 7.4 s parse, 5.8 s
  categorize; 564 convs reclassified into new buckets). Silent-failure scan
  fixed 4 findings: HTTP-error swallow, cache-clear swallow, prompt-fragment in
  log lines, timeout portability.
- **Phase 2**: `reconstruct.py` with union-find clustering + `build_timeline`.
  Three tuning iterations (over-merge 2,092 → 1,123 → 154 real multi-fragment
  threads). Silent-failure scan fixed 3: None-name crash in `_pick_name`,
  basis mislabel from in-loop assignment (now post-union pass), missing scope
  log. Final: 154 multi-fragment projects in 1.3 s.
- **Phase 3**: `insights.py` (`refine_conversation`, `summarize_project`,
  `review_project`, bulk `refine_all`), `export.py` (markdown + Claude bundle
  + dedup report). Silent-failure scan fixed 5: stale-cache schema crash,
  TOCTOU on bundle uniquify (now `open(path, 'x')`), batch abort on single
  failure, None-text crash, callback swallow.
- **Phase 4**: UI wiring. New Timeline tab. Projects tab now uses
  reconstruction; added Name + Span columns and per-project Summarize / Deep
  Review / Claude-bundle buttons. Tools menu → Find Duplicates → save report.
  Attachment field exposed in conversation viewer and project detail. Silent-
  failure scan fixed 7: caught and fixed a regression I had introduced (tree
  iid → project key map missing, silently no-op'ing the legacy Copy/Export
  buttons), plus None-safe attachments, guarded `by_category`, stale-callback
  status stomping, error-detail surfacing, `_on_close` swallow, reconstruct
  try/except.
- **Phase 5**: pytest suite (28 tests, 0.66 s, all green), exe rebuild, this
  doc quartet.
