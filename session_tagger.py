#!/usr/bin/env python3
"""Session tag/label and notes system for PS1 AI Player.

Manages user-defined tags (e.g. "good_run", "boss_fight", "failed") and
free-text notes for sessions.  Tags are persisted in ``session_tags.json``,
notes in ``session_notes.json``, both alongside session CSVs.

Usage:
    python session_tagger.py tag <csv_filename> <tag1> [tag2 ...]
    python session_tagger.py untag <csv_filename> <tag1> [tag2 ...]
    python session_tagger.py list-tags [--log-dir logs/]
    python session_tagger.py show <csv_filename> [--log-dir logs/]
    python session_tagger.py note <csv_filename> <text>
    python session_tagger.py show-note <csv_filename> [--log-dir logs/]
    python session_tagger.py delete-note <csv_filename> [--log-dir logs/]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from log_config import get_logger

logger = get_logger(__name__)


class SessionTagger:
    """Manage tags/labels for sessions persisted in JSON."""

    def __init__(self, log_dir: str | Path = "logs") -> None:
        self.log_dir = Path(log_dir)

    @property
    def _tags_path(self) -> Path:
        """Return the path to the session tags JSON file."""
        return self.log_dir / "session_tags.json"

    def _load(self) -> dict[str, list[str]]:
        """Load tags JSON.  Returns empty dict if file is missing."""
        if not self._tags_path.exists():
            return {}
        try:
            data = json.loads(self._tags_path.read_text())
            if not isinstance(data, dict):
                return {}
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, list[str]]) -> None:
        """Write tags JSON."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._tags_path.write_text(json.dumps(data, indent=2) + "\n")

    def tag(self, csv_filename: str, *tags: str) -> list[str]:
        """Add tags to a session.  Returns the updated tag list.

        Tags are normalised to lowercase with whitespace stripped.
        Duplicates are ignored.
        """
        data = self._load()
        existing = data.get(csv_filename, [])
        for t in tags:
            normalised = t.strip().lower()
            if normalised and normalised not in existing:
                existing.append(normalised)
        data[csv_filename] = existing
        self._save(data)
        logger.debug("Tagged %s: %s", csv_filename, existing)
        return existing

    def untag(self, csv_filename: str, *tags: str) -> list[str]:
        """Remove tags from a session.  Returns the updated tag list.

        If no tags remain, the entry is removed from the JSON entirely.
        Missing tags are silently ignored.
        """
        data = self._load()
        existing = data.get(csv_filename, [])
        normalised = {t.strip().lower() for t in tags}
        existing = [t for t in existing if t not in normalised]
        if existing:
            data[csv_filename] = existing
        else:
            data.pop(csv_filename, None)
        self._save(data)
        logger.debug("Untagged %s: %s", csv_filename, existing)
        return existing

    def get_tags(self, csv_filename: str) -> list[str]:
        """Get tags for a session.  Returns empty list if none."""
        return self._load().get(csv_filename, [])

    def list_tags(self) -> dict[str, list[str]]:
        """Return all session -> tags mappings."""
        return self._load()

    def sessions_with_tag(self, tag: str) -> list[str]:
        """Return all CSV filenames that have a given tag."""
        normalised = tag.strip().lower()
        return [
            csv for csv, tags in self._load().items()
            if normalised in tags
        ]

    def all_known_tags(self) -> list[str]:
        """Return sorted unique list of all tags across all sessions."""
        tags: set[str] = set()
        for tag_list in self._load().values():
            tags.update(tag_list)
        return sorted(tags)

    # -- Notes ---------------------------------------------------------------

    @property
    def _notes_path(self) -> Path:
        """Return the path to the session notes JSON file."""
        return self.log_dir / "session_notes.json"

    def _load_notes(self) -> dict[str, str]:
        """Load notes JSON.  Returns empty dict if file is missing."""
        if not self._notes_path.exists():
            return {}
        try:
            data = json.loads(self._notes_path.read_text())
            if not isinstance(data, dict):
                return {}
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_notes(self, data: dict[str, str]) -> None:
        """Write notes JSON."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._notes_path.write_text(json.dumps(data, indent=2) + "\n")

    def set_note(self, csv_filename: str, text: str) -> str:
        """Set (or replace) the note for a session.  Returns the saved text.

        Leading/trailing whitespace is stripped.  Empty text deletes the note.
        """
        text = text.strip()
        data = self._load_notes()
        if text:
            data[csv_filename] = text
        else:
            data.pop(csv_filename, None)
        self._save_notes(data)
        logger.debug("Note set for %s: %s", csv_filename, text[:50] if text else "(deleted)")
        return text

    def get_note(self, csv_filename: str) -> str:
        """Get the note for a session.  Returns empty string if none."""
        return self._load_notes().get(csv_filename, "")

    def delete_note(self, csv_filename: str) -> None:
        """Delete the note for a session."""
        data = self._load_notes()
        if csv_filename in data:
            del data[csv_filename]
            self._save_notes(data)
            logger.debug("Note deleted for %s", csv_filename)

    def list_notes(self) -> dict[str, str]:
        """Return all session -> note mappings."""
        return self._load_notes()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for session tagging."""
    parser = argparse.ArgumentParser(description="Session Tag/Label System")
    parser.add_argument(
        "--log-dir", default="logs", help="Log directory (default: logs/)"
    )
    sub = parser.add_subparsers(dest="command")

    # tag
    tag_p = sub.add_parser("tag", help="Add tags to a session")
    tag_p.add_argument("csv_filename", help="CSV filename (not full path)")
    tag_p.add_argument("tags", nargs="+", help="Tags to add")

    # untag
    untag_p = sub.add_parser("untag", help="Remove tags from a session")
    untag_p.add_argument("csv_filename", help="CSV filename (not full path)")
    untag_p.add_argument("tags", nargs="+", help="Tags to remove")

    # list-tags
    sub.add_parser("list-tags", help="Show all sessions and their tags")

    # show
    show_p = sub.add_parser("show", help="Show tags for a specific session")
    show_p.add_argument("csv_filename", help="CSV filename (not full path)")

    # note
    note_p = sub.add_parser("note", help="Set a note for a session")
    note_p.add_argument("csv_filename", help="CSV filename (not full path)")
    note_p.add_argument("text", nargs="+", help="Note text")

    # show-note
    show_note_p = sub.add_parser("show-note", help="Show note for a session")
    show_note_p.add_argument("csv_filename", help="CSV filename (not full path)")

    # delete-note
    del_note_p = sub.add_parser("delete-note", help="Delete note for a session")
    del_note_p.add_argument("csv_filename", help="CSV filename (not full path)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    tagger = SessionTagger(log_dir=args.log_dir)

    if args.command == "tag":
        result = tagger.tag(args.csv_filename, *args.tags)
        print(f"{args.csv_filename}: {result}")

    elif args.command == "untag":
        result = tagger.untag(args.csv_filename, *args.tags)
        print(f"{args.csv_filename}: {result}")

    elif args.command == "list-tags":
        data = tagger.list_tags()
        if not data:
            print("No tags found.")
        else:
            for csv, tags in sorted(data.items()):
                print(f"  {csv}: {tags}")

    elif args.command == "show":
        tags = tagger.get_tags(args.csv_filename)
        print(f"{args.csv_filename}: {tags}")

    elif args.command == "note":
        text = " ".join(args.text)
        result = tagger.set_note(args.csv_filename, text)
        print(f"{args.csv_filename} note: {result}")

    elif args.command == "show-note":
        note = tagger.get_note(args.csv_filename)
        if note:
            print(f"{args.csv_filename} note: {note}")
        else:
            print(f"{args.csv_filename}: no note")

    elif args.command == "delete-note":
        tagger.delete_note(args.csv_filename)
        print(f"{args.csv_filename}: note deleted")


if __name__ == "__main__":
    main()
