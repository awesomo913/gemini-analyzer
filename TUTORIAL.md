# GeminiAnalyzer — User Tutorial

_Last updated: 2026-05-28 (v2)._

## Quickstart

1. **Download your Gemini data** from [takeout.google.com](https://takeout.google.com),
   select *Gemini Apps*, finish the export. You'll get a ZIP.
2. **Open the app.** Either:
   - double-click `Desktop/My Apps/GeminiAnalyzer.exe` (Windows), or
   - run `python main.py` from the `gemini_analyzer` folder.
3. **File → Open File…** and pick the ZIP, OR **File → Open Folder…** and
   pick the unzipped Takeout folder. The status bar shows progress.
4. Explore the five tabs in the right panel.

To enable cloud LLM features (optional):

```powershell
setx OPENROUTER_API_KEY "your-key-here"
```

Get a free key at [openrouter.ai](https://openrouter.ai), then restart the app.

## Feature walkthrough

### Conversation tab
Click any conversation in the left list. You'll see role-tagged messages,
embedded code blocks rendered with syntax-friendly styling, and the 📎
**attachments** line under each message that had files attached.

### Code Extractor tab
Every code block from every conversation, filterable by language, source
conversation, activity type, minimum lines, or text search. Select one (or
several) and **Copy Selected** to paste into Claude/IDE. **Copy All Visible**
grabs everything matching your current filter.

### Projects & Apps tab
Shows **reconstructed projects** — fragmented activity entries stitched back
together using shared project names and rare code identifiers. Columns:
*Project*, *Convs* (how many fragments stitched), *Span* (days from first to
last activity), *Code* blocks, *Languages*.

Click a project to see:
- A header line with size, span, languages, and merge basis
  (`project_name` if Gemini explicitly named it; `shared_code_identity` if it
  was reconstructed from shared filenames/classes).
- AI summary / AI review panes if you've clicked the LLM buttons.
- Each fragment conversation listed chronologically with attachments + code
  block previews.

**Per-project actions** (top of the detail pane):
- **Summarize (LLM)** — sends a compact digest of the project to OpenRouter and
  asks for a one-line description, status, and one realistic next step. Result
  is cached on disk; clicking again is free.
- **Deep Review (LLM)** — bigger prompt; gets a four-section markdown review
  (what it is, blind spots, highest-leverage next move, Claude-ready handoff).
- **Export Claude Bundle…** — writes a `<project>.md` to a folder you pick,
  containing summary (if any) + review (if any) + all extracted code + a
  chronological conversation index. Designed to paste straight into Claude
  Code as project context.

**Multi-project actions** (action bar above the list):
- **Export Selected (code only)** / **Export All (code only)** — original v1
  behavior: one `*_code.txt` per project with all the code blocks concatenated.
- **Copy Selected Code** — same content, to clipboard.
- **Export Claude-ready Bundles…** — bundle version of the above for every
  selected project.

### Timeline tab
Bucket conversations by day, month, or year (top-right dropdown). For each
bucket: total conversations, an ASCII bar showing relative volume, and the
top 4 categories that month. The summary line on the right shows your peak.

### Overview tab
Top-line stats: total, coding count, app/program creation count, total code
blocks, projects. Plus category breakdown, language histogram, and project
list.

## Recipes

**"Pull my BambooForest project into Claude":**
1. Projects & Apps tab → find/click *BambooForest* (or whatever your project's
   called).
2. Click **Deep Review (LLM)** — wait for the panes to update.
3. Click **Export Claude Bundle…** → pick `Desktop/`.
4. Open `Desktop/BambooForest.md` in Claude Code or paste it into Claude.ai.

**"What was I building in March 2026?":**
1. Timeline tab → switch dropdown to *month* → look for `2026-03`.
2. See top categories for that month, then Projects & Apps tab → sort threads
   whose span covers March.

**"Find and clean up duplicates":**
Tools menu → **Find Duplicates → save report…** → pick a folder.
You'll get `dedup_report_<timestamp>.md` listing every duplicate group. Your
source Takeout is **never modified** — the report is a map you use manually.

**"Recover every snippet of Python I wrote with Gemini":**
Code Extractor tab → Language: `python` → **Copy All Visible**.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "LLM idle — set OPENROUTER_API_KEY" | Cloud features disabled — set the env var and restart. |
| Summarize / Deep Review reports "Summarize failed: HTTP 429" | Free-model rate limit — wait a minute, or try again; client retries fallback models automatically. |
| Project list shows "FROM" / "Yes" / a sentence as a name | Categorizer regex caught a false positive; reconstruction filters most of these, but if one slips through, Summarize will rename it. |
| Window doesn't remember position | Window-state save logs the failure to the app log; usually a locked config file. |
| `Tools → Run Diagnostics` shows missing dependency | Should never happen on the packaged exe; on a raw source run, ensure Python 3.10+ with tkinter. |

## FAQ

**Does this send my conversations to the internet?**
Only when *you* click **Summarize** or **Deep Review** on a specific project,
and only if you've set `OPENROUTER_API_KEY`. Categorization, search,
reconstruction, code extraction, timeline, and bundle export are all local.

**Will the exe upload anything on launch?**
No. The app makes zero outbound network calls unless you trigger an LLM
action.

**Can I use a paid OpenRouter model instead of free?**
Yes — `~/.claude/projects/.../GeminiAnalyzer/settings.json` has an `llm_model`
key. Edit it to any OpenRouter model ID (e.g. `anthropic/claude-sonnet-4-6`)
and restart.

**Why are some "projects" only one conversation each in the data?**
By default the Projects tab only shows multi-fragment threads (where 2+
scattered conversations were stitched together). Single-conv projects are
intentionally hidden — they're not really "reconstructions."

## Changelog

- **2026-05-28 — v2:** project reconstruction + Timeline tab + LLM
  Summarize/Review + Claude-ready bundle export + non-destructive dedup
  report + attachment surfacing in UI + 6 new categories (Writing & Editing,
  Productivity & Planning, Finance & Money, Media & Design, Hardware &
  Electronics, Gaming).
- **earlier — v1:** parse Takeout ZIP/HTML/JSON, keyword categorization,
  per-project code export, dark UI.
