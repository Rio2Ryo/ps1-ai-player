#!/usr/bin/env python3
"""Session search & filter for PS1 AI Player.

Filter sessions by parameter conditions (e.g. hp last > 50, gold mean > 1000),
step count range, date/time range, and tag/note full-text search.

Usage:
    python session_search.py search --log-dir logs/ --param "hp last > 50"
    python session_search.py search --log-dir logs/ --param "gold mean > 1000" --steps 10-100
    python session_search.py search --log-dir logs/ --date 20250101-20250201 --tag good_run
    python session_search.py search --log-dir logs/ --note "boss fight" --format json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from log_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# ParamCondition — a single parameter filter
# ---------------------------------------------------------------------------

_OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

_AGGREGATORS = {"last", "first", "mean", "min", "max", "std"}

# Pattern: "hp last > 50" or "gold mean >= 1000.5"
_COND_RE = re.compile(
    r"^\s*(\w+)\s+(last|first|mean|min|max|std)\s*"
    r"([><!]=?|==|!=)\s*(-?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


@dataclass
class ParamCondition:
    """A single parameter filter condition."""

    parameter: str
    aggregator: str  # last, first, mean, min, max, std
    operator: str  # >, >=, <, <=, ==, !=
    value: float

    @classmethod
    def parse(cls, text: str) -> ParamCondition:
        """Parse a condition string like ``'hp last > 50'``."""
        m = _COND_RE.match(text)
        if not m:
            raise ValueError(
                f"Invalid condition: {text!r}.  "
                f"Expected format: '<param> <last|first|mean|min|max|std> <op> <number>'"
            )
        return cls(
            parameter=m.group(1),
            aggregator=m.group(2).lower(),
            operator=m.group(3),
            value=float(m.group(4)),
        )

    def evaluate(self, session) -> bool:
        """Test this condition against a SessionData object."""
        if self.parameter not in session.df.columns:
            return False
        import pandas as pd

        if not pd.api.types.is_numeric_dtype(session.df[self.parameter]):
            return False
        col = session.df[self.parameter]
        if self.aggregator == "last":
            actual = float(col.iloc[-1])
        elif self.aggregator == "first":
            actual = float(col.iloc[0])
        elif self.aggregator == "mean":
            actual = float(col.mean())
        elif self.aggregator == "min":
            actual = float(col.min())
        elif self.aggregator == "max":
            actual = float(col.max())
        elif self.aggregator == "std":
            actual = float(col.std())
        else:
            return False
        return _OPERATORS[self.operator](actual, self.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "aggregator": self.aggregator,
            "operator": self.operator,
            "value": self.value,
        }


# ---------------------------------------------------------------------------
# SessionSearch — main search engine
# ---------------------------------------------------------------------------

@dataclass
class SessionSearch:
    """Search and filter sessions by multiple criteria."""

    log_dir: Path = field(default_factory=lambda: Path("logs"))
    param_conditions: list[ParamCondition] = field(default_factory=list)
    min_steps: int | None = None
    max_steps: int | None = None
    date_from: str | None = None  # YYYYMMDD
    date_to: str | None = None  # YYYYMMDD
    tag: str | None = None
    note_query: str | None = None

    def search(self) -> list:
        """Run the search and return matching SessionData objects."""
        from session_replay import SessionData
        from session_tagger import SessionTagger

        sessions = SessionData.discover_sessions(self.log_dir)
        tagger = SessionTagger(log_dir=self.log_dir)

        results = []
        for s in sessions:
            if not self._match(s, tagger):
                continue
            results.append(s)
        return results

    def _match(self, session, tagger) -> bool:
        """Return True if session passes all filters."""
        # Step count range
        if self.min_steps is not None and session.total_steps < self.min_steps:
            return False
        if self.max_steps is not None and session.total_steps > self.max_steps:
            return False

        # Date range (compare YYYYMMDD strings — they sort lexicographically)
        ts_date = session.timestamp[:8]  # "YYYYMMDD" portion
        if self.date_from is not None and ts_date < self.date_from:
            return False
        if self.date_to is not None and ts_date > self.date_to:
            return False

        # Tag filter
        if self.tag is not None:
            tags = tagger.get_tags(session.csv_path.name)
            if self.tag.strip().lower() not in tags:
                return False

        # Note full-text search (case-insensitive substring)
        if self.note_query is not None:
            note = tagger.get_note(session.csv_path.name)
            if self.note_query.lower() not in note.lower():
                return False

        # Parameter conditions — all must match
        for cond in self.param_conditions:
            if not cond.evaluate(session):
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the search criteria."""
        d: dict[str, Any] = {"log_dir": str(self.log_dir)}
        if self.param_conditions:
            d["param_conditions"] = [c.to_dict() for c in self.param_conditions]
        if self.min_steps is not None:
            d["min_steps"] = self.min_steps
        if self.max_steps is not None:
            d["max_steps"] = self.max_steps
        if self.date_from is not None:
            d["date_from"] = self.date_from
        if self.date_to is not None:
            d["date_to"] = self.date_to
        if self.tag is not None:
            d["tag"] = self.tag
        if self.note_query is not None:
            d["note_query"] = self.note_query
        return d

    def to_markdown(self, results: list) -> str:
        """Generate a Markdown report of search results."""
        lines: list[str] = ["# Session Search Results", ""]

        # Criteria
        lines.append("## Search Criteria")
        if self.param_conditions:
            for c in self.param_conditions:
                lines.append(
                    f"- {c.parameter} {c.aggregator} {c.operator} {c.value}"
                )
        if self.min_steps is not None or self.max_steps is not None:
            lines.append(
                f"- Steps: {self.min_steps or '*'} — {self.max_steps or '*'}"
            )
        if self.date_from or self.date_to:
            lines.append(
                f"- Date: {self.date_from or '*'} — {self.date_to or '*'}"
            )
        if self.tag:
            lines.append(f"- Tag: {self.tag}")
        if self.note_query:
            lines.append(f"- Note contains: {self.note_query!r}")
        lines.append("")

        # Results
        lines.append(f"## Results ({len(results)} sessions)")
        lines.append("")
        if results:
            lines.append("| Timestamp | Game ID | Steps | Cost |")
            lines.append("|-----------|---------|-------|------|")
            for s in results:
                lines.append(
                    f"| {s.timestamp} | {s.game_id} | {s.total_steps} "
                    f"| ${s.cost_usd:.4f} |"
                )
        else:
            lines.append("No sessions matched the criteria.")
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_steps_range(text: str) -> tuple[int | None, int | None]:
    """Parse ``'10-100'`` or ``'10-'`` or ``'-100'`` into (min, max)."""
    parts = text.split("-", 1)
    lo = int(parts[0]) if parts[0].strip() else None
    hi = int(parts[1]) if len(parts) > 1 and parts[1].strip() else None
    return lo, hi


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Session search & filter"
    )
    sub = parser.add_subparsers(dest="command")

    sp = sub.add_parser("search", help="Search sessions")
    sp.add_argument("--log-dir", default="logs")
    sp.add_argument(
        "--param", action="append", default=[],
        help="Parameter condition, e.g. 'hp last > 50'",
    )
    sp.add_argument("--steps", help="Step range, e.g. '10-100'")
    sp.add_argument("--date", help="Date range, e.g. '20250101-20250201'")
    sp.add_argument("--tag", help="Filter by tag")
    sp.add_argument("--note", help="Note full-text search")
    sp.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
    )

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        raise SystemExit(2)

    conditions = [ParamCondition.parse(p) for p in args.param]

    min_steps = max_steps = None
    if args.steps:
        min_steps, max_steps = _parse_steps_range(args.steps)

    date_from = date_to = None
    if args.date:
        parts = args.date.split("-", 1)
        date_from = parts[0].strip() if parts[0].strip() else None
        date_to = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

    searcher = SessionSearch(
        log_dir=Path(args.log_dir),
        param_conditions=conditions,
        min_steps=min_steps,
        max_steps=max_steps,
        date_from=date_from,
        date_to=date_to,
        tag=args.tag,
        note_query=args.note,
    )

    results = searcher.search()

    if args.format == "json":
        out = {
            "criteria": searcher.to_dict(),
            "count": len(results),
            "sessions": [
                {
                    "csv_filename": s.csv_path.name,
                    "timestamp": s.timestamp,
                    "game_id": s.game_id,
                    "steps": s.total_steps,
                    "cost_usd": s.cost_usd,
                }
                for s in results
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print(searcher.to_markdown(results))


if __name__ == "__main__":
    main()
