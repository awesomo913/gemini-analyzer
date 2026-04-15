# GeminiAnalyzer

Parse, categorize, and extract code from your Google Gemini conversation exports.

## What it does

Takes a Google Takeout export of your Gemini Apps data (ZIP or extracted folder) and gives you:

- **Automatic categorization** — 7 top-level categories (Coding, Creative Writing, Research, Business, Math/Science, Naming, Personal) with subcategories
- **Coding project detection** — finds the apps, programs, and tools you built, groups conversations by project name
- **Code Extractor** — every code block from every conversation, filterable by language, conversation, activity type, min lines, or text content. One-click copy to clipboard, ready to paste into Claude or another tool
- **Projects & Apps tab** — multi-select projects, batch-export all code per project to separate files
- **Modern dark UI** — tkinter + ttk with custom theme, keyboard shortcuts, search, settings persistence
- **Diagnostic reports** saved to Desktop
- Handles the real Google Takeout format: ZIP archives, extracted folders, `MyActivity.html`, or JSON exports

Tested against a real 46 MB Takeout with 8,653 conversations (11 second load).

## Run it

```bash
python main.py
```

Or on Windows, use `Start GeminiAnalyzer.bat` from the parent folder.

Then **File > Open Folder** and point it at your extracted `Takeout` folder, or **File > Open File** and pick the takeout ZIP directly.

## Requirements

Python 3.10+ with tkinter (included in standard installs). No external dependencies.

## Files

- `main.py` — entry point and CLI
- `parser.py` — parses Takeout HTML/JSON/ZIP
- `categorizer.py` — categorization engine
- `ui_app.py` — tkinter UI
- `config_manager.py` — cross-platform settings
- `diagnostics.py` — logging and diagnostic reports
- `SECURITY_NOTES.md` — security audit notes
