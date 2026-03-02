#!/usr/bin/env python3
"""Session exporter — bundle session artifacts into a ZIP archive and
import ZIP bundles back into the log directory.

Exported ZIP contents:
  - {stem}.csv                (step-by-step CSV log)
  - {stem}.session.json       (cost/state/strategy summary)
  - {stem}.history.json       (action history records)
  - analysis/action_report.md (ActionAnalyzer report, if action column exists)
  - analysis/cross_session.md (CrossSessionAnalyzer report, if multiple sessions)
  - analysis/cross_session.json (CrossSessionAnalyzer JSON output)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

from log_config import get_logger
from session_replay import ActionAnalyzer, SessionData

logger = get_logger(__name__)


class SessionExporter:
    """Export / import session artifacts as ZIP bundles."""

    def __init__(self, session: SessionData) -> None:
        self.session = session

    def export_zip(self, output_path: str | Path) -> Path:
        """Bundle session files + generated analysis into a ZIP archive.

        Returns the resolved output path.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Core session files
            if self.session.csv_path.exists():
                zf.write(self.session.csv_path, self.session.csv_path.name)
            if self.session.session_path.exists():
                zf.write(self.session.session_path, self.session.session_path.name)
            if self.session.history_path.exists():
                zf.write(self.session.history_path, self.session.history_path.name)

            # Action analysis report
            analyzer = ActionAnalyzer(self.session)
            report = analyzer.format_report()
            zf.writestr("analysis/action_report.md", report)

            # Cross-session report (if there are sibling sessions)
            try:
                siblings = SessionData.discover_sessions(
                    self.session.csv_path.parent,
                    game_id=self.session.game_id,
                )
                if len(siblings) >= 2:
                    from cross_session_analyzer import CrossSessionAnalyzer

                    cross = CrossSessionAnalyzer(siblings)
                    zf.writestr("analysis/cross_session.md", cross.to_markdown())
                    zf.writestr(
                        "analysis/cross_session.json",
                        json.dumps(cross.to_dict(), indent=2, default=str),
                    )
            except Exception as exc:
                logger.debug("Cross-session analysis skipped: %s", exc)

        logger.info("Exported session to %s", output_path)
        return output_path

    def export_bytes(self) -> bytes:
        """Export to an in-memory ZIP and return the raw bytes."""
        import io

        buf = io.BytesIO()
        # Write to buffer via a temp approach
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if self.session.csv_path.exists():
                zf.write(self.session.csv_path, self.session.csv_path.name)
            if self.session.session_path.exists():
                zf.write(self.session.session_path, self.session.session_path.name)
            if self.session.history_path.exists():
                zf.write(self.session.history_path, self.session.history_path.name)

            analyzer = ActionAnalyzer(self.session)
            zf.writestr("analysis/action_report.md", analyzer.format_report())

            try:
                siblings = SessionData.discover_sessions(
                    self.session.csv_path.parent,
                    game_id=self.session.game_id,
                )
                if len(siblings) >= 2:
                    from cross_session_analyzer import CrossSessionAnalyzer

                    cross = CrossSessionAnalyzer(siblings)
                    zf.writestr("analysis/cross_session.md", cross.to_markdown())
                    zf.writestr(
                        "analysis/cross_session.json",
                        json.dumps(cross.to_dict(), indent=2, default=str),
                    )
            except Exception:
                pass

        return buf.getvalue()

    @staticmethod
    def list_zip_contents(zip_path: str | Path) -> list[str]:
        """List filenames in a session ZIP archive."""
        zip_path = Path(zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            return zf.namelist()

    @staticmethod
    def import_zip(zip_path: str | Path, target_dir: str | Path) -> list[Path]:
        """Extract session files from a ZIP into *target_dir*.

        Only extracts recognised session files (CSV, .session.json,
        .history.json). Analysis files are skipped during import.

        Returns a list of extracted file paths.
        """
        zip_path = Path(zip_path)
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        extracted: list[Path] = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                # Only extract top-level session artifacts (not analysis/)
                if "/" in name:
                    continue
                if not (
                    name.endswith(".csv")
                    or name.endswith(".session.json")
                    or name.endswith(".history.json")
                ):
                    continue
                dest = target_dir / name
                with zf.open(name) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(dest)
                logger.info("Extracted %s -> %s", name, dest)

        return extracted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="session_exporter",
        description="Export / import session artifacts as ZIP bundles.",
    )
    sub = parser.add_subparsers(dest="command")

    # export
    p_export = sub.add_parser("export", help="Export a session to ZIP")
    p_export.add_argument("csv_path", help="Path to session CSV")
    p_export.add_argument(
        "--output", default=None,
        help="Output ZIP path (default: <stem>.zip next to CSV)",
    )

    # import
    p_import = sub.add_parser("import", help="Import a session from ZIP")
    p_import.add_argument("zip_path", help="Path to session ZIP")
    p_import.add_argument(
        "--target-dir", default="logs",
        help="Target directory for extracted files (default: logs/)",
    )

    # list
    p_list = sub.add_parser("list", help="List contents of a session ZIP")
    p_list.add_argument("zip_path", help="Path to session ZIP")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "export":
        session = SessionData.from_log_path(args.csv_path)
        exporter = SessionExporter(session)
        if args.output:
            out = Path(args.output)
        else:
            out = session.csv_path.with_suffix(".zip")
        result = exporter.export_zip(out)
        print(f"Exported to {result}")

    elif args.command == "import":
        extracted = SessionExporter.import_zip(args.zip_path, args.target_dir)
        if extracted:
            print(f"Imported {len(extracted)} file(s) to {args.target_dir}:")
            for f in extracted:
                print(f"  {f.name}")
        else:
            print("No session files found in ZIP.")

    elif args.command == "list":
        contents = SessionExporter.list_zip_contents(args.zip_path)
        for name in contents:
            print(name)


if __name__ == "__main__":
    main()
