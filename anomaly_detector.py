#!/usr/bin/env python3
"""Anomaly detector — detect unusual parameter spikes, action pattern deviations,
and cross-session performance regressions.

Anomaly types:
  - Parameter spikes   : sudden changes exceeding z-score threshold within a session
  - Action deviations  : actions whose frequency deviates significantly from the mean
  - Session regressions: parameters that worsen compared to prior sessions
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from log_config import get_logger
from session_replay import ActionAnalyzer, SessionData, _FIXED_COLUMNS

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes for anomaly results
# ---------------------------------------------------------------------------

@dataclass
class Anomaly:
    """A single detected anomaly."""

    kind: str  # "spike", "action_deviation", "regression"
    severity: str  # "low", "medium", "high"
    session: str  # session timestamp
    description: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "session": self.session,
            "description": self.description,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# AnomalyDetector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """Detect anomalies within and across sessions."""

    def __init__(
        self,
        sessions: list[SessionData],
        *,
        spike_threshold: float = 2.5,
        action_deviation_threshold: float = 2.0,
        regression_threshold: float = 0.1,
    ) -> None:
        if not sessions:
            raise ValueError("AnomalyDetector requires at least 1 session")
        self.sessions = sorted(sessions, key=lambda s: s.timestamp)
        self.spike_threshold = spike_threshold
        self.action_deviation_threshold = action_deviation_threshold
        self.regression_threshold = regression_threshold

    # ------------------------------------------------------------------
    # 1. Parameter spike detection
    # ------------------------------------------------------------------

    def detect_spikes(self) -> list[Anomaly]:
        """Detect parameter spikes using z-score on step-to-step deltas.

        A spike occurs when a delta exceeds *spike_threshold* standard
        deviations from the mean delta for that parameter.
        """
        anomalies: list[Anomaly] = []

        for s in self.sessions:
            for param in s.parameters:
                col = s.df[param]
                if len(col) < 3:
                    continue

                deltas = col.diff().dropna().tolist()
                if len(deltas) < 2:
                    continue

                mean_d = statistics.mean(deltas)
                std_d = statistics.stdev(deltas)
                if std_d == 0:
                    continue

                steps = s.df["step"].tolist()
                for i, delta in enumerate(deltas):
                    z = abs(delta - mean_d) / std_d
                    if z >= self.spike_threshold:
                        step_idx = i + 1  # delta[i] corresponds to step[i+1]
                        step_val = steps[step_idx] if step_idx < len(steps) else steps[-1]
                        severity = "high" if z >= 4.0 else "medium" if z >= 3.0 else "low"
                        anomalies.append(Anomaly(
                            kind="spike",
                            severity=severity,
                            session=s.timestamp,
                            description=(
                                f"Parameter '{param}' spike at step {step_val}: "
                                f"delta={delta:.2f} (z-score={z:.2f})"
                            ),
                            details={
                                "parameter": param,
                                "step": int(step_val),
                                "delta": round(delta, 4),
                                "z_score": round(z, 4),
                                "mean_delta": round(mean_d, 4),
                                "std_delta": round(std_d, 4),
                            },
                        ))

        return anomalies

    # ------------------------------------------------------------------
    # 2. Action pattern deviation detection
    # ------------------------------------------------------------------

    def detect_action_deviations(self) -> list[Anomaly]:
        """Detect sessions where action frequencies deviate significantly
        from the cross-session average.

        Computes the mean frequency proportion for each action across all
        sessions, then flags sessions where an action's proportion is more
        than *action_deviation_threshold* standard deviations from the mean.
        """
        if len(self.sessions) < 2:
            return []

        anomalies: list[Anomaly] = []

        # Compute per-session action proportions
        all_actions: set[str] = set()
        session_props: list[dict[str, float]] = []
        for s in self.sessions:
            analyzer = ActionAnalyzer(s)
            freq = analyzer.action_frequency()
            total = sum(freq.values())
            props = {act: cnt / total for act, cnt in freq.items()} if total else {}
            session_props.append(props)
            all_actions.update(props.keys())

        if not all_actions:
            return anomalies

        # Compute mean and std for each action across sessions
        for action in sorted(all_actions):
            proportions = [sp.get(action, 0.0) for sp in session_props]
            if len(proportions) < 2:
                continue
            mean_p = statistics.mean(proportions)
            std_p = statistics.stdev(proportions)
            if std_p == 0:
                continue

            for i, prop in enumerate(proportions):
                z = abs(prop - mean_p) / std_p
                if z >= self.action_deviation_threshold:
                    s = self.sessions[i]
                    direction = "over-used" if prop > mean_p else "under-used"
                    severity = "high" if z >= 3.0 else "medium"
                    anomalies.append(Anomaly(
                        kind="action_deviation",
                        severity=severity,
                        session=s.timestamp,
                        description=(
                            f"Action '{action}' {direction} in session {s.timestamp}: "
                            f"{prop:.1%} vs mean {mean_p:.1%} (z={z:.2f})"
                        ),
                        details={
                            "action": action,
                            "proportion": round(prop, 4),
                            "mean_proportion": round(mean_p, 4),
                            "std_proportion": round(std_p, 4),
                            "z_score": round(z, 4),
                            "direction": direction,
                        },
                    ))

        return anomalies

    # ------------------------------------------------------------------
    # 3. Cross-session regression detection
    # ------------------------------------------------------------------

    def detect_regressions(self) -> list[Anomaly]:
        """Detect parameters that worsen in the latest session compared to
        the average of prior sessions.

        A regression is flagged when the latest session's final parameter
        value is worse by more than *regression_threshold* fraction of the
        prior sessions' average final value.  "Worse" means lower for most
        parameters, but the detection is direction-agnostic — it flags any
        significant deviation from the prior mean.
        """
        if len(self.sessions) < 2:
            return []

        anomalies: list[Anomaly] = []
        latest = self.sessions[-1]
        prior = self.sessions[:-1]

        # Collect union of parameters
        all_params: set[str] = set()
        for s in self.sessions:
            all_params.update(s.parameters)

        for param in sorted(all_params):
            # Gather final values from prior sessions
            prior_finals: list[float] = []
            for s in prior:
                if param in s.df.columns and len(s.df) > 0:
                    prior_finals.append(float(s.df[param].iloc[-1]))

            if not prior_finals:
                continue

            # Latest session final value
            if param not in latest.df.columns or len(latest.df) == 0:
                continue
            latest_final = float(latest.df[param].iloc[-1])

            prior_mean = statistics.mean(prior_finals)
            if prior_mean == 0:
                continue

            # Relative change
            change = (latest_final - prior_mean) / abs(prior_mean)

            if abs(change) >= self.regression_threshold:
                direction = "improved" if change > 0 else "regressed"
                severity = (
                    "high" if abs(change) >= 0.3
                    else "medium" if abs(change) >= 0.2
                    else "low"
                )
                anomalies.append(Anomaly(
                    kind="regression",
                    severity=severity,
                    session=latest.timestamp,
                    description=(
                        f"Parameter '{param}' {direction} in latest session: "
                        f"{latest_final:.2f} vs prior avg {prior_mean:.2f} "
                        f"({change:+.1%})"
                    ),
                    details={
                        "parameter": param,
                        "latest_value": round(latest_final, 4),
                        "prior_mean": round(prior_mean, 4),
                        "change_pct": round(change * 100, 2),
                        "direction": direction,
                    },
                ))

        return anomalies

    # ------------------------------------------------------------------
    # Aggregate interface
    # ------------------------------------------------------------------

    def detect_all(self) -> list[Anomaly]:
        """Run all detection methods and return combined anomaly list."""
        all_anomalies: list[Anomaly] = []
        all_anomalies.extend(self.detect_spikes())
        all_anomalies.extend(self.detect_action_deviations())
        all_anomalies.extend(self.detect_regressions())
        return all_anomalies

    def summary(self) -> dict[str, Any]:
        """Summary statistics of all detected anomalies."""
        anomalies = self.detect_all()
        by_kind: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for a in anomalies:
            by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
            by_severity[a.severity] = by_severity.get(a.severity, 0) + 1

        return {
            "total": len(anomalies),
            "by_kind": by_kind,
            "by_severity": by_severity,
            "anomalies": [a.to_dict() for a in anomalies],
        }

    def to_markdown(self) -> str:
        """Anomaly report in Markdown format."""
        anomalies = self.detect_all()
        lines: list[str] = [
            "# Anomaly Detection Report",
            "",
            f"Sessions analyzed: {len(self.sessions)}",
            f"Total anomalies: {len(anomalies)}",
            "",
        ]

        if not anomalies:
            lines.append("No anomalies detected.")
            return "\n".join(lines)

        # Group by kind
        spikes = [a for a in anomalies if a.kind == "spike"]
        deviations = [a for a in anomalies if a.kind == "action_deviation"]
        regressions = [a for a in anomalies if a.kind == "regression"]

        if spikes:
            lines.append("## Parameter Spikes")
            lines.append("")
            for a in spikes:
                icon = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}[a.severity]
                lines.append(f"- {icon} {a.description}")
            lines.append("")

        if deviations:
            lines.append("## Action Pattern Deviations")
            lines.append("")
            for a in deviations:
                icon = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}[a.severity]
                lines.append(f"- {icon} {a.description}")
            lines.append("")

        if regressions:
            lines.append("## Cross-Session Regressions")
            lines.append("")
            for a in regressions:
                icon = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}[a.severity]
                lines.append(f"- {icon} {a.description}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="anomaly_detector",
        description="Detect anomalies across agent sessions.",
    )
    sub = parser.add_subparsers(dest="command")

    p_detect = sub.add_parser("detect", help="Run anomaly detection")
    p_detect.add_argument(
        "--log-dir", default="logs",
        help="Session log directory (default: logs/)",
    )
    p_detect.add_argument("--game", default=None, help="Filter by game ID")
    p_detect.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="Output format (default: markdown)",
    )
    p_detect.add_argument(
        "--output", default=None,
        help="Write report to file (default: stdout)",
    )
    p_detect.add_argument(
        "--spike-threshold", type=float, default=2.5,
        help="Z-score threshold for spike detection (default: 2.5)",
    )

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    sessions = SessionData.discover_sessions(args.log_dir, game_id=args.game)
    if not sessions:
        print(f"No sessions found in {args.log_dir}")
        return

    detector = AnomalyDetector(
        sessions,
        spike_threshold=args.spike_threshold,
    )

    if args.format == "json":
        output = json.dumps(detector.summary(), indent=2, default=str)
    else:
        output = detector.to_markdown()

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output)
        logger.info("Report written to %s", out_path)
    else:
        print(output)


if __name__ == "__main__":
    main()
