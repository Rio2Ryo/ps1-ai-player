#!/usr/bin/env python3
"""Cross-session analyzer — aggregate data from multiple sessions to identify
strategy effectiveness, parameter trends, action-outcome correlations, and
produce actionable recommendations for improving agent performance.

Goes beyond pairwise comparison (SessionComparator) to provide:
  - Merged CSV analysis across all sessions for a given game
  - Per-strategy effectiveness scoring
  - Parameter trend comparison across sessions
  - Action effectiveness ranking
  - Markdown report output
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from log_config import get_logger
from session_replay import (
    ActionAnalyzer,
    SessionData,
    _FIXED_COLUMNS,
    _df_to_markdown,
)

logger = get_logger(__name__)


class CrossSessionAnalyzer:
    """Analyze multiple sessions to identify trends, strategy effectiveness,
    and action-outcome correlations across session boundaries."""

    def __init__(self, sessions: list[SessionData]) -> None:
        if not sessions:
            raise ValueError("CrossSessionAnalyzer requires at least 1 session")
        self.sessions = sorted(sessions, key=lambda s: s.timestamp)

    # ------------------------------------------------------------------
    # 1. merged_df
    # ------------------------------------------------------------------

    def merged_df(self) -> pd.DataFrame:
        """Concatenate all session DataFrames with an added ``session_id`` column."""
        frames: list[pd.DataFrame] = []
        for s in self.sessions:
            df = s.df.copy()
            df["session_id"] = s.timestamp
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    # ------------------------------------------------------------------
    # 2. parameter_evolution
    # ------------------------------------------------------------------

    def parameter_evolution(self) -> dict[str, list[dict[str, Any]]]:
        """Per-session stats for each numeric parameter, ordered chronologically.

        Returns ``{param: [{session, mean, min, max, first, last, std, trend}, ...]}``.
        """
        # Collect union of all numeric parameters
        all_params: list[str] = []
        seen: set[str] = set()
        for s in self.sessions:
            for p in s.parameters:
                if p not in seen:
                    all_params.append(p)
                    seen.add(p)

        result: dict[str, list[dict[str, Any]]] = {}
        for param in all_params:
            entries: list[dict[str, Any]] = []
            prev_mean: float | None = None
            for s in self.sessions:
                if param not in s.df.columns:
                    continue
                col = s.df[param]
                mean_val = float(col.mean())
                entry: dict[str, Any] = {
                    "session": s.timestamp,
                    "mean": round(mean_val, 2),
                    "min": round(float(col.min()), 2),
                    "max": round(float(col.max()), 2),
                    "first": round(float(col.iloc[0]), 2),
                    "last": round(float(col.iloc[-1]), 2),
                    "std": round(float(col.std()), 2) if len(col) > 1 else 0.0,
                }
                # Trend relative to previous session
                if prev_mean is not None:
                    diff = mean_val - prev_mean
                    if diff > 0.5:
                        entry["trend"] = "rising"
                    elif diff < -0.5:
                        entry["trend"] = "falling"
                    else:
                        entry["trend"] = "stable"
                else:
                    entry["trend"] = "baseline"
                prev_mean = mean_val
                entries.append(entry)
            result[param] = entries
        return result

    # ------------------------------------------------------------------
    # 3. strategy_effectiveness
    # ------------------------------------------------------------------

    def strategy_effectiveness(self) -> pd.DataFrame:
        """Group sessions by strategy and compute aggregated parameter stats.

        Returns a DataFrame with columns:
        ``strategy | sessions | avg_steps | <param>_mean | <param>_last_mean | ...``
        """
        # Collect union of all numeric parameters
        all_params: list[str] = []
        seen: set[str] = set()
        for s in self.sessions:
            for p in s.parameters:
                if p not in seen:
                    all_params.append(p)
                    seen.add(p)

        # Group sessions by strategy
        groups: dict[str, list[SessionData]] = {}
        for s in self.sessions:
            strategy = s.session_info.get("strategy", {}).get("current", "unknown")
            groups.setdefault(strategy, []).append(s)

        rows: list[dict[str, Any]] = []
        for strategy, sessions in sorted(groups.items()):
            row: dict[str, Any] = {
                "strategy": strategy,
                "sessions": len(sessions),
                "avg_steps": round(
                    statistics.mean(s.total_steps for s in sessions), 1
                ),
            }
            for param in all_params:
                means: list[float] = []
                lasts: list[float] = []
                for s in sessions:
                    if param in s.df.columns:
                        means.append(float(s.df[param].mean()))
                        lasts.append(float(s.df[param].iloc[-1]))
                if means:
                    row[f"{param}_mean"] = round(statistics.mean(means), 2)
                    row[f"{param}_last_mean"] = round(statistics.mean(lasts), 2)
            rows.append(row)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # 4. action_effectiveness
    # ------------------------------------------------------------------

    def action_effectiveness(self, target_param: str) -> pd.DataFrame:
        """Aggregate action→parameter-delta impacts across ALL sessions.

        Returns a DataFrame with columns:
        ``action | mean_delta | median_delta | count``

        Raises ``KeyError`` if *target_param* is not found in any session.
        """
        pooled: dict[str, list[float]] = {}
        found = False
        for s in self.sessions:
            if target_param not in s.df.columns:
                continue
            found = True
            if "action" not in s.df.columns or len(s.df) < 2:
                continue
            vals = s.df[target_param].tolist()
            actions = s.df["action"].astype(str).tolist()
            for i in range(len(actions) - 1):
                act = actions[i]
                delta = float(vals[i + 1]) - float(vals[i])
                pooled.setdefault(act, []).append(delta)

        if not found:
            raise KeyError(
                f"Parameter '{target_param}' not found in any session"
            )

        rows: list[dict[str, Any]] = []
        for act, deltas in sorted(pooled.items()):
            rows.append({
                "action": act,
                "mean_delta": round(statistics.mean(deltas), 4),
                "median_delta": round(statistics.median(deltas), 4),
                "count": len(deltas),
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["action", "mean_delta", "median_delta", "count"]
        )

    # ------------------------------------------------------------------
    # 5. session_progression
    # ------------------------------------------------------------------

    def session_progression(self) -> pd.DataFrame:
        """One row per session with key metrics, ordered by timestamp."""
        all_params: list[str] = []
        seen: set[str] = set()
        for s in self.sessions:
            for p in s.parameters:
                if p not in seen:
                    all_params.append(p)
                    seen.add(p)

        rows: list[dict[str, Any]] = []
        for s in self.sessions:
            row: dict[str, Any] = {
                "session": s.timestamp,
                "game_id": s.game_id,
                "total_steps": s.total_steps,
                "duration_s": round(s.duration_seconds, 1),
                "cost_usd": s.cost_usd,
            }
            for param in all_params:
                if param in s.df.columns:
                    row[f"{param}_last"] = round(float(s.df[param].iloc[-1]), 2)
            rows.append(row)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # 6. common_patterns
    # ------------------------------------------------------------------

    def common_patterns(self) -> dict[str, Any]:
        """Identify common patterns across all sessions.

        Returns:
        - ``most_frequent_actions``: pooled action frequency
        - ``most_common_transitions``: pooled transition counts
        - ``longest_streaks``: top streaks across all sessions
        """
        # Pool frequencies
        total_freq: dict[str, int] = {}
        # Pool transitions
        total_trans: dict[str, dict[str, int]] = {}
        # Collect all streaks
        all_streaks: list[dict[str, Any]] = []

        for s in self.sessions:
            analyzer = ActionAnalyzer(s)

            freq = analyzer.action_frequency()
            for act, cnt in freq.items():
                total_freq[act] = total_freq.get(act, 0) + cnt

            trans = analyzer.action_transitions()
            for src, dests in trans.items():
                if src not in total_trans:
                    total_trans[src] = {}
                for dst, cnt in dests.items():
                    total_trans[src][dst] = total_trans[src].get(dst, 0) + cnt

            streaks = analyzer.action_streaks()
            for streak in streaks:
                streak["session"] = s.timestamp
            all_streaks.extend(streaks)

        # Sort streaks by length descending, top 10
        all_streaks.sort(key=lambda x: x["length"], reverse=True)

        return {
            "most_frequent_actions": dict(
                sorted(total_freq.items(), key=lambda x: -x[1])
            ),
            "most_common_transitions": total_trans,
            "longest_streaks": all_streaks[:10],
        }

    # ------------------------------------------------------------------
    # 7. recommendations
    # ------------------------------------------------------------------

    def recommendations(self) -> list[str]:
        """Generate heuristic-based text recommendations."""
        recs: list[str] = []

        # Strategy comparison recommendations
        strat_df = self.strategy_effectiveness()
        if len(strat_df) >= 2:
            # Collect union of parameters
            all_params: list[str] = []
            seen: set[str] = set()
            for s in self.sessions:
                for p in s.parameters:
                    if p not in seen:
                        all_params.append(p)
                        seen.add(p)

            for param in all_params:
                col = f"{param}_last_mean"
                if col not in strat_df.columns:
                    continue
                best_idx = strat_df[col].idxmax()
                worst_idx = strat_df[col].idxmin()
                if best_idx == worst_idx:
                    continue
                best_strat = strat_df.iloc[best_idx]["strategy"]
                worst_strat = strat_df.iloc[worst_idx]["strategy"]
                best_val = strat_df.iloc[best_idx][col]
                worst_val = strat_df.iloc[worst_idx][col]
                if best_val != worst_val:
                    recs.append(
                        f"Strategy '{best_strat}' yields higher {param} on "
                        f"average than strategy '{worst_strat}' "
                        f"({best_val:.1f} vs {worst_val:.1f})"
                    )

        # Action effectiveness recommendations
        all_params_set: set[str] = set()
        for s in self.sessions:
            all_params_set.update(s.parameters)
        for param in sorted(all_params_set):
            try:
                act_df = self.action_effectiveness(param)
            except KeyError:
                continue
            if act_df.empty:
                continue
            best_idx = act_df["mean_delta"].idxmax()
            best_act = act_df.iloc[best_idx]["action"]
            best_delta = act_df.iloc[best_idx]["mean_delta"]
            if best_delta > 0:
                recs.append(
                    f"Action '{best_act}' has the strongest positive impact on "
                    f"{param} (mean +{best_delta:.4f})"
                )

        # Parameter trend recommendations
        evol = self.parameter_evolution()
        for param, entries in evol.items():
            if len(entries) < 2:
                continue
            last_two = entries[-2:]
            if last_two[-1]["trend"] == "falling":
                recs.append(
                    f"Parameter '{param}' has been declining across sessions "
                    f"(session {last_two[0]['session']}: mean {last_two[0]['mean']:.1f} "
                    f"-> session {last_two[1]['session']}: mean {last_two[1]['mean']:.1f})"
                )

        # Cross-strategy switch recommendation
        if len(strat_df) >= 2:
            # Find strategy with highest average steps (more survival)
            best_steps_idx = strat_df["avg_steps"].idxmax()
            worst_steps_idx = strat_df["avg_steps"].idxmin()
            if best_steps_idx != worst_steps_idx:
                best = strat_df.iloc[best_steps_idx]["strategy"]
                worst = strat_df.iloc[worst_steps_idx]["strategy"]
                recs.append(
                    f"Consider switching from strategy '{worst}' to '{best}' "
                    f"for better outcomes"
                )

        return recs

    # ------------------------------------------------------------------
    # 8. to_markdown
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Full cross-session analysis report in Markdown."""
        lines: list[str] = [
            "# Cross-Session Analysis Report",
            "",
            f"Sessions analyzed: {len(self.sessions)}",
            "",
        ]

        # Session progression
        prog = self.session_progression()
        lines.append("## Session Progression")
        lines.append("")
        lines.append(_df_to_markdown(prog, index=False))
        lines.append("")

        # Parameter evolution
        evol = self.parameter_evolution()
        if evol:
            lines.append("## Parameter Evolution")
            lines.append("")
            for param, entries in evol.items():
                lines.append(f"### {param}")
                lines.append("")
                evol_df = pd.DataFrame(entries)
                lines.append(_df_to_markdown(evol_df, index=False))
                lines.append("")

        # Strategy effectiveness
        strat_df = self.strategy_effectiveness()
        if not strat_df.empty:
            lines.append("## Strategy Effectiveness")
            lines.append("")
            lines.append(_df_to_markdown(strat_df, index=False))
            lines.append("")

        # Action effectiveness (for each parameter)
        all_params: set[str] = set()
        for s in self.sessions:
            all_params.update(s.parameters)
        if all_params:
            lines.append("## Action Effectiveness")
            lines.append("")
            for param in sorted(all_params):
                try:
                    act_df = self.action_effectiveness(param)
                except KeyError:
                    continue
                if act_df.empty:
                    continue
                lines.append(f"### {param}")
                lines.append("")
                lines.append(_df_to_markdown(act_df, index=False))
                lines.append("")

        # Common patterns
        patterns = self.common_patterns()
        lines.append("## Common Patterns")
        lines.append("")

        freq = patterns["most_frequent_actions"]
        if freq:
            lines.append("### Most Frequent Actions")
            lines.append("")
            total = sum(freq.values())
            for act, cnt in list(freq.items())[:15]:
                pct = cnt / total * 100 if total else 0
                lines.append(f"- **{act}**: {cnt} ({pct:.1f}%)")
            lines.append("")

        streaks = patterns["longest_streaks"]
        if streaks:
            lines.append("### Longest Streaks")
            lines.append("")
            for s in streaks[:10]:
                lines.append(
                    f"- **{s['action']}** x{s['length']} "
                    f"(session {s['session']}, steps {s['start_step']}-{s['end_step']})"
                )
            lines.append("")

        # Recommendations
        recs = self.recommendations()
        if recs:
            lines.append("## Recommendations")
            lines.append("")
            for r in recs:
                lines.append(f"- {r}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 9. to_dict
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable dict of all analysis results."""
        strat_df = self.strategy_effectiveness()
        prog_df = self.session_progression()

        # Action effectiveness for all params
        all_params: set[str] = set()
        for s in self.sessions:
            all_params.update(s.parameters)
        action_eff: dict[str, list[dict[str, Any]]] = {}
        for param in sorted(all_params):
            try:
                act_df = self.action_effectiveness(param)
            except KeyError:
                continue
            if not act_df.empty:
                action_eff[param] = act_df.to_dict(orient="records")

        return {
            "session_count": len(self.sessions),
            "sessions": [s.timestamp for s in self.sessions],
            "parameter_evolution": self.parameter_evolution(),
            "strategy_effectiveness": strat_df.to_dict(orient="records"),
            "action_effectiveness": action_eff,
            "session_progression": prog_df.to_dict(orient="records"),
            "common_patterns": self.common_patterns(),
            "recommendations": self.recommendations(),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="cross_session_analyzer",
        description="Cross-session analyzer — multi-session learning and trend analysis.",
    )
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser("analyze", help="Analyze sessions across multiple runs")
    p_analyze.add_argument(
        "--log-dir", default="logs", help="Session log directory (default: logs/)"
    )
    p_analyze.add_argument("--game", default=None, help="Filter by game ID")
    p_analyze.add_argument(
        "--output", default=None, help="Write report to file (default: stdout)"
    )
    p_analyze.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # analyze command
    sessions = SessionData.discover_sessions(args.log_dir, game_id=args.game)
    if not sessions:
        print(f"No sessions found in {args.log_dir}")
        return

    logger.info(
        "Loaded %d session(s) from %s", len(sessions), args.log_dir
    )
    analyzer = CrossSessionAnalyzer(sessions)

    if args.format == "json":
        output = json.dumps(analyzer.to_dict(), indent=2, default=str)
    else:
        output = analyzer.to_markdown()

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output)
        logger.info("Report written to %s", out_path)
    else:
        print(output)


if __name__ == "__main__":
    main()
