#!/usr/bin/env python3
"""Batch report generator — unified report combining cross_session_analyzer,
anomaly_detector, strategy_optimizer, and parameter_predictor results.

Produces a comprehensive report covering all sessions in a single command.
Supports Markdown, JSON, and HTML output formats.

Usage:
    python batch_report.py generate --log-dir logs/ [--format markdown|json|html]
    python batch_report.py generate --log-dir logs/ --output reports/batch_report.md
    python batch_report.py generate --log-dir logs/ --game DEMO --format html
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from log_config import get_logger
from session_replay import SessionData

logger = get_logger(__name__)


class BatchReportGenerator:
    """Generate a unified report integrating multiple analysis modules."""

    def __init__(
        self,
        sessions: list[SessionData],
        *,
        strategy_config: dict[str, Any] | None = None,
        spike_threshold: float = 2.5,
        prediction_window: int = 10,
    ) -> None:
        if not sessions:
            raise ValueError("BatchReportGenerator requires at least 1 session")
        self.sessions = sorted(sessions, key=lambda s: s.timestamp)
        self.strategy_config = strategy_config
        self.spike_threshold = spike_threshold
        self.prediction_window = prediction_window

    # ------------------------------------------------------------------
    # Section generators
    # ------------------------------------------------------------------

    def cross_session_section(self) -> dict[str, Any]:
        """Run CrossSessionAnalyzer and return results."""
        from cross_session_analyzer import CrossSessionAnalyzer

        analyzer = CrossSessionAnalyzer(self.sessions)
        return analyzer.to_dict()

    def anomaly_section(self) -> dict[str, Any]:
        """Run AnomalyDetector and return results."""
        from anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(
            self.sessions, spike_threshold=self.spike_threshold,
        )
        return detector.summary()

    def strategy_section(self) -> dict[str, Any] | None:
        """Run StrategyOptimizer if a strategy config is provided."""
        if not self.strategy_config:
            return None

        from strategy_optimizer import StrategyOptimizer

        try:
            optimizer = StrategyOptimizer(self.strategy_config, self.sessions)
            optimized = optimizer.optimize()
            return {
                "diff": optimizer.diff(),
                "notes": optimized.get("_optimization_notes", []),
                "optimized_config": {
                    k: v for k, v in optimized.items() if not k.startswith("_")
                },
            }
        except (ValueError, KeyError) as exc:
            logger.warning("Strategy optimization skipped: %s", exc)
            return None

    def prediction_section(self) -> list[dict[str, Any]]:
        """Run ParameterPredictor for each session and return results."""
        from parameter_predictor import ParameterPredictor

        results: list[dict[str, Any]] = []
        for s in self.sessions:
            predictor = ParameterPredictor(s, window=self.prediction_window)
            results.append(predictor.to_dict())
        return results

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------

    def generate(self) -> dict[str, Any]:
        """Generate the complete report as a dict."""
        report: dict[str, Any] = {
            "generated_at": datetime.now().isoformat(),
            "session_count": len(self.sessions),
            "sessions": [s.timestamp for s in self.sessions],
        }

        report["cross_session"] = self.cross_session_section()
        report["anomalies"] = self.anomaly_section()
        report["predictions"] = self.prediction_section()

        strategy = self.strategy_section()
        if strategy is not None:
            report["strategy_optimization"] = strategy

        return report

    # ------------------------------------------------------------------
    # Output formats
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable report dict."""
        return self.generate()

    def to_json(self) -> str:
        """JSON string output."""
        return json.dumps(self.generate(), indent=2, default=str)

    def to_markdown(self) -> str:
        """Markdown formatted report."""
        report = self.generate()
        lines: list[str] = []

        lines.append("# Batch Analysis Report")
        lines.append("")
        lines.append(f"**Generated:** {report['generated_at']}")
        lines.append(f"**Sessions analyzed:** {report['session_count']}")
        lines.append("")

        # --- Cross-session section ---
        cross = report["cross_session"]
        lines.append("## Cross-Session Analysis")
        lines.append("")

        # Session progression
        prog = cross.get("session_progression", [])
        if prog:
            lines.append("### Session Progression")
            lines.append("")
            if prog:
                keys = list(prog[0].keys())
                lines.append("| " + " | ".join(keys) + " |")
                lines.append("| " + " | ".join("---" for _ in keys) + " |")
                for row in prog:
                    vals = [str(row.get(k, "")) for k in keys]
                    lines.append("| " + " | ".join(vals) + " |")
                lines.append("")

        # Recommendations
        recs = cross.get("recommendations", [])
        if recs:
            lines.append("### Recommendations")
            lines.append("")
            for r in recs:
                lines.append(f"- {r}")
            lines.append("")

        # --- Anomaly section ---
        anomalies = report["anomalies"]
        lines.append("## Anomaly Detection")
        lines.append("")
        lines.append(f"**Total anomalies:** {anomalies.get('total', 0)}")
        lines.append("")

        by_kind = anomalies.get("by_kind", {})
        if by_kind:
            lines.append("| Type | Count |")
            lines.append("| --- | --- |")
            for kind, count in by_kind.items():
                lines.append(f"| {kind} | {count} |")
            lines.append("")

        anomaly_list = anomalies.get("anomalies", [])
        if anomaly_list:
            severity_icon = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}
            for a in anomaly_list[:20]:
                icon = severity_icon.get(a.get("severity", ""), "")
                lines.append(f"- {icon} {a.get('description', '')}")
            if len(anomaly_list) > 20:
                lines.append(f"- ... and {len(anomaly_list) - 20} more")
            lines.append("")

        # --- Prediction section ---
        predictions = report.get("predictions", [])
        if predictions:
            lines.append("## Parameter Predictions")
            lines.append("")
            for pred in predictions:
                session_name = pred.get("session", "unknown")
                lines.append(f"### Session: {session_name}")
                lines.append("")

                params = pred.get("parameters", {})
                if params:
                    lines.append("| Parameter | Slope | Intercept | R\u00b2 | Trend |")
                    lines.append("| --- | --- | --- | --- | --- |")
                    for param, data in params.items():
                        reg = data.get("regression", {})
                        slope = reg.get("slope", 0)
                        intercept = reg.get("intercept", 0)
                        r_sq = reg.get("r_squared", 0)
                        trend = "rising" if slope > 0 else ("falling" if slope < 0 else "flat")
                        lines.append(
                            f"| {param} | {slope:.4f} | {intercept:.4f} | {r_sq:.4f} | {trend} |"
                        )
                    lines.append("")

                thresholds = pred.get("thresholds", [])
                if thresholds:
                    lines.append("| Parameter | Threshold | Direction | Est. Step | Current |")
                    lines.append("| --- | --- | --- | --- | --- |")
                    for t in thresholds:
                        est = str(t.get("estimated_step")) if t.get("estimated_step") is not None else "N/A"
                        lines.append(
                            f"| {t['parameter']} | {t['threshold']:.2f} | {t['direction']} "
                            f"| {est} | {t['current_value']:.2f} |"
                        )
                    lines.append("")

        # --- Strategy optimization section ---
        strategy = report.get("strategy_optimization")
        if strategy:
            lines.append("## Strategy Optimization")
            lines.append("")
            diff_lines = strategy.get("diff", [])
            if diff_lines:
                lines.append("### Proposed Changes")
                lines.append("")
                for d in diff_lines:
                    lines.append(f"- {d}")
                lines.append("")

            notes = strategy.get("notes", [])
            if notes:
                lines.append("### Notes")
                lines.append("")
                for n in notes:
                    lines.append(f"- {n}")
                lines.append("")

        return "\n".join(lines)

    def to_html(self) -> str:
        """Standalone HTML report."""
        report = self.generate()

        css = """\
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 24px auto; max-width: 1100px; padding: 0 16px; background: #f5f5f5; color: #333; }
table { border-collapse: collapse; width: 100%; background: #fff; margin: 16px 0; }
th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
th { background: #e3f2fd; }
tr:nth-child(even) { background: #fafafa; }
h1, h2, h3 { color: #1565c0; }
.card { background: #fff; border-radius: 6px; padding: 20px; margin: 16px 0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12); }
.badge-high { color: #e53935; font-weight: bold; }
.badge-medium { color: #fb8c00; font-weight: bold; }
.badge-low { color: #fdd835; font-weight: bold; }
"""

        parts: list[str] = []
        parts.append(f"<!DOCTYPE html><html><head><meta charset='utf-8'>")
        parts.append(f"<title>Batch Report</title><style>{css}</style></head><body>")
        parts.append(f"<h1>Batch Analysis Report</h1>")
        parts.append(f"<p><strong>Generated:</strong> {report['generated_at']}</p>")
        parts.append(f"<p><strong>Sessions:</strong> {report['session_count']}</p>")

        # Cross-session
        cross = report["cross_session"]
        parts.append('<div class="card"><h2>Cross-Session Analysis</h2>')

        prog = cross.get("session_progression", [])
        if prog:
            parts.append("<h3>Session Progression</h3><table>")
            keys = list(prog[0].keys())
            parts.append("<tr>" + "".join(f"<th>{k}</th>" for k in keys) + "</tr>")
            for row in prog:
                parts.append("<tr>" + "".join(f"<td>{row.get(k, '')}</td>" for k in keys) + "</tr>")
            parts.append("</table>")

        recs = cross.get("recommendations", [])
        if recs:
            parts.append("<h3>Recommendations</h3><ul>")
            for r in recs:
                parts.append(f"<li>{r}</li>")
            parts.append("</ul>")
        parts.append("</div>")

        # Anomalies
        anomalies = report["anomalies"]
        parts.append('<div class="card"><h2>Anomaly Detection</h2>')
        parts.append(f"<p><strong>Total:</strong> {anomalies.get('total', 0)}</p>")
        anomaly_list = anomalies.get("anomalies", [])
        if anomaly_list:
            for a in anomaly_list[:20]:
                sev = a.get("severity", "low")
                badge_cls = f"badge-{sev}"
                parts.append(
                    f'<p><span class="{badge_cls}">[{sev.upper()}]</span> '
                    f'{a.get("description", "")}</p>'
                )
            if len(anomaly_list) > 20:
                parts.append(f"<p>... and {len(anomaly_list) - 20} more</p>")
        else:
            parts.append("<p>No anomalies detected.</p>")
        parts.append("</div>")

        # Predictions
        predictions = report.get("predictions", [])
        if predictions:
            parts.append('<div class="card"><h2>Parameter Predictions</h2>')
            for pred in predictions:
                session_name = pred.get("session", "unknown")
                parts.append(f"<h3>Session: {session_name}</h3>")
                params = pred.get("parameters", {})
                if params:
                    parts.append("<table><tr><th>Parameter</th><th>Slope</th>")
                    parts.append("<th>R\u00b2</th><th>Trend</th></tr>")
                    for param, data in params.items():
                        reg = data.get("regression", {})
                        slope = reg.get("slope", 0)
                        r_sq = reg.get("r_squared", 0)
                        trend = "rising" if slope > 0 else ("falling" if slope < 0 else "flat")
                        color = "green" if trend == "rising" else ("red" if trend == "falling" else "gray")
                        parts.append(
                            f"<tr><td>{param}</td><td>{slope:.4f}</td>"
                            f"<td>{r_sq:.4f}</td>"
                            f'<td style="color:{color}">{trend}</td></tr>'
                        )
                    parts.append("</table>")
            parts.append("</div>")

        # Strategy optimization
        strategy = report.get("strategy_optimization")
        if strategy:
            parts.append('<div class="card"><h2>Strategy Optimization</h2>')
            diff_lines = strategy.get("diff", [])
            if diff_lines:
                parts.append("<h3>Proposed Changes</h3><ul>")
                for d in diff_lines:
                    parts.append(f"<li><code>{d}</code></li>")
                parts.append("</ul>")
            notes = strategy.get("notes", [])
            if notes:
                parts.append("<h3>Notes</h3><ul>")
                for n in notes:
                    parts.append(f"<li>{n}</li>")
                parts.append("</ul>")
            parts.append("</div>")

        parts.append("</body></html>")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _find_strategy_config(log_dir: str | Path) -> dict[str, Any] | None:
    """Auto-discover the first strategy config in config/strategies/."""
    strat_dir = Path("config/strategies")
    if not strat_dir.is_dir():
        return None
    files = sorted(strat_dir.glob("*.json"))
    if not files:
        return None
    try:
        return json.loads(files[0].read_text())
    except Exception:
        return None


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="batch_report",
        description="Generate a comprehensive batch report across all sessions.",
    )
    sub = parser.add_subparsers(dest="command")

    p_gen = sub.add_parser("generate", help="Generate batch report")
    p_gen.add_argument(
        "--log-dir", default="logs",
        help="Session log directory (default: logs/)",
    )
    p_gen.add_argument("--game", default=None, help="Filter by game ID")
    p_gen.add_argument(
        "--format", dest="fmt", choices=["markdown", "json", "html"],
        default="markdown", help="Output format (default: markdown)",
    )
    p_gen.add_argument(
        "--output", default=None,
        help="Write report to file (default: stdout)",
    )
    p_gen.add_argument(
        "--strategy", default=None,
        help="Strategy JSON path for optimization (auto-detected if omitted)",
    )
    p_gen.add_argument(
        "--spike-threshold", type=float, default=2.5,
        help="Z-score threshold for anomaly spike detection (default: 2.5)",
    )

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    sessions = SessionData.discover_sessions(args.log_dir, game_id=args.game)
    if not sessions:
        print(f"No sessions found in {args.log_dir}")
        return

    # Strategy config
    strategy_config = None
    if args.strategy:
        strat_path = Path(args.strategy)
        if strat_path.exists():
            strategy_config = json.loads(strat_path.read_text())
        else:
            print(f"Strategy file not found: {strat_path}")
    else:
        strategy_config = _find_strategy_config(args.log_dir)

    generator = BatchReportGenerator(
        sessions,
        strategy_config=strategy_config,
        spike_threshold=args.spike_threshold,
    )

    if args.fmt == "json":
        output = generator.to_json()
    elif args.fmt == "html":
        output = generator.to_html()
    else:
        output = generator.to_markdown()

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output)
        logger.info("Report written to %s", out_path)
    else:
        print(output)


if __name__ == "__main__":
    main()
