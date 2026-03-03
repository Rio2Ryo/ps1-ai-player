#!/usr/bin/env python3
"""Action recommender — suggest optimal actions based on historical session data.

Learns action→parameter impacts from past sessions and recommends the top
actions given the current parameter state.  Uses cross-session aggregated
action effectiveness and per-session ActionAnalyzer impact data.

Usage:
    python action_recommender.py recommend --log-dir logs/ --session <csv_path>
    python action_recommender.py recommend --log-dir logs/ --session <csv_path> --top 5
    python action_recommender.py recommend --log-dir logs/ --session <csv_path> --format json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from log_config import get_logger
from session_replay import ActionAnalyzer, SessionData

logger = get_logger(__name__)


@dataclass
class ActionScore:
    """Score for a single recommended action."""

    action: str
    score: float
    param_impacts: dict[str, float] = field(default_factory=dict)
    reason: str = ""


class ActionRecommender:
    """Recommend actions based on historical action→parameter impact data.

    The recommender builds a model of how each action affects each parameter
    by aggregating data from all provided training sessions.  It then scores
    actions for a target session by weighting impacts toward parameters that
    are currently declining or low.
    """

    def __init__(
        self,
        training_sessions: list[SessionData],
        *,
        top_n: int = 3,
    ) -> None:
        if not training_sessions:
            raise ValueError("ActionRecommender requires at least 1 training session")
        self.training_sessions = training_sessions
        self.top_n = top_n
        self._impact_model: dict[str, dict[str, dict[str, float]]] = {}
        self._build_model()

    def _build_model(self) -> None:
        """Build the action→parameter impact model from training sessions."""
        # Collect all (action, param) → list[delta]
        raw: dict[str, dict[str, list[float]]] = {}

        for s in self.training_sessions:
            df = s.df
            if "action" not in df.columns or len(df) < 2:
                continue
            actions = df["action"].astype(str).tolist()
            for param in s.parameters:
                vals = df[param].tolist()
                for i in range(len(actions) - 1):
                    act = actions[i]
                    delta = float(vals[i + 1]) - float(vals[i])
                    raw.setdefault(act, {}).setdefault(param, []).append(delta)

        # Aggregate to mean/count
        for act, params in raw.items():
            self._impact_model[act] = {}
            for param, deltas in params.items():
                self._impact_model[act][param] = {
                    "mean_delta": round(statistics.mean(deltas), 4),
                    "count": len(deltas),
                }

    @property
    def known_actions(self) -> list[str]:
        """All actions seen in training data."""
        return sorted(self._impact_model.keys())

    @property
    def impact_model(self) -> dict[str, dict[str, dict[str, float]]]:
        """The learned action→parameter impact model."""
        return self._impact_model

    def _compute_param_weights(self, session: SessionData) -> dict[str, float]:
        """Compute per-parameter urgency weights based on the session's current state.

        Parameters that are declining or at low values relative to their range
        get higher weights.  Stable/rising parameters get lower weights.
        """
        df = session.df
        weights: dict[str, float] = {}

        for param in session.parameters:
            if param not in df.columns or len(df) < 2:
                weights[param] = 1.0
                continue

            col = df[param].dropna()
            if len(col) < 2:
                weights[param] = 1.0
                continue

            current = float(col.iloc[-1])
            mean_val = float(col.mean())
            param_range = float(col.max() - col.min())

            # Trend from recent values
            tail = col.tail(min(10, len(col)))
            if len(tail) >= 2:
                slope = float(tail.iloc[-1] - tail.iloc[0]) / len(tail)
            else:
                slope = 0.0

            weight = 1.0

            # Boost weight for declining parameters
            if slope < 0:
                weight += 1.0

            # Boost weight for parameters below their mean
            if param_range > 0 and current < mean_val:
                weight += 0.5

            weights[param] = round(weight, 2)

        return weights

    def recommend(self, target_session: SessionData) -> list[ActionScore]:
        """Recommend top actions for the given session's current state.

        Actions are scored by their weighted impact across all parameters,
        where weights reflect parameter urgency (declining params weighted higher).
        """
        if not self._impact_model:
            return []

        weights = self._compute_param_weights(target_session)
        scores: list[ActionScore] = []

        for action, param_impacts in self._impact_model.items():
            total_score = 0.0
            impact_summary: dict[str, float] = {}

            for param, w in weights.items():
                if param in param_impacts:
                    mean_delta = param_impacts[param]["mean_delta"]
                    # Positive delta is good for declining params (higher weight)
                    total_score += mean_delta * w
                    impact_summary[param] = mean_delta

            # Build reason text
            positive = [p for p, d in impact_summary.items() if d > 0]
            negative = [p for p, d in impact_summary.items() if d < 0]
            parts = []
            if positive:
                parts.append(f"improves {', '.join(positive)}")
            if negative:
                parts.append(f"reduces {', '.join(negative)}")
            reason = "; ".join(parts) if parts else "neutral impact"

            scores.append(ActionScore(
                action=action,
                score=round(total_score, 4),
                param_impacts=impact_summary,
                reason=reason,
            ))

        # Sort by score descending
        scores.sort(key=lambda s: s.score, reverse=True)
        return scores[: self.top_n]

    def to_dict(self, target_session: SessionData) -> dict[str, Any]:
        """JSON-serialisable recommendation result."""
        recs = self.recommend(target_session)
        weights = self._compute_param_weights(target_session)
        return {
            "session": target_session.timestamp,
            "param_weights": weights,
            "recommendations": [
                {
                    "rank": i + 1,
                    "action": r.action,
                    "score": r.score,
                    "param_impacts": r.param_impacts,
                    "reason": r.reason,
                }
                for i, r in enumerate(recs)
            ],
            "known_actions": self.known_actions,
            "training_sessions": len(self.training_sessions),
        }

    def to_markdown(self, target_session: SessionData) -> str:
        """Markdown formatted recommendation report."""
        data = self.to_dict(target_session)
        lines: list[str] = []

        lines.append("# Action Recommendations")
        lines.append("")
        lines.append(f"**Session:** {data['session']}")
        lines.append(f"**Training sessions:** {data['training_sessions']}")
        lines.append("")

        # Parameter weights
        lines.append("## Parameter Urgency Weights")
        lines.append("")
        lines.append("| Parameter | Weight |")
        lines.append("| --- | --- |")
        for param, w in data["param_weights"].items():
            lines.append(f"| {param} | {w} |")
        lines.append("")

        # Recommendations
        lines.append("## Top Recommendations")
        lines.append("")
        for rec in data["recommendations"]:
            lines.append(f"### #{rec['rank']}: {rec['action']} (score: {rec['score']})")
            lines.append("")
            lines.append(f"**Reason:** {rec['reason']}")
            lines.append("")
            if rec["param_impacts"]:
                lines.append("| Parameter | Expected Delta |")
                lines.append("| --- | --- |")
                for p, d in rec["param_impacts"].items():
                    lines.append(f"| {p} | {d:+.4f} |")
                lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="action_recommender",
        description="Recommend optimal actions based on historical session data.",
    )
    sub = parser.add_subparsers(dest="command")

    p_rec = sub.add_parser("recommend", help="Recommend actions for a session")
    p_rec.add_argument("session", help="Target session CSV path")
    p_rec.add_argument(
        "--log-dir", default="logs",
        help="Training session log directory (default: logs/)",
    )
    p_rec.add_argument("--game", default=None, help="Filter training sessions by game ID")
    p_rec.add_argument("--top", type=int, default=3, help="Number of recommendations (default: 3)")
    p_rec.add_argument(
        "--format", dest="fmt", choices=["markdown", "json"],
        default="markdown", help="Output format (default: markdown)",
    )

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    target = SessionData.from_log_path(Path(args.session))
    training = SessionData.discover_sessions(args.log_dir, game_id=args.game)

    if not training:
        print(f"No training sessions found in {args.log_dir}")
        return

    recommender = ActionRecommender(training, top_n=args.top)

    if args.fmt == "json":
        print(json.dumps(recommender.to_dict(target), indent=2))
    else:
        print(recommender.to_markdown(target))


if __name__ == "__main__":
    main()
