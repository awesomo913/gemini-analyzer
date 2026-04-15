# Security Notes — GeminiAnalyzer

## Input Validation
- **JSON parsing**: All JSON files are loaded with `json.load()` which rejects malformed input. Unicode errors use `errors="replace"` to prevent crashes.
- **ZIP handling**: Uses Python's `zipfile` module with extraction to a temporary directory. Files are cleaned up in a `finally` block.
- **Path traversal**: All file paths use `pathlib.Path` and are resolved before use. No raw string concatenation for paths.
- **File type validation**: Only `.json` and `.zip` files are accepted. Directory traversal uses `rglob("*.json")` to restrict file types.

## Data at Rest
- **Config storage**: Settings are stored as plain JSON in the platform-appropriate config directory (`AppData/Local`, `~/.config`, or `Library/Application Support`). No sensitive data is stored in config.
- **No credentials**: The application does not handle any passwords, API keys, or authentication tokens.
- **Diagnostic reports**: Explicitly filter out any keys containing "password", "key", "token", or "secret" from diagnostic output.

## Logging
- **Rotating logs**: `RotatingFileHandler` with 5 MB max size and 3 backup files prevents unbounded disk usage.
- **No sensitive data in logs**: Log messages contain only operational information (file paths, counts, errors).

## Clipboard Operations
- **User-initiated only**: Clipboard operations (`clipboard_clear`, `clipboard_append`) only execute on explicit user action (button click or keyboard shortcut).

## Temporary Files
- **Cleanup**: ZIP extraction uses `tempfile.mkdtemp()` and cleanup is guaranteed via `finally` block with `shutil.rmtree()`.

## Platform Compliance
- **Windows**: No admin rights required. Writes only to user directories.
- **Linux/FHS**: Config in `~/.config/GeminiAnalyzer/`, logs in same directory. No writes outside home.
- **macOS**: Config in `~/Library/Application Support/GeminiAnalyzer/`.

## Remaining Risks
- TODO (LOW): Large JSON files could consume significant memory. Consider streaming parser for files > 500 MB.
- TODO (LOW): No file locking on config — concurrent instances could overwrite each other's settings.
