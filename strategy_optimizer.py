#!/usr/bin/env python3
"""Strategy optimizer — auto-tune strategy JSON thresholds and priorities
based on cross-session analysis and anomaly detection results.

Takes an existing strategy JSON (``config/strategies/*.json``) together with
session data, and produces an optimised version with adjusted threshold
values and priorities derived from actual parameter distributions and
strategy effectiveness metrics.

Optimisation heuristics:
  1. **Threshold value tuning** — shift ``lt`` / ``gt`` threshold values
     toward observed percentiles so they fire at more meaningful points.
  2. **Priority rebalancing** — boost priorities for thresholds linked to
     the best-performing strategy, lower priorities for under-performing ones.
  3. **New threshold suggestions** — propose thresholds for parameters that
     show strong cross-session trends but have no existing rule.
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from log_config import get_logger
from session_replay import SessionData

logger = get_logger(__name__)


class StrategyOptimizer:
    """Optimize strategy thresholds using empirical session data."""

    def __init__(
        self,
        strategy_config: dict[str, Any],
        sessions: list[SessionData],
    ) -> None:
        if not sessions:
            raise ValueError("StrategyOptimizer requires at least 1 session")
        if "thresholds" not in strategy_config:
            raise ValueError("strategy_config must contain 'thresholds' key")
        self.original = copy.deepcopy(strategy_config)
        self.sessions = sorted(sessions, key=lambda s: s.timestamp)

    # ------------------------------------------------------------------
    # Internal: gather stats
    # ------------------------------------------------------------------

    def _param_stats(self) -> dict[str, dict[str, float]]:
        """Compute per-parameter distribution stats across all sessions."""
        from cross_session_analyzer import CrossSessionAnalyzer

        analyzer = CrossSessionAnalyzer(self.sessions)
        merged = analyzer.merged_df()

        all_params: set[str] = set()
        for s in self.sessions:
            all_params.update(s.parameters)

        stats: dict[str, dict[str, float]] = {}
        for param in sorted(all_params):
            if param not in merged.columns:
                continue
            col = merged[param].dropna()
            if col.empty:
                continue
            stats[param] = {
                "mean": float(col.mean()),
                "std": float(col.std()) if len(col) > 1 else 0.0,
                "min": float(col.min()),
                "max": float(col.max()),
                "p10": float(col.quantile(0.10)),
                "p25": float(col.quantile(0.25)),
                "p50": float(col.quantile(0.50)),
                "p75": float(col.quantile(0.75)),
                "p90": float(col.quantile(0.90)),
            }
        return stats

    def _strategy_scores(self) -> dict[str, float]:
        """Score each strategy by average step count (higher = better)."""
        from cross_session_analyzer import CrossSessionAnalyzer

        analyzer = CrossSessionAnalyzer(self.sessions)
        strat_df = analyzer.strategy_effectiveness()
        scores: dict[str, float] = {}
        if strat_df.empty:
            return scores
        for _, row in strat_df.iterrows():
            scores[row["strategy"]] = float(row["avg_steps"])
        return scores

    # ------------------------------------------------------------------
    # 1. Tune threshold values
    # ------------------------------------------------------------------

    def tune_thresholds(self) -> list[dict[str, Any]]:
        """Adjust threshold values based on observed parameter distributions.

        For ``lt`` thresholds, shifts the value toward the 25th percentile
        so it fires when the parameter is genuinely low.
        For ``gt`` thresholds, shifts toward the 75th percentile.

        Returns the modified threshold list.
        """
        stats = self._param_stats()
        thresholds = copy.deepcopy(self.original["thresholds"])

        for t in thresholds:
            param = t["parameter"]
            if param not in stats:
                continue
            s = stats[param]
            op = t.get("operator", "")
            old_val = t["value"]

            if op == "lt":
                # Use 25th percentile, but don't move more than 50% away
                target = s["p25"]
                new_val = round((old_val + target) / 2, 2)
                t["value"] = new_val
                t["_tuning"] = f"lt: {old_val} -> {new_val} (p25={s['p25']:.1f})"
            elif op == "gt":
                target = s["p75"]
                new_val = round((old_val + target) / 2, 2)
                t["value"] = new_val
                t["_tuning"] = f"gt: {old_val} -> {new_val} (p75={s['p75']:.1f})"

        return thresholds

    # ------------------------------------------------------------------
    # 2. Rebalance priorities
    # ------------------------------------------------------------------

    def rebalance_priorities(
        self, thresholds: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Adjust priorities: boost thresholds whose ``target_strategy``
        performed best across sessions, lower under-performing ones.

        Returns the modified threshold list.
        """
        if thresholds is None:
            thresholds = copy.deepcopy(self.original["thresholds"])
        else:
            thresholds = copy.deepcopy(thresholds)

        scores = self._strategy_scores()
        if not scores:
            return thresholds

        max_score = max(scores.values()) if scores else 1.0
        min_score = min(scores.values()) if scores else 0.0
        score_range = max_score - min_score if max_score != min_score else 1.0

        for t in thresholds:
            target = t.get("target_strategy", "")
            if target not in scores:
                continue
            # Normalise to 0-1 range
            norm = (scores[target] - min_score) / score_range
            # Adjust priority: +-2 based on performance
            adjustment = round((norm - 0.5) * 4)
            old_p = t.get("priority", 5)
            new_p = max(1, min(10, old_p + adjustment))
            if new_p != old_p:
                t["_priority_adjustment"] = f"{old_p} -> {new_p} (strategy score: {scores[target]:.1f})"
            t["priority"] = new_p

        return thresholds

    # ------------------------------------------------------------------
    # 3. Suggest new thresholds
    # ------------------------------------------------------------------

    def suggest_new_thresholds(self) -> list[dict[str, Any]]:
        """Propose thresholds for parameters that have no existing rule
        but show significant variation across sessions.

        Returns a list of new threshold suggestions (not yet in the config).
        """
        stats = self._param_stats()
        existing_params = {t["parameter"] for t in self.original["thresholds"]}

        suggestions: list[dict[str, Any]] = []
        for param, s in stats.items():
            if param in existing_params:
                continue
            # Only suggest if std is significant relative to range
            param_range = s["max"] - s["min"]
            if param_range == 0:
                continue
            cv = s["std"] / abs(s["mean"]) if s["mean"] != 0 else 0
            if cv < 0.1:
                continue

            # Suggest a "low" threshold at p25 and "high" at p75
            suggestions.append({
                "parameter": param,
                "operator": "lt",
                "value": round(s["p25"], 2),
                "target_strategy": "defensive",
                "priority": 6,
                "_suggestion": f"New: {param} < {s['p25']:.1f} (p25, cv={cv:.2f})",
            })
            suggestions.append({
                "parameter": param,
                "operator": "gt",
                "value": round(s["p75"], 2),
                "target_strategy": "aggressive",
                "priority": 4,
                "_suggestion": f"New: {param} > {s['p75']:.1f} (p75, cv={cv:.2f})",
            })

        return suggestions

    # ------------------------------------------------------------------
    # Full optimisation pipeline
    # ------------------------------------------------------------------

    def optimize(self) -> dict[str, Any]:
        """Run full optimisation: tune values, rebalance priorities,
        suggest new thresholds. Returns a new strategy config dict.

        The output is a valid strategy JSON with an extra
        ``"_optimization_notes"`` key containing change descriptions.
        """
        tuned = self.tune_thresholds()
        rebalanced = self.rebalance_priorities(tuned)
        suggestions = self.suggest_new_thresholds()

        # Collect notes from _tuning / _priority_adjustment / _suggestion
        notes: list[str] = []
        clean_thresholds: list[dict[str, Any]] = []
        for t in rebalanced:
            entry = {k: v for k, v in t.items() if not k.startswith("_")}
            if "_tuning" in t:
                notes.append(t["_tuning"])
            if "_priority_adjustment" in t:
                notes.append(t["_priority_adjustment"])
            clean_thresholds.append(entry)

        new_thresholds: list[dict[str, Any]] = []
        for s in suggestions:
            entry = {k: v for k, v in s.items() if not k.startswith("_")}
            new_thresholds.append(entry)
            if "_suggestion" in s:
                notes.append(s["_suggestion"])

        result = copy.deepcopy(self.original)
        result["thresholds"] = clean_thresholds + new_thresholds
        result["_optimization_notes"] = notes
        result["_sessions_analyzed"] = len(self.sessions)

        return result

    def diff(self) -> list[str]:
        """Human-readable diff between original and optimised config."""
        optimized = self.optimize()
        lines: list[str] = []
        orig_thresholds = {
            (t["parameter"], t["operator"]): t
            for t in self.original["thresholds"]
        }
        opt_thresholds = {
            (t["parameter"], t["operator"]): t
            for t in optimized["thresholds"]
        }

        # Changed thresholds
        for key in orig_thresholds:
            if key in opt_thresholds:
                o = orig_thresholds[key]
                n = opt_thresholds[key]
                changes = []
                if o["value"] != n["value"]:
                    changes.append(f"value: {o['value']} -> {n['value']}")
                if o.get("priority") != n.get("priority"):
                    changes.append(f"priority: {o.get('priority')} -> {n.get('priority')}")
                if changes:
                    lines.append(
                        f"  [{key[0]} {key[1]}] {', '.join(changes)}"
                    )

        # New thresholds
        for key in opt_thresholds:
            if key not in orig_thresholds:
                t = opt_thresholds[key]
                lines.append(
                    f"  + [{t['parameter']} {t['operator']} {t['value']}] "
                    f"-> {t['target_strategy']} (priority {t.get('priority', '?')})"
                )

        return lines

    def to_markdown(self) -> str:
        """Optimisation report in Markdown."""
        optimized = self.optimize()
        diff_lines = self.diff()

        lines: list[str] = [
            "# Strategy Optimisation Report",
            "",
            f"Genre: {self.original.get('genre', 'unknown')}",
            f"Sessions analyzed: {len(self.sessions)}",
            "",
        ]

        if diff_lines:
            lines.append("## Changes")
            lines.append("")
            for d in diff_lines:
                lines.append(f"- {d}")
            lines.append("")
        else:
            lines.append("No changes recommended.")
            lines.append("")

        notes = optimized.get("_optimization_notes", [])
        if notes:
            lines.append("## Notes")
            lines.append("")
            for n in notes:
                lines.append(f"- {n}")
            lines.append("")

        # Optimised JSON preview
        clean = {k: v for k, v in optimized.items() if not k.startswith("_")}
        lines.append("## Optimised Config")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(clean, indent=2))
        lines.append("```")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="strategy_optimizer",
        description="Auto-tune strategy JSON thresholds from session data.",
    )
    sub = parser.add_subparsers(dest="command")

    p_opt = sub.add_parser("optimize", help="Optimize a strategy config")
    p_opt.add_argument(
        "strategy_file", help="Path to strategy JSON (e.g. config/strategies/rpg.json)",
    )
    p_opt.add_argument(
        "--log-dir", default="logs",
        help="Session log directory (default: logs/)",
    )
    p_opt.add_argument("--game", default=None, help="Filter sessions by game ID")
    p_opt.add_argument(
        "--output", default=None,
        help="Write optimised JSON to file (default: stdout)",
    )
    p_opt.add_argument(
        "--format", choices=["json", "markdown"], default="json",
        help="Output format (default: json)",
    )

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Load strategy config
    strat_path = Path(args.strategy_file)
    if not strat_path.exists():
        print(f"Strategy file not found: {strat_path}")
        sys.exit(1)
    strategy_config = json.loads(strat_path.read_text())

    # Load sessions
    sessions = SessionData.discover_sessions(args.log_dir, game_id=args.game)
    if not sessions:
        print(f"No sessions found in {args.log_dir}")
        return

    optimizer = StrategyOptimizer(strategy_config, sessions)

    if args.format == "markdown":
        output = optimizer.to_markdown()
    else:
        optimized = optimizer.optimize()
        clean = {k: v for k, v in optimized.items() if not k.startswith("_")}
        output = json.dumps(clean, indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output)
        logger.info("Written to %s", out_path)
    else:
        print(output)


if __name__ == "__main__":
    main()
