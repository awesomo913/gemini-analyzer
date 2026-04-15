"""GeminiAnalyzer — Parse, categorize, and extract code from Gemini exports."""

import sys
import argparse
import logging
from pathlib import Path

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="gemini_analyzer",
        description="Analyze Google Gemini Takeout exports — categorize conversations and extract code.",
    )
    ap.add_argument("path", nargs="?", default=None,
                    help="Path to a JSON file, ZIP archive, or Takeout folder to auto-load.")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                    help="Logging verbosity (default: INFO).")
    ap.add_argument("--theme", default=None, choices=["dark", "light"],
                    help="Override color theme.")
    ap.add_argument("--diagnostics", action="store_true",
                    help="Generate a diagnostic report to the Desktop and exit.")
    args = ap.parse_args()

    from diagnostics import setup_logging, generate_report
    setup_logging(args.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting GeminiAnalyzer")

    if args.diagnostics:
        report = generate_report(save_to_desktop=True)
        print(report)
        print("\nDiagnostic report saved to Desktop.")
        return

    from config_manager import Config
    config = Config()
    if args.theme:
        config.theme = args.theme
        config.save()

    from ui_app import GeminiAnalyzerApp
    app = GeminiAnalyzerApp()

    if args.path:
        p = Path(args.path).resolve()
        if p.exists():
            app.root.after(500, lambda: app._load_data(p))
        else:
            logger.error("Path not found: %s", p)

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical("Unhandled exception: %s", e, exc_info=True)
        generate_report(save_to_desktop=True)
        raise


if __name__ == "__main__":
    main()
