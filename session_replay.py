#!/usr/bin/env python3
"""Session Replay Viewer — load, view, compare, and analyze past agent sessions.

Each run.sh session produces three artifacts in logs/:
  - YYYYMMDD_HHMMSS_{GAME_ID}_agent.csv          (step-by-step CSV log)
  - YYYYMMDD_HHMMSS_{GAME_ID}_agent.session.json  (cost/state/strategy summary)
  - YYYYMMDD_HHMMSS_{GAME_ID}_agent.history.json   (last-N action records)

This module provides:
  SessionData       — load all three files for one session
  SessionTimeline   — step-by-step replay / event search
  ActionAnalyzer    — action frequency, transitions, parameter impact, streaks
  SessionComparator — compare 2+ sessions side-by-side (params + actions)
  CLI               — list / show / timeline / compare / events / replay subcommands
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Filename pattern: YYYYMMDD_HHMMSS_{GAME_ID}_agent.csv
# ---------------------------------------------------------------------------
_FILENAME_RE = re.compile(
    r"^(\d{8}_\d{6})_(.+)_agent\.csv$"
)

_FIXED_COLUMNS = {"timestamp", "step", "action", "reasoning", "observations"}


def _df_to_markdown(df: pd.DataFrame, *, index: bool = True) -> str:
    """Convert a DataFrame to a Markdown table without requiring tabulate."""
    cols = list(df.columns)
    if index:
        idx_name = df.index.name or ""
        header = [str(idx_name)] + [str(c) for c in cols]
    else:
        header = [str(c) for c in cols]

    rows: list[list[str]] = []
    for idx_val, row in df.iterrows():
        if index:
            rows.append([str(idx_val)] + [str(row[c]) for c in cols])
        else:
            rows.append([str(row[c]) for c in cols])

    # Compute column widths
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    hdr = "| " + " | ".join(h.ljust(w) for h, w in zip(header, widths)) + " |"
    body = "\n".join(
        "| " + " | ".join(cell.ljust(w) for cell, w in zip(r, widths)) + " |"
        for r in rows
    )
    return f"{hdr}\n{sep}\n{body}"


# ---------------------------------------------------------------------------
# SessionData
# ---------------------------------------------------------------------------

@dataclass
class SessionData:
    """Loads all three artifact files for a single agent session."""

    csv_path: Path
    session_path: Path
    history_path: Path
    game_id: str
    timestamp: str  # "YYYYMMDD_HHMMSS"
    df: pd.DataFrame = field(repr=False)
    session_info: dict[str, Any] = field(repr=False)
    history: list[dict[str, Any]] = field(repr=False)

    # -- Properties ----------------------------------------------------------

    @property
    def total_steps(self) -> int:
        """Number of rows in the CSV log."""
        return len(self.df)

    @property
    def duration_seconds(self) -> float:
        """Wall-clock duration between first and last CSV timestamp."""
        if len(self.df) < 2:
            return 0.0
        ts = pd.to_datetime(self.df["timestamp"])
        delta = ts.iloc[-1] - ts.iloc[0]
        return delta.total_seconds()

    @property
    def cost_usd(self) -> float:
        """Total API cost from session.json, or 0.0 if unavailable."""
        cost = self.session_info.get("cost", {})
        return float(cost.get("total_cost_usd", 0.0))

    @property
    def parameters(self) -> list[str]:
        """Numeric column names (excluding fixed columns like timestamp/step/action)."""
        return [
            c for c in self.df.columns
            if c not in _FIXED_COLUMNS and pd.api.types.is_numeric_dtype(self.df[c])
        ]

    # -- Constructors --------------------------------------------------------

    @classmethod
    def from_log_path(cls, csv_path: str | Path) -> SessionData:
        """Auto-discover sibling .session.json / .history.json from a CSV path."""
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        m = _FILENAME_RE.match(csv_path.name)
        if not m:
            raise ValueError(
                f"Filename does not match expected pattern "
                f"YYYYMMDD_HHMMSS_GAMEID_agent.csv: {csv_path.name}"
            )
        timestamp_str, game_id = m.group(1), m.group(2)

        stem = csv_path.stem  # e.g. 20250101_120000_DEMO_agent
        parent = csv_path.parent
        session_path = parent / f"{stem}.session.json"
        history_path = parent / f"{stem}.history.json"

        df = pd.read_csv(csv_path)

        session_info: dict[str, Any] = {}
        if session_path.exists():
            session_info = json.loads(session_path.read_text())

        history: list[dict[str, Any]] = []
        if history_path.exists():
            history = json.loads(history_path.read_text())

        return cls(
            csv_path=csv_path,
            session_path=session_path,
            history_path=history_path,
            game_id=game_id,
            timestamp=timestamp_str,
            df=df,
            session_info=session_info,
            history=history,
        )

    @classmethod
    def discover_sessions(
        cls,
        log_dir: str | Path = "logs",
        game_id: str | None = None,
    ) -> list[SessionData]:
        """Find all sessions in *log_dir*, optionally filtered by game_id.

        Returns a list sorted by timestamp (ascending).
        """
        log_dir = Path(log_dir)
        if not log_dir.is_dir():
            return []

        sessions: list[SessionData] = []
        for csv_file in sorted(log_dir.glob("*_agent.csv")):
            m = _FILENAME_RE.match(csv_file.name)
            if not m:
                continue
            if game_id is not None and m.group(2) != game_id:
                continue
            try:
                sessions.append(cls.from_log_path(csv_file))
            except Exception:
                continue  # skip malformed files

        return sessions


# ---------------------------------------------------------------------------
# SessionTimeline
# ---------------------------------------------------------------------------

class SessionTimeline:
    """Step-by-step replay and event search for a single session."""

    def __init__(self, session: SessionData) -> None:
        self.session = session

    def get_step(self, n: int) -> dict[str, Any]:
        """Return action, reasoning, observations, and parameters at step *n*.

        Looks up by the ``step`` column value. Raises ``KeyError`` if not found.
        """
        df = self.session.df
        mask = df["step"] == n
        if not mask.any():
            raise KeyError(f"Step {n} not found in session")
        row = df.loc[mask].iloc[0]
        result: dict[str, Any] = {
            "step": int(row["step"]),
            "action": row.get("action", ""),
            "reasoning": row.get("reasoning", ""),
            "observations": row.get("observations", ""),
        }
        for param in self.session.parameters:
            result[param] = row[param]
        return result

    def get_range(self, start: int, end: int) -> pd.DataFrame:
        """Slice of CSV data where ``start <= step <= end``."""
        df = self.session.df
        return df[(df["step"] >= start) & (df["step"] <= end)].copy()

    def parameter_at_step(self, param: str, step: int) -> float:
        """Value of *param* at the given *step*."""
        info = self.get_step(step)
        if param not in info:
            raise KeyError(f"Parameter '{param}' not found at step {step}")
        return float(info[param])

    def find_events(self, param: str, condition: str) -> list[int]:
        """Find steps where *param* matches *condition*.

        *condition* is a simple comparison like ``"< 100"`` or ``">= 50"``.
        Supported operators: ``<``, ``<=``, ``>``, ``>=``, ``==``, ``!=``.
        """
        df = self.session.df
        if param not in df.columns:
            raise KeyError(f"Parameter '{param}' not in CSV columns")

        cond_match = re.match(r"^\s*([<>!=]+)\s*(-?\d+(?:\.\d+)?)\s*$", condition)
        if not cond_match:
            raise ValueError(
                f"Invalid condition '{condition}'. "
                f"Expected format: '<op> <number>' (e.g., '< 100', '>= 50')"
            )
        op_str, val_str = cond_match.group(1), cond_match.group(2)
        threshold = float(val_str)

        ops = {
            "<": lambda s: s < threshold,
            "<=": lambda s: s <= threshold,
            ">": lambda s: s > threshold,
            ">=": lambda s: s >= threshold,
            "==": lambda s: s == threshold,
            "!=": lambda s: s != threshold,
        }
        if op_str not in ops:
            raise ValueError(f"Unsupported operator '{op_str}'")

        mask = ops[op_str](df[param])
        return df.loc[mask, "step"].tolist()

    def get_step_enriched(self, n: int) -> dict[str, Any]:
        """Like :meth:`get_step` but merges ``.history.json`` data if available.

        If a matching history record exists for step *n*, the returned dict
        includes an ``actions`` list (multi-action data from history) instead of
        the single CSV ``action`` string.  Additional history fields such as
        ``parameters`` are also merged.
        """
        base = self.get_step(n)

        # Build step→history lookup on first call
        if not hasattr(self, "_history_by_step"):
            self._history_by_step: dict[int, dict[str, Any]] = {}
            for entry in self.session.history:
                step_val = entry.get("step")
                if step_val is not None:
                    self._history_by_step[int(step_val)] = entry

        hist = self._history_by_step.get(n)
        if hist is not None:
            # Prefer multi-action list from history
            actions = hist.get("action")
            if isinstance(actions, list):
                base["actions"] = actions
            elif actions is not None:
                base["actions"] = [actions]
            # Merge extra history fields (parameters snapshot, etc.)
            for key in ("parameters",):
                if key in hist:
                    base[f"history_{key}"] = hist[key]
        return base

    def format_step(self, n: int) -> str:
        """Human-readable summary for a single step."""
        info = self.get_step(n)
        lines = [
            f"--- Step {info['step']} ---",
            f"Action:       {info['action']}",
            f"Reasoning:    {info['reasoning']}",
            f"Observations: {info['observations']}",
        ]
        params = {k: v for k, v in info.items()
                  if k not in ("step", "action", "reasoning", "observations")}
        if params:
            parts = [f"{k}={v}" for k, v in params.items()]
            lines.append(f"Parameters:   {', '.join(parts)}")
        return "\n".join(lines)

    def format_timeline(self, start: int = 0, end: int | None = None) -> str:
        """Multi-step formatted output."""
        df = self.session.df
        steps = sorted(df["step"].unique())
        if end is not None:
            steps = [s for s in steps if start <= s <= end]
        else:
            steps = [s for s in steps if s >= start]

        blocks = [self.format_step(s) for s in steps]
        return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# ActionAnalyzer
# ---------------------------------------------------------------------------

class ActionAnalyzer:
    """Analyze action patterns and action-outcome correlations.

    Works from the CSV ``action`` column (always present in session logs).
    Falls back gracefully if no actions exist.
    """

    def __init__(self, session: SessionData) -> None:
        self.session = session

    def action_frequency(self) -> dict[str, int]:
        """Count occurrences of each action in the CSV."""
        df = self.session.df
        if "action" not in df.columns:
            return {}
        counts = df["action"].value_counts()
        return {str(k): int(v) for k, v in counts.items()}

    def action_transitions(self) -> dict[str, dict[str, int]]:
        """Build action -> next_action transition matrix from CSV.

        Returns ``{action: {next_action: count}}``.
        """
        df = self.session.df
        if "action" not in df.columns or len(df) < 2:
            return {}

        actions = df["action"].astype(str).tolist()
        matrix: dict[str, dict[str, int]] = {}
        for cur, nxt in zip(actions[:-1], actions[1:]):
            if cur not in matrix:
                matrix[cur] = {}
            matrix[cur][nxt] = matrix[cur].get(nxt, 0) + 1
        return matrix

    def action_parameter_impact(self, param: str) -> dict[str, dict[str, float]]:
        """For each action, compute mean param delta at the next step.

        Returns ``{action: {mean_delta, count, median_delta}}``.
        Raises ``KeyError`` if *param* is not a CSV column.
        """
        df = self.session.df
        if param not in df.columns:
            raise KeyError(f"Parameter '{param}' not in CSV columns")
        if "action" not in df.columns or len(df) < 2:
            return {}

        deltas: dict[str, list[float]] = {}
        vals = df[param].tolist()
        actions = df["action"].astype(str).tolist()

        for i in range(len(actions) - 1):
            act = actions[i]
            delta = float(vals[i + 1]) - float(vals[i])
            if act not in deltas:
                deltas[act] = []
            deltas[act].append(delta)

        result: dict[str, dict[str, float]] = {}
        for act, ds in deltas.items():
            result[act] = {
                "mean_delta": round(statistics.mean(ds), 4),
                "count": len(ds),
                "median_delta": round(statistics.median(ds), 4),
            }
        return result

    def action_streaks(self) -> list[dict[str, Any]]:
        """Find consecutive sequences of the same action.

        Returns ``[{action, start_step, end_step, length}]`` sorted by length
        descending.
        """
        df = self.session.df
        if "action" not in df.columns or len(df) == 0:
            return []

        actions = df["action"].astype(str).tolist()
        steps = df["step"].tolist()

        streaks: list[dict[str, Any]] = []
        cur_action = actions[0]
        start_step = steps[0]
        length = 1

        for i in range(1, len(actions)):
            if actions[i] == cur_action:
                length += 1
            else:
                if length >= 2:
                    streaks.append({
                        "action": cur_action,
                        "start_step": int(start_step),
                        "end_step": int(steps[i - 1]),
                        "length": length,
                    })
                cur_action = actions[i]
                start_step = steps[i]
                length = 1

        # Final streak
        if length >= 2:
            streaks.append({
                "action": cur_action,
                "start_step": int(start_step),
                "end_step": int(steps[-1]),
                "length": length,
            })

        streaks.sort(key=lambda s: s["length"], reverse=True)
        return streaks

    def format_report(self) -> str:
        """Human-readable action analysis report (Markdown)."""
        lines: list[str] = ["# Action Analysis Report", ""]

        # Frequencies
        freq = self.action_frequency()
        if freq:
            lines.append("## Action Frequency")
            lines.append("")
            total = sum(freq.values())
            for act, cnt in sorted(freq.items(), key=lambda x: -x[1]):
                pct = cnt / total * 100 if total else 0
                lines.append(f"- **{act}**: {cnt} ({pct:.1f}%)")
            lines.append("")

        # Transitions
        trans = self.action_transitions()
        if trans:
            lines.append("## Action Transitions")
            lines.append("")
            for src, dests in sorted(trans.items()):
                dest_strs = [f"{d} ({c})" for d, c in sorted(dests.items(), key=lambda x: -x[1])]
                lines.append(f"- **{src}** -> {', '.join(dest_strs)}")
            lines.append("")

        # Streaks
        streaks = self.action_streaks()
        if streaks:
            lines.append("## Top Action Streaks")
            lines.append("")
            for s in streaks[:10]:
                lines.append(
                    f"- **{s['action']}** x{s['length']} "
                    f"(steps {s['start_step']}-{s['end_step']})"
                )
            lines.append("")

        # Parameter impact (for each numeric param)
        params = self.session.parameters
        if params and freq:
            lines.append("## Action-Parameter Impact")
            lines.append("")
            for param in params:
                impact = self.action_parameter_impact(param)
                if impact:
                    lines.append(f"### {param}")
                    lines.append("")
                    for act, stats in sorted(impact.items()):
                        lines.append(
                            f"- **{act}**: mean_delta={stats['mean_delta']}, "
                            f"median_delta={stats['median_delta']}, "
                            f"count={stats['count']}"
                        )
                    lines.append("")

        if not freq:
            lines.append("No actions found in session data.")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# SessionComparator
# ---------------------------------------------------------------------------

class SessionComparator:
    """Compare two or more sessions side-by-side."""

    def __init__(self, sessions: list[SessionData]) -> None:
        if len(sessions) < 2:
            raise ValueError("SessionComparator requires at least 2 sessions")
        self.sessions = sessions

    def compare_summary(self) -> pd.DataFrame:
        """Table with one row per session: timestamp, steps, cost, and param stats."""
        rows: list[dict[str, Any]] = []
        for s in self.sessions:
            row: dict[str, Any] = {
                "timestamp": s.timestamp,
                "game_id": s.game_id,
                "steps": s.total_steps,
                "cost_usd": s.cost_usd,
                "duration_s": s.duration_seconds,
            }
            for param in s.parameters:
                col = s.df[param]
                row[f"{param}_mean"] = round(col.mean(), 2)
                row[f"{param}_min"] = round(col.min(), 2)
                row[f"{param}_max"] = round(col.max(), 2)
            rows.append(row)
        return pd.DataFrame(rows)

    def compare_parameters(self, param: str) -> dict[str, dict[str, float]]:
        """Per-session statistics for a specific parameter.

        Returns ``{timestamp: {mean, min, max, std, first, last}}``.
        """
        result: dict[str, dict[str, float]] = {}
        for s in self.sessions:
            if param not in s.df.columns:
                continue
            col = s.df[param]
            result[s.timestamp] = {
                "mean": round(float(col.mean()), 2),
                "min": round(float(col.min()), 2),
                "max": round(float(col.max()), 2),
                "std": round(float(col.std()), 2),
                "first": round(float(col.iloc[0]), 2),
                "last": round(float(col.iloc[-1]), 2),
            }
        return result

    def compare_actions(self) -> pd.DataFrame:
        """Action frequency comparison across sessions.

        Returns a DataFrame with columns: action, then per-session count and pct
        columns named ``{timestamp}_count`` and ``{timestamp}_pct``.
        """
        all_freq: dict[str, dict[str, int]] = {}
        totals: dict[str, int] = {}
        for s in self.sessions:
            analyzer = ActionAnalyzer(s)
            freq = analyzer.action_frequency()
            all_freq[s.timestamp] = freq
            totals[s.timestamp] = sum(freq.values())

        # Union of all action names
        all_actions: set[str] = set()
        for freq in all_freq.values():
            all_actions.update(freq.keys())

        rows: list[dict[str, Any]] = []
        for action in sorted(all_actions):
            row: dict[str, Any] = {"action": action}
            for s in self.sessions:
                ts = s.timestamp
                cnt = all_freq[ts].get(action, 0)
                total = totals[ts]
                pct = round(cnt / total * 100, 1) if total else 0.0
                row[f"{ts}_count"] = cnt
                row[f"{ts}_pct"] = pct
            rows.append(row)

        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def compare_action_transitions(self) -> dict[str, dict[str, dict[str, int]]]:
        """Per-session transition matrices.

        Returns ``{timestamp: {action: {next_action: count}}}``.
        """
        result: dict[str, dict[str, dict[str, int]]] = {}
        for s in self.sessions:
            analyzer = ActionAnalyzer(s)
            result[s.timestamp] = analyzer.action_transitions()
        return result

    def diff_strategies(self) -> list[dict[str, Any]]:
        """Strategy differences between sessions.

        Returns a list of dicts with timestamp + strategy info for each session.
        """
        diffs: list[dict[str, Any]] = []
        for s in self.sessions:
            strategy = s.session_info.get("strategy", {})
            diffs.append({
                "timestamp": s.timestamp,
                "game_id": s.game_id,
                "strategy": strategy,
            })
        return diffs

    def to_markdown(self) -> str:
        """Formatted comparison report in Markdown."""
        lines: list[str] = ["# Session Comparison Report", ""]

        # Summary table
        summary = self.compare_summary()
        lines.append("## Summary")
        lines.append("")
        lines.append(_df_to_markdown(summary, index=False))
        lines.append("")

        # Parameter details — use the union of all parameters
        all_params: list[str] = []
        seen: set[str] = set()
        for s in self.sessions:
            for p in s.parameters:
                if p not in seen:
                    all_params.append(p)
                    seen.add(p)

        if all_params:
            lines.append("## Parameter Comparison")
            lines.append("")
            for param in all_params:
                stats = self.compare_parameters(param)
                if not stats:
                    continue
                lines.append(f"### {param}")
                lines.append("")
                stat_df = pd.DataFrame(stats).T
                stat_df.index.name = "session"
                lines.append(_df_to_markdown(stat_df))
                lines.append("")

        # Action comparison
        action_df = self.compare_actions()
        if not action_df.empty:
            lines.append("## Action Comparison")
            lines.append("")
            lines.append(_df_to_markdown(action_df, index=False))
            lines.append("")

        # Strategy diffs
        diffs = self.diff_strategies()
        lines.append("## Strategy Differences")
        lines.append("")
        for d in diffs:
            lines.append(f"- **{d['timestamp']}** ({d['game_id']}): "
                         f"{json.dumps(d['strategy'], default=str)}")
        lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_list(args: argparse.Namespace) -> None:
    """List all discovered sessions."""
    sessions = SessionData.discover_sessions(args.log_dir, game_id=args.game)
    if not sessions:
        print(f"No sessions found in {args.log_dir}")
        return
    print(f"{'Timestamp':<20} {'Game ID':<20} {'Steps':>6} {'Cost ($)':>10} {'CSV'}")
    print("-" * 80)
    for s in sessions:
        print(
            f"{s.timestamp:<20} {s.game_id:<20} {s.total_steps:>6} "
            f"{s.cost_usd:>10.4f} {s.csv_path.name}"
        )


def _cmd_show(args: argparse.Namespace) -> None:
    """Show single session summary."""
    s = SessionData.from_log_path(args.csv_path)
    print(f"Session: {s.timestamp}  Game: {s.game_id}")
    print(f"CSV:     {s.csv_path}")
    print(f"Steps:   {s.total_steps}")
    print(f"Duration: {s.duration_seconds:.1f}s")
    print(f"Cost:    ${s.cost_usd:.4f}")
    print(f"Parameters: {', '.join(s.parameters)}")
    if s.session_info:
        print(f"\nSession info keys: {', '.join(s.session_info.keys())}")
    if s.history:
        print(f"History records: {len(s.history)}")


def _cmd_timeline(args: argparse.Namespace) -> None:
    """Replay timeline step by step."""
    s = SessionData.from_log_path(args.csv_path)
    tl = SessionTimeline(s)
    print(tl.format_timeline(start=args.start, end=args.end))


def _cmd_compare(args: argparse.Namespace) -> None:
    """Compare multiple sessions."""
    sessions = [SessionData.from_log_path(p) for p in args.csv_paths]
    comp = SessionComparator(sessions)
    print(comp.to_markdown())


def _cmd_events(args: argparse.Namespace) -> None:
    """Find events matching a condition."""
    s = SessionData.from_log_path(args.csv_path)
    tl = SessionTimeline(s)
    steps = tl.find_events(args.param, args.condition)
    if not steps:
        print(f"No events found where {args.param} {args.condition}")
        return
    print(f"Found {len(steps)} step(s) where {args.param} {args.condition}:")
    for step in steps:
        print(f"  Step {step}: {args.param} = {tl.parameter_at_step(args.param, step)}")


def _cmd_replay(args: argparse.Namespace) -> None:
    """Action analysis / enriched replay for a session."""
    s = SessionData.from_log_path(args.csv_path)

    if args.step is not None:
        # Show enriched step detail
        tl = SessionTimeline(s)
        info = tl.get_step_enriched(args.step)
        print(f"--- Step {info['step']} (enriched) ---")
        if "actions" in info:
            print(f"Actions:      {info['actions']}")
        else:
            print(f"Action:       {info['action']}")
        print(f"Reasoning:    {info['reasoning']}")
        print(f"Observations: {info['observations']}")
        params = {k: v for k, v in info.items()
                  if k not in ("step", "action", "actions", "reasoning",
                               "observations", "history_parameters")}
        if params:
            parts = [f"{k}={v}" for k, v in params.items()]
            print(f"Parameters:   {', '.join(parts)}")
        if "history_parameters" in info:
            print(f"History snap: {info['history_parameters']}")
        return

    analyzer = ActionAnalyzer(s)

    if args.actions:
        # Show action frequency table only
        freq = analyzer.action_frequency()
        if not freq:
            print("No actions found in session data.")
            return
        total = sum(freq.values())
        print(f"{'Action':<30} {'Count':>6} {'Pct':>7}")
        print("-" * 45)
        for act, cnt in sorted(freq.items(), key=lambda x: -x[1]):
            pct = cnt / total * 100 if total else 0
            print(f"{act:<30} {cnt:>6} {pct:>6.1f}%")
        return

    # Full action analysis report
    print(analyzer.format_report())


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="session_replay",
        description="Session Replay Viewer — view, compare, and analyze past agent sessions.",
    )
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="List all sessions")
    p_list.add_argument("--game", default=None, help="Filter by game ID")
    p_list.add_argument("--log-dir", default="logs", help="Log directory (default: logs)")
    p_list.set_defaults(func=_cmd_list)

    # show
    p_show = sub.add_parser("show", help="Show single session summary")
    p_show.add_argument("csv_path", help="Path to session CSV")
    p_show.set_defaults(func=_cmd_show)

    # timeline
    p_tl = sub.add_parser("timeline", help="Replay session timeline")
    p_tl.add_argument("csv_path", help="Path to session CSV")
    p_tl.add_argument("--start", type=int, default=0, help="Start step (default: 0)")
    p_tl.add_argument("--end", type=int, default=None, help="End step (default: last)")
    p_tl.set_defaults(func=_cmd_timeline)

    # compare
    p_cmp = sub.add_parser("compare", help="Compare multiple sessions")
    p_cmp.add_argument("csv_paths", nargs="+", help="Paths to session CSVs (2+)")
    p_cmp.set_defaults(func=_cmd_compare)

    # events
    p_ev = sub.add_parser("events", help="Find events in a session")
    p_ev.add_argument("csv_path", help="Path to session CSV")
    p_ev.add_argument("--param", required=True, help="Parameter name")
    p_ev.add_argument("--condition", required=True, help='Condition (e.g., "< 100")')
    p_ev.set_defaults(func=_cmd_events)

    # replay
    p_replay = sub.add_parser("replay", help="Action analysis / enriched replay")
    p_replay.add_argument("csv_path", help="Path to session CSV")
    p_replay.add_argument("--step", type=int, default=None,
                          help="Show enriched detail for a specific step")
    p_replay.add_argument("--actions", action="store_true",
                          help="Show action frequency table only")
    p_replay.set_defaults(func=_cmd_replay)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
