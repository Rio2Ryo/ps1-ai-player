#!/usr/bin/env python3
"""Session scoring & ranking for PS1 AI Player.

Scores sessions 0–100 based on configurable criteria: step count,
parameter improvement, action diversity, and cost efficiency.

Usage:
    python session_scorer.py score <csv_path> [--weights steps=30,param=30,diversity=20,cost=20]
    python session_scorer.py rank --log-dir logs/ [--format markdown|json]
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

# Default weight distribution (must sum to 100)
DEFAULT_WEIGHTS: dict[str, float] = {
    "steps": 30.0,
    "param_improvement": 30.0,
    "action_diversity": 20.0,
    "cost_efficiency": 20.0,
}


# ---------------------------------------------------------------------------
# ScoreBreakdown — per-criterion scores
# ---------------------------------------------------------------------------

@dataclass
class ScoreBreakdown:
    """Individual criterion scores (each 0–100) and final weighted score."""

    steps_score: float = 0.0
    param_improvement_score: float = 0.0
    action_diversity_score: float = 0.0
    cost_efficiency_score: float = 0.0
    total: float = 0.0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps_score": round(self.steps_score, 2),
            "param_improvement_score": round(self.param_improvement_score, 2),
            "action_diversity_score": round(self.action_diversity_score, 2),
            "cost_efficiency_score": round(self.cost_efficiency_score, 2),
            "total": round(self.total, 2),
            "weights": self.weights,
        }


# ---------------------------------------------------------------------------
# SessionScorer
# ---------------------------------------------------------------------------

class SessionScorer:
    """Score and rank sessions based on configurable criteria."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        step_target: int = 100,
    ) -> None:
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.step_target = step_target

    def score(self, session) -> ScoreBreakdown:
        """Score a single SessionData object (0–100)."""
        breakdown = ScoreBreakdown(weights=dict(self.weights))

        # 1. Steps score — ratio of total steps to target, capped at 100
        breakdown.steps_score = min(100.0, session.total_steps / self.step_target * 100)

        # 2. Parameter improvement — average improvement ratio across params
        breakdown.param_improvement_score = self._param_improvement(session)

        # 3. Action diversity — ratio of unique actions to total, scaled
        breakdown.action_diversity_score = self._action_diversity(session)

        # 4. Cost efficiency — steps per dollar (more steps per dollar = better)
        breakdown.cost_efficiency_score = self._cost_efficiency(session)

        # Weighted total
        breakdown.total = (
            breakdown.steps_score * self.weights.get("steps", 0) / 100
            + breakdown.param_improvement_score * self.weights.get("param_improvement", 0) / 100
            + breakdown.action_diversity_score * self.weights.get("action_diversity", 0) / 100
            + breakdown.cost_efficiency_score * self.weights.get("cost_efficiency", 0) / 100
        )
        breakdown.total = round(min(100.0, max(0.0, breakdown.total)), 2)

        return breakdown

    def rank_sessions(self, sessions: list) -> list[dict[str, Any]]:
        """Score and rank a list of SessionData objects.

        Returns a list of dicts sorted by total score descending:
        ``[{csv_filename, timestamp, game_id, steps, score, breakdown}, ...]``
        """
        ranked = []
        for s in sessions:
            bd = self.score(s)
            ranked.append({
                "csv_filename": s.csv_path.name,
                "timestamp": s.timestamp,
                "game_id": s.game_id,
                "steps": s.total_steps,
                "score": bd.total,
                "breakdown": bd.to_dict(),
            })
        ranked.sort(key=lambda r: r["score"], reverse=True)
        # Assign rank
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
        return ranked

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "step_target": self.step_target,
        }

    def to_markdown(self, ranking: list[dict[str, Any]]) -> str:
        """Generate a Markdown ranking report."""
        lines: list[str] = ["# Session Ranking", ""]
        lines.append(f"**Weights**: {self.weights}")
        lines.append(f"**Step target**: {self.step_target}")
        lines.append("")

        if ranking:
            lines.append("| Rank | Timestamp | Game | Steps | Score |")
            lines.append("|------|-----------|------|-------|-------|")
            for r in ranking:
                lines.append(
                    f"| {r['rank']} | {r['timestamp']} | {r['game_id']} "
                    f"| {r['steps']} | {r['score']:.1f} |"
                )
        else:
            lines.append("No sessions to rank.")
        lines.append("")
        return "\n".join(lines)

    # -- Private scoring helpers ---------------------------------------------

    @staticmethod
    def _param_improvement(session) -> float:
        """Score based on parameter improvement (last vs first).

        For each numeric param, compute (last - first) / abs(first) as
        improvement ratio.  Positive improvement is good.  Average across
        all params, then scale to 0–100 (50 = no change, 100 = doubled).
        """
        import pandas as pd

        params = [
            c for c in session.df.columns
            if c not in {"timestamp", "step", "action", "reasoning", "observations"}
            and pd.api.types.is_numeric_dtype(session.df[c])
        ]
        if not params or len(session.df) < 2:
            return 50.0  # neutral

        improvements = []
        for p in params:
            first_val = float(session.df[p].iloc[0])
            last_val = float(session.df[p].iloc[-1])
            if abs(first_val) < 1e-9:
                # Avoid division by zero; use absolute change
                improvements.append(min(1.0, max(-1.0, last_val - first_val)))
            else:
                ratio = (last_val - first_val) / abs(first_val)
                improvements.append(min(1.0, max(-1.0, ratio)))

        avg_improvement = sum(improvements) / len(improvements)
        # Map [-1, 1] to [0, 100]: -1 → 0, 0 → 50, 1 → 100
        return max(0.0, min(100.0, 50.0 + avg_improvement * 50.0))

    @staticmethod
    def _action_diversity(session) -> float:
        """Score based on action diversity.

        Uses the ratio of unique actions to a reasonable baseline.
        1 unique action = 0, 2 = 40, 3 = 60, 5+ = 100.
        """
        if "action" not in session.df.columns or len(session.df) == 0:
            return 0.0
        unique_count = session.df["action"].nunique()
        # Scale: map 1→0, 2→40, 3→60, 4→80, 5+→100
        if unique_count <= 1:
            return 0.0
        return min(100.0, (unique_count - 1) * 25.0)

    @staticmethod
    def _cost_efficiency(session) -> float:
        """Score based on steps per dollar spent.

        If no cost data, assume perfect efficiency (100).
        Scale: 0 steps/$ = 0, 1000+ steps/$ = 100.
        """
        cost = session.cost_usd
        if cost <= 0:
            return 100.0  # free session = max efficiency
        steps_per_dollar = session.total_steps / cost
        # Scale: 1000 steps/$ = 100
        return min(100.0, steps_per_dollar / 10.0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_weights(text: str) -> dict[str, float]:
    """Parse ``'steps=30,param=30,diversity=20,cost=20'`` into a dict."""
    mapping = {
        "steps": "steps",
        "param": "param_improvement",
        "param_improvement": "param_improvement",
        "diversity": "action_diversity",
        "action_diversity": "action_diversity",
        "cost": "cost_efficiency",
        "cost_efficiency": "cost_efficiency",
    }
    weights = dict(DEFAULT_WEIGHTS)
    for pair in text.split(","):
        key, _, val = pair.partition("=")
        key = key.strip().lower()
        mapped = mapping.get(key)
        if mapped and val.strip():
            weights[mapped] = float(val.strip())
    return weights


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Session scoring & ranking")
    sub = parser.add_subparsers(dest="command")

    sp_score = sub.add_parser("score", help="Score a single session")
    sp_score.add_argument("csv_path", help="Path to session CSV")
    sp_score.add_argument("--weights", default=None, help="Weights e.g. steps=30,param=30,diversity=20,cost=20")
    sp_score.add_argument("--step-target", type=int, default=100)

    sp_rank = sub.add_parser("rank", help="Rank all sessions")
    sp_rank.add_argument("--log-dir", default="logs")
    sp_rank.add_argument("--weights", default=None)
    sp_rank.add_argument("--step-target", type=int, default=100)
    sp_rank.add_argument("--format", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        raise SystemExit(2)

    weights = _parse_weights(args.weights) if args.weights else None
    scorer = SessionScorer(weights=weights, step_target=args.step_target)

    if args.command == "score":
        from session_replay import SessionData
        session = SessionData.from_log_path(args.csv_path)
        bd = scorer.score(session)
        print(json.dumps({
            "csv_filename": session.csv_path.name,
            "timestamp": session.timestamp,
            "score": bd.total,
            "breakdown": bd.to_dict(),
        }, indent=2))

    elif args.command == "rank":
        from session_replay import SessionData
        sessions = SessionData.discover_sessions(args.log_dir)
        ranking = scorer.rank_sessions(sessions)
        if args.format == "json":
            print(json.dumps(ranking, indent=2))
        else:
            print(scorer.to_markdown(ranking))


if __name__ == "__main__":
    main()
