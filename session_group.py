#!/usr/bin/env python3
"""Session group management for PS1 AI Player.

Organises sessions into experiment groups (e.g. "Strategy A vs B",
"Tuning round 3").  Groups are persisted in ``session_groups.json``
alongside session CSVs.

Usage:
    python session_group.py create <group_name> [--description TEXT] [--log-dir logs/]
    python session_group.py delete <group_name> [--log-dir logs/]
    python session_group.py add <group_name> <csv_filename> [csv_filename ...] [--log-dir logs/]
    python session_group.py remove <group_name> <csv_filename> [csv_filename ...] [--log-dir logs/]
    python session_group.py list [--log-dir logs/]
    python session_group.py show <group_name> [--log-dir logs/] [--format markdown|json]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from log_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# SessionGroup dataclass
# ---------------------------------------------------------------------------

@dataclass
class SessionGroup:
    """A named group of sessions with optional description."""

    name: str
    description: str = ""
    members: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "members": list(self.members),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionGroup:
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            members=list(data.get("members", [])),
        )


# ---------------------------------------------------------------------------
# SessionGroupManager — CRUD + aggregate stats
# ---------------------------------------------------------------------------

class SessionGroupManager:
    """Manage session groups persisted in JSON."""

    def __init__(self, log_dir: str | Path = "logs") -> None:
        self.log_dir = Path(log_dir)

    @property
    def _groups_path(self) -> Path:
        return self.log_dir / "session_groups.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        """Load groups JSON.  Returns empty dict if file is missing."""
        if not self._groups_path.exists():
            return {}
        try:
            data = json.loads(self._groups_path.read_text())
            if not isinstance(data, dict):
                return {}
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        """Write groups JSON."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._groups_path.write_text(json.dumps(data, indent=2) + "\n")

    # -- CRUD ---------------------------------------------------------------

    def create_group(self, name: str, description: str = "") -> SessionGroup:
        """Create a new group.  Raises ValueError if it already exists."""
        name = name.strip()
        if not name:
            raise ValueError("Group name must not be empty")
        data = self._load()
        if name in data:
            raise ValueError(f"Group already exists: {name}")
        group = SessionGroup(name=name, description=description.strip())
        data[name] = group.to_dict()
        self._save(data)
        logger.debug("Created group: %s", name)
        return group

    def delete_group(self, name: str) -> None:
        """Delete a group.  Raises KeyError if it does not exist."""
        data = self._load()
        if name not in data:
            raise KeyError(f"Group not found: {name}")
        del data[name]
        self._save(data)
        logger.debug("Deleted group: %s", name)

    def get_group(self, name: str) -> SessionGroup:
        """Return a single group.  Raises KeyError if not found."""
        data = self._load()
        if name not in data:
            raise KeyError(f"Group not found: {name}")
        return SessionGroup.from_dict(data[name])

    def list_groups(self) -> list[SessionGroup]:
        """Return all groups sorted by name."""
        data = self._load()
        groups = [SessionGroup.from_dict(v) for v in data.values()]
        groups.sort(key=lambda g: g.name)
        return groups

    def add_sessions(self, name: str, *csv_filenames: str) -> SessionGroup:
        """Add session CSV filenames to a group.  Duplicates are ignored.

        Raises KeyError if the group does not exist.
        """
        data = self._load()
        if name not in data:
            raise KeyError(f"Group not found: {name}")
        group = SessionGroup.from_dict(data[name])
        for fn in csv_filenames:
            fn = fn.strip()
            if fn and fn not in group.members:
                group.members.append(fn)
        data[name] = group.to_dict()
        self._save(data)
        logger.debug("Added %d sessions to %s", len(csv_filenames), name)
        return group

    def remove_sessions(self, name: str, *csv_filenames: str) -> SessionGroup:
        """Remove session CSV filenames from a group.  Missing names are ignored.

        Raises KeyError if the group does not exist.
        """
        data = self._load()
        if name not in data:
            raise KeyError(f"Group not found: {name}")
        group = SessionGroup.from_dict(data[name])
        to_remove = {fn.strip() for fn in csv_filenames}
        group.members = [m for m in group.members if m not in to_remove]
        data[name] = group.to_dict()
        self._save(data)
        logger.debug("Removed sessions from %s", name)
        return group

    def rename_group(self, old_name: str, new_name: str) -> SessionGroup:
        """Rename a group.  Raises KeyError/ValueError as appropriate."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("New group name must not be empty")
        data = self._load()
        if old_name not in data:
            raise KeyError(f"Group not found: {old_name}")
        if new_name in data:
            raise ValueError(f"Group already exists: {new_name}")
        group_data = data.pop(old_name)
        group_data["name"] = new_name
        data[new_name] = group_data
        self._save(data)
        return SessionGroup.from_dict(group_data)

    # -- Aggregate stats ----------------------------------------------------

    def group_stats(self, name: str) -> dict[str, Any]:
        """Compute aggregate statistics for a group's sessions.

        Returns dict with:
          - group: group metadata
          - member_count: int
          - sessions_found: int (members that exist in log_dir)
          - avg_score: float (average SessionScorer total, or None)
          - avg_steps: float
          - avg_cost_usd: float
          - param_comparison: {param: {mean, min, max, std}} across all members
          - member_details: [{csv_filename, score, steps, cost_usd, params}]
        """
        from session_replay import SessionData
        from session_scorer import SessionScorer

        group = self.get_group(name)
        scorer = SessionScorer()

        # Load available sessions
        sessions: list[SessionData] = []
        for fn in group.members:
            csv_path = self.log_dir / fn
            if csv_path.exists():
                try:
                    sessions.append(SessionData.from_log_path(csv_path))
                except (ValueError, FileNotFoundError):
                    continue

        result: dict[str, Any] = {
            "group": group.to_dict(),
            "member_count": len(group.members),
            "sessions_found": len(sessions),
            "avg_score": None,
            "avg_steps": 0.0,
            "avg_cost_usd": 0.0,
            "param_comparison": {},
            "member_details": [],
        }

        if not sessions:
            return result

        # Per-session details
        scores = []
        steps_list = []
        costs = []
        all_params: dict[str, list[float]] = {}

        for s in sessions:
            bd = scorer.score(s)
            scores.append(bd.total)
            steps_list.append(s.total_steps)
            costs.append(s.cost_usd)

            detail: dict[str, Any] = {
                "csv_filename": s.csv_path.name,
                "timestamp": s.timestamp,
                "game_id": s.game_id,
                "score": bd.total,
                "steps": s.total_steps,
                "cost_usd": s.cost_usd,
            }

            # Per-param last values
            param_vals: dict[str, float] = {}
            for p in s.parameters:
                last_val = float(s.df[p].iloc[-1])
                param_vals[p] = last_val
                all_params.setdefault(p, []).append(last_val)
            detail["params"] = param_vals
            result["member_details"].append(detail)

        result["avg_score"] = sum(scores) / len(scores)
        result["avg_steps"] = sum(steps_list) / len(steps_list)
        result["avg_cost_usd"] = sum(costs) / len(costs)

        # Parameter comparison across members
        import statistics as _stats
        for p, vals in sorted(all_params.items()):
            comparison: dict[str, float] = {
                "mean": _stats.mean(vals),
                "min": min(vals),
                "max": max(vals),
            }
            if len(vals) >= 2:
                comparison["std"] = _stats.stdev(vals)
            else:
                comparison["std"] = 0.0
            result["param_comparison"][p] = comparison

        return result

    # -- Output helpers -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return all groups as a JSON-serialisable dict."""
        groups = self.list_groups()
        return {
            "groups": [g.to_dict() for g in groups],
            "total_groups": len(groups),
        }

    def to_markdown(self, name: str | None = None) -> str:
        """Generate a markdown report.

        If *name* is given, show stats for that group.  Otherwise list all.
        """
        if name:
            return self._group_stats_markdown(name)
        return self._list_markdown()

    def _list_markdown(self) -> str:
        lines: list[str] = ["# Session Groups", ""]
        groups = self.list_groups()
        if not groups:
            lines.append("No groups defined.")
            return "\n".join(lines)

        lines.append("| Group | Description | Members |")
        lines.append("|-------|-------------|---------|")
        for g in groups:
            lines.append(f"| {g.name} | {g.description} | {len(g.members)} |")
        lines.append("")
        return "\n".join(lines)

    def _group_stats_markdown(self, name: str) -> str:
        stats = self.group_stats(name)
        g = stats["group"]
        lines: list[str] = [
            f"# Group: {g['name']}",
            "",
            f"**Description:** {g['description'] or '(none)'}",
            f"**Members:** {stats['member_count']} ({stats['sessions_found']} found)",
            "",
        ]

        if stats["avg_score"] is not None:
            lines.append(f"**Average Score:** {stats['avg_score']:.1f}")
        lines.append(f"**Average Steps:** {stats['avg_steps']:.1f}")
        lines.append(f"**Average Cost:** ${stats['avg_cost_usd']:.4f}")
        lines.append("")

        # Parameter comparison table
        pc = stats["param_comparison"]
        if pc:
            lines.append("## Parameter Comparison")
            lines.append("")
            lines.append("| Parameter | Mean | Min | Max | Std |")
            lines.append("|-----------|------|-----|-----|-----|")
            for p, vals in pc.items():
                lines.append(
                    f"| {p} | {vals['mean']:.2f} | {vals['min']:.2f} "
                    f"| {vals['max']:.2f} | {vals['std']:.2f} |"
                )
            lines.append("")

        # Member details
        details = stats["member_details"]
        if details:
            lines.append("## Members")
            lines.append("")
            lines.append("| Session | Score | Steps | Cost |")
            lines.append("|---------|-------|-------|------|")
            for d in details:
                lines.append(
                    f"| {d['csv_filename']} | {d['score']:.1f} "
                    f"| {d['steps']} | ${d['cost_usd']:.4f} |"
                )
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Session Group Management")
    parser.add_argument("--log-dir", default="logs", help="Log directory (default: logs/)")
    sub = parser.add_subparsers(dest="command")

    # create
    sp_create = sub.add_parser("create", help="Create a new group")
    sp_create.add_argument("name", help="Group name")
    sp_create.add_argument("--description", default="", help="Group description")

    # delete
    sp_delete = sub.add_parser("delete", help="Delete a group")
    sp_delete.add_argument("name", help="Group name")

    # add
    sp_add = sub.add_parser("add", help="Add sessions to a group")
    sp_add.add_argument("name", help="Group name")
    sp_add.add_argument("csv_filenames", nargs="+", help="CSV filenames to add")

    # remove
    sp_remove = sub.add_parser("remove", help="Remove sessions from a group")
    sp_remove.add_argument("name", help="Group name")
    sp_remove.add_argument("csv_filenames", nargs="+", help="CSV filenames to remove")

    # list
    sub.add_parser("list", help="List all groups")

    # show
    sp_show = sub.add_parser("show", help="Show group details and stats")
    sp_show.add_argument("name", help="Group name")
    sp_show.add_argument("--format", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    mgr = SessionGroupManager(log_dir=args.log_dir)

    if args.command == "create":
        group = mgr.create_group(args.name, description=args.description)
        print(f"Created group: {group.name}")

    elif args.command == "delete":
        try:
            mgr.delete_group(args.name)
            print(f"Deleted group: {args.name}")
        except KeyError as e:
            print(str(e))
            raise SystemExit(1)

    elif args.command == "add":
        try:
            group = mgr.add_sessions(args.name, *args.csv_filenames)
            print(f"Group {group.name}: {len(group.members)} members")
        except KeyError as e:
            print(str(e))
            raise SystemExit(1)

    elif args.command == "remove":
        try:
            group = mgr.remove_sessions(args.name, *args.csv_filenames)
            print(f"Group {group.name}: {len(group.members)} members")
        except KeyError as e:
            print(str(e))
            raise SystemExit(1)

    elif args.command == "list":
        md = mgr.to_markdown()
        print(md)

    elif args.command == "show":
        try:
            if args.format == "json":
                stats = mgr.group_stats(args.name)
                print(json.dumps(stats, indent=2))
            else:
                print(mgr.to_markdown(args.name))
        except KeyError as e:
            print(str(e))
            raise SystemExit(1)


if __name__ == "__main__":
    main()
