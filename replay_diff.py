#!/usr/bin/env python3
"""Step-level diff between two agent sessions.

Aligns two sessions by step number and identifies:
  - Divergence points (steps where different actions were chosen)
  - Parameter deltas at each step
  - Per-parameter trajectory comparison

Usage:
    python replay_diff.py diff <session_a.csv> <session_b.csv>
    python replay_diff.py diff <a.csv> <b.csv> --format json --output report.json
    python replay_diff.py diff <a.csv> <b.csv> --param hp
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from log_config import get_logger
from session_replay import SessionData, _FIXED_COLUMNS, _df_to_markdown

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParamDelta:
    """Parameter comparison at a single step."""

    value_a: float | None
    value_b: float | None
    diff: float | None       # value_b - value_a (None if either is None)
    pct_diff: float | None   # percentage difference

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepDiff:
    """Diff for a single step between two sessions."""

    step: int
    action_a: str | None       # None if session A doesn't have this step
    action_b: str | None       # None if session B doesn't have this step
    action_diverged: bool       # True if actions differ
    param_deltas: dict[str, ParamDelta]

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "action_a": self.action_a,
            "action_b": self.action_b,
            "action_diverged": self.action_diverged,
            "param_deltas": {k: v.to_dict() for k, v in self.param_deltas.items()},
        }


# ---------------------------------------------------------------------------
# ReplayDiff
# ---------------------------------------------------------------------------

class ReplayDiff:
    """Step-level diff between two sessions."""

    def __init__(self, session_a: SessionData, session_b: SessionData) -> None:
        self.session_a = session_a
        self.session_b = session_b
        self._step_diffs: list[StepDiff] | None = None

    # -- Core methods -------------------------------------------------------

    def step_diffs(self) -> list[StepDiff]:
        """Align both sessions by step number and produce a StepDiff per step.

        Steps present in only one session have ``None`` for the other.
        """
        if self._step_diffs is not None:
            return self._step_diffs

        df_a = self.session_a.df
        df_b = self.session_b.df

        # Index by step for fast lookup
        a_by_step: dict[int, pd.Series] = {}
        for _, row in df_a.iterrows():
            a_by_step[int(row["step"])] = row

        b_by_step: dict[int, pd.Series] = {}
        for _, row in df_b.iterrows():
            b_by_step[int(row["step"])] = row

        # Union of all steps
        all_steps = sorted(set(a_by_step.keys()) | set(b_by_step.keys()))

        # Union of parameter columns
        params_a = set(self.session_a.parameters)
        params_b = set(self.session_b.parameters)
        all_params = sorted(params_a | params_b)

        diffs: list[StepDiff] = []
        for step in all_steps:
            row_a = a_by_step.get(step)
            row_b = b_by_step.get(step)

            action_a = str(row_a["action"]) if row_a is not None and "action" in row_a.index else None
            action_b = str(row_b["action"]) if row_b is not None and "action" in row_b.index else None

            # Determine divergence: both must be present and different
            if action_a is not None and action_b is not None:
                action_diverged = action_a != action_b
            else:
                action_diverged = False

            param_deltas: dict[str, ParamDelta] = {}
            for param in all_params:
                val_a: float | None = None
                val_b: float | None = None
                if row_a is not None and param in row_a.index:
                    try:
                        val_a = float(row_a[param])
                    except (ValueError, TypeError):
                        pass
                if row_b is not None and param in row_b.index:
                    try:
                        val_b = float(row_b[param])
                    except (ValueError, TypeError):
                        pass

                diff: float | None = None
                pct_diff: float | None = None
                if val_a is not None and val_b is not None:
                    diff = val_b - val_a
                    if val_a != 0:
                        pct_diff = diff / abs(val_a) * 100
                    else:
                        pct_diff = 0.0 if diff == 0 else None

                param_deltas[param] = ParamDelta(
                    value_a=val_a,
                    value_b=val_b,
                    diff=diff,
                    pct_diff=pct_diff,
                )

            diffs.append(StepDiff(
                step=step,
                action_a=action_a,
                action_b=action_b,
                action_diverged=action_diverged,
                param_deltas=param_deltas,
            ))

        self._step_diffs = diffs
        return diffs

    def divergence_points(self) -> list[StepDiff]:
        """Return only steps where actions diverged."""
        return [sd for sd in self.step_diffs() if sd.action_diverged]

    def param_comparison(self, param: str) -> pd.DataFrame:
        """DataFrame comparing a single parameter across both sessions.

        Columns: ``step``, ``{param}_a``, ``{param}_b``, ``diff``, ``pct_diff``.
        Raises ``KeyError`` if *param* is not found in either session.
        """
        all_params = set(self.session_a.parameters) | set(self.session_b.parameters)
        if param not in all_params:
            raise KeyError(f"Parameter '{param}' not found in either session")

        rows: list[dict[str, Any]] = []
        for sd in self.step_diffs():
            pd_delta = sd.param_deltas.get(param)
            if pd_delta is None:
                continue
            rows.append({
                "step": sd.step,
                f"{param}_a": pd_delta.value_a,
                f"{param}_b": pd_delta.value_b,
                "diff": pd_delta.diff,
                "pct_diff": pd_delta.pct_diff,
            })

        return pd.DataFrame(rows)

    def summary(self) -> dict[str, Any]:
        """High-level summary of the diff."""
        diffs = self.step_diffs()
        steps_a = {sd.step for sd in diffs if sd.action_a is not None}
        steps_b = {sd.step for sd in diffs if sd.action_b is not None}
        common_steps = steps_a & steps_b

        # Divergence count among common steps
        diverged = [sd for sd in diffs if sd.step in common_steps and sd.action_diverged]
        divergence_count = len(diverged)
        divergence_rate = divergence_count / len(common_steps) if common_steps else 0.0

        # Per-param mean absolute diff across common steps
        all_params = sorted(
            set(self.session_a.parameters) | set(self.session_b.parameters)
        )
        param_diffs: dict[str, float] = {}
        for param in all_params:
            abs_diffs: list[float] = []
            for sd in diffs:
                if sd.step not in common_steps:
                    continue
                pd_delta = sd.param_deltas.get(param)
                if pd_delta is not None and pd_delta.diff is not None:
                    abs_diffs.append(abs(pd_delta.diff))
            if abs_diffs:
                param_diffs[param] = round(sum(abs_diffs) / len(abs_diffs), 4)

        return {
            "session_a": f"{self.session_a.timestamp} ({self.session_a.game_id})",
            "session_b": f"{self.session_b.timestamp} ({self.session_b.game_id})",
            "total_steps_a": len(steps_a),
            "total_steps_b": len(steps_b),
            "common_steps": len(common_steps),
            "divergence_count": divergence_count,
            "divergence_rate": round(divergence_rate, 4),
            "param_diffs": param_diffs,
        }

    def to_markdown(self) -> str:
        """Full diff report in Markdown format."""
        lines: list[str] = ["# Session Diff Report", ""]

        # Summary
        s = self.summary()
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Session A**: {s['session_a']}")
        lines.append(f"- **Session B**: {s['session_b']}")
        lines.append(f"- **Steps A**: {s['total_steps_a']}")
        lines.append(f"- **Steps B**: {s['total_steps_b']}")
        lines.append(f"- **Common steps**: {s['common_steps']}")
        lines.append(f"- **Divergence count**: {s['divergence_count']}")
        lines.append(f"- **Divergence rate**: {s['divergence_rate']:.2%}")
        lines.append("")

        # Divergence points table
        div_points = self.divergence_points()
        if div_points:
            lines.append("## Divergence Points")
            lines.append("")

            # Build DataFrame for display
            div_rows: list[dict[str, Any]] = []
            for sd in div_points:
                row: dict[str, Any] = {
                    "step": sd.step,
                    "action_a": sd.action_a or "",
                    "action_b": sd.action_b or "",
                }
                # Include top param diffs
                for param, pd_delta in sd.param_deltas.items():
                    if pd_delta.diff is not None:
                        row[f"{param}_diff"] = round(pd_delta.diff, 2)
                div_rows.append(row)

            df_div = pd.DataFrame(div_rows)
            lines.append(_df_to_markdown(df_div, index=False))
            lines.append("")
        else:
            lines.append("## Divergence Points")
            lines.append("")
            lines.append("No divergence points found (identical actions).")
            lines.append("")

        # Per-parameter comparison
        all_params = sorted(
            set(self.session_a.parameters) | set(self.session_b.parameters)
        )
        if all_params:
            lines.append("## Parameter Comparison")
            lines.append("")
            for param in all_params:
                pc = self.param_comparison(param)
                if pc.empty:
                    continue
                # Compute summary stats
                valid_diffs = pc["diff"].dropna()
                if len(valid_diffs) == 0:
                    continue
                mean_diff = valid_diffs.abs().mean()
                max_diff = valid_diffs.abs().max()
                trend = "rising" if valid_diffs.mean() > 0 else "falling" if valid_diffs.mean() < 0 else "flat"
                lines.append(f"### {param}")
                lines.append(f"- Mean |diff|: {mean_diff:.4f}")
                lines.append(f"- Max |diff|: {max_diff:.4f}")
                lines.append(f"- Trajectory: B vs A is **{trend}**")
                lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable output combining summary + all step diffs."""
        return {
            "summary": self.summary(),
            "step_diffs": [sd.to_dict() for sd in self.step_diffs()],
            "divergence_points": [sd.to_dict() for sd in self.divergence_points()],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_diff(args: argparse.Namespace) -> None:
    """Execute the diff subcommand."""
    session_a = SessionData.from_log_path(args.session_a)
    session_b = SessionData.from_log_path(args.session_b)

    differ = ReplayDiff(session_a, session_b)

    if args.format == "json":
        if args.param:
            # JSON output for a specific parameter
            pc = differ.param_comparison(args.param)
            output = json.dumps(pc.to_dict(orient="records"), indent=2, default=str)
        else:
            output = json.dumps(differ.to_dict(), indent=2, default=str)
    else:
        if args.param:
            # Markdown for a specific parameter
            pc = differ.param_comparison(args.param)
            output = f"# Parameter Comparison: {args.param}\n\n"
            output += _df_to_markdown(pc, index=False)
        else:
            output = differ.to_markdown()

    if args.output:
        Path(args.output).write_text(output)
        logger.info("Output written to %s", args.output)
    else:
        print(output)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="replay_diff",
        description="Step-level diff between two agent sessions.",
    )
    sub = parser.add_subparsers(dest="command")

    p_diff = sub.add_parser("diff", help="Diff two sessions step-by-step")
    p_diff.add_argument("session_a", help="Path to session A CSV")
    p_diff.add_argument("session_b", help="Path to session B CSV")
    p_diff.add_argument("--format", choices=["markdown", "json"], default="markdown",
                        help="Output format (default: markdown)")
    p_diff.add_argument("--output", default=None, help="Write output to file instead of stdout")
    p_diff.add_argument("--param", default=None, help="Focus on a specific parameter")
    p_diff.set_defaults(func=_cmd_diff)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
