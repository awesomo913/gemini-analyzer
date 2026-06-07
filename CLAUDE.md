<!-- claude-backend:generated:start -->
# gemini_analyzer

## Overview

- **Files**: 19 (.py (12), .md (7))
- **Entry points**: `categorizer.py`, `main.py`
- **Key files**: `README.md`, `requirements.txt`, `.gitignore`

## Structure

```
tests/  (1 files)
```

## Conventions

- Use `pathlib.Path` for all path operations
- Type hints are used extensively -- maintain them
- Use specific exception types in except clauses
- Use `logging.getLogger(__name__)` for all logging
- Absolute imports preferred

## Modules

- `categorizer.py` -- Conversation categorization engine with coding project detection
- `config_manager.py` -- Cross-platform settings persistence and configuration
- `diagnostics.py` -- Diagnostic report generation and logging setup
- `export.py` -- Markdown export + Claude-ready project bundles + NON-DESTRUCTIVE dedup report
- `insights.py` -- LLM-powered insights: per-conversation refinement, project summaries, reviews
- `llm_cache.py` -- On-disk cache for LLM results — each conversation is processed at most once
- `llm_client.py` -- OpenRouter LLM client — stdlib only, fails closed, privacy-safe logging
- `main.py` -- GeminiAnalyzer — Parse, categorize, and extract code from Gemini exports [entry]
- `parser.py` -- Gemini Takeout data parser — handles HTML and JSON export formats
- `reconstruct.py` -- Project reconstruction + timeline
- `tests/test_gemini_analyzer.py` -- Regression tests for GeminiAnalyzer
- `ui_app.py` -- Main application UI — modern dark-themed Gemini Analyzer

<!-- claude-backend:generated:end -->
