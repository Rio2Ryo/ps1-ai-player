#!/usr/bin/env python3
"""Session Parameter Trend Prediction — linear regression + moving average.

Predicts where session parameters (hp, gold, score, etc.) are heading:
  - "HP will reach 0 at step ~45"
  - "gold will exceed 10000 around step 80"

Uses linear regression (OLS) and rolling averages for trend extrapolation,
with threshold-arrival estimation and forecast series generation.

Usage:
    python parameter_predictor.py predict <csv_path> [--window 10] [--extra-steps 20] [--format markdown|json]
    python parameter_predictor.py forecast <csv_path> --param hp [--steps 30]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from log_config import get_logger
from session_replay import SessionData

logger = get_logger(__name__)


class ParameterPredictor:
    """Statistical trend prediction for session parameters."""

    def __init__(self, session: SessionData, window: int = 10) -> None:
        self.session = session
        self.window = window

    # -- Core methods --------------------------------------------------------

    def linear_regression(self, param: str) -> dict:
        """Fit OLS on step vs parameter value.

        Returns ``{"slope": float, "intercept": float, "r_squared": float}``.
        """
        df = self.session.df
        x = df["step"].values.astype(float)
        y = df[param].values.astype(float)

        # Remove NaN entries
        mask = ~(np.isnan(x) | np.isnan(y))
        x, y = x[mask], y[mask]

        if len(x) < 2:
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}

        coeffs = np.polyfit(x, y, 1)
        slope, intercept = float(coeffs[0]), float(coeffs[1])

        # R-squared
        y_pred = slope * x + intercept
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot != 0 else 0.0

        return {"slope": slope, "intercept": intercept, "r_squared": r_squared}

    def moving_average(self, param: str) -> pd.Series:
        """Return rolling mean with ``window=self.window``, ``min_periods=1``."""
        return self.session.df[param].rolling(window=self.window, min_periods=1).mean()

    def predict_value(self, param: str, step: int) -> float:
        """Predict parameter value at a future step using linear regression."""
        reg = self.linear_regression(param)
        return reg["intercept"] + reg["slope"] * step

    def predict_threshold(
        self,
        param: str,
        threshold: float,
        direction: str = "below",
    ) -> int | None:
        """Estimate at which step *param* will cross *threshold*.

        ``direction="below"``: step where value drops below threshold (e.g. HP=0).
        ``direction="above"``: step where value rises above threshold.

        Returns ``None`` if the trend doesn't go in that direction or the
        crossing is already in the past.
        """
        reg = self.linear_regression(param)
        slope = reg["slope"]
        intercept = reg["intercept"]

        if slope == 0:
            return None

        # solve: intercept + slope * step = threshold
        step_cross = (threshold - intercept) / slope

        # Check direction makes sense
        if direction == "below" and slope >= 0:
            return None
        if direction == "above" and slope <= 0:
            return None

        step_cross_int = int(math.ceil(step_cross))
        max_step = int(self.session.df["step"].max())

        if step_cross_int <= max_step:
            return None

        return step_cross_int

    def predict_all_thresholds(
        self,
        thresholds: dict[str, list[tuple[float, str]]] | None = None,
    ) -> list[dict]:
        """Batch threshold prediction.

        *thresholds* maps param names to lists of ``(threshold_value, direction)``
        pairs.  If empty or ``None``, auto-generates sensible defaults: for each
        param, predict reaching 0 (``"below"``) and 2× current max (``"above"``).
        """
        if not thresholds:
            thresholds = {}
            for param in self.session.parameters:
                col = self.session.df[param]
                current_max = float(col.max())
                thresholds[param] = [
                    (0.0, "below"),
                    (current_max * 2, "above"),
                ]

        results: list[dict] = []
        for param, pairs in thresholds.items():
            reg = self.linear_regression(param)
            current_value = float(self.session.df[param].iloc[-1])
            for thresh_val, direction in pairs:
                est = self.predict_threshold(param, thresh_val, direction)
                results.append({
                    "parameter": param,
                    "threshold": thresh_val,
                    "direction": direction,
                    "estimated_step": est,
                    "current_value": current_value,
                    "slope": reg["slope"],
                })
        return results

    def forecast_series(self, param: str, extra_steps: int = 20) -> pd.DataFrame:
        """Return DataFrame with columns: step, actual, predicted, moving_avg.

        Includes all existing steps plus *extra_steps* future steps.
        """
        df = self.session.df
        reg = self.linear_regression(param)
        ma = self.moving_average(param)

        existing_steps = df["step"].values.astype(int)
        max_step = int(existing_steps.max()) if len(existing_steps) > 0 else 0
        future_steps = np.arange(max_step + 1, max_step + 1 + extra_steps)
        all_steps = np.concatenate([existing_steps, future_steps])

        # Actual values (NaN for future)
        actual = list(df[param].values) + [float("nan")] * extra_steps

        # Predicted (linear regression for all steps)
        predicted = [reg["intercept"] + reg["slope"] * s for s in all_steps]

        # Moving average (NaN for future)
        ma_values = list(ma.values) + [float("nan")] * extra_steps

        return pd.DataFrame({
            "step": all_steps,
            "actual": actual,
            "predicted": predicted,
            "moving_avg": ma_values,
        })

    def to_dict(self) -> dict:
        """JSON-serialisable summary with per-param regression stats,
        threshold predictions, and forecast data."""
        result: dict[str, Any] = {
            "session": self.session.csv_path.name,
            "window": self.window,
            "parameters": {},
        }

        for param in self.session.parameters:
            reg = self.linear_regression(param)
            forecast = self.forecast_series(param)
            result["parameters"][param] = {
                "regression": reg,
                "forecast": {
                    "step": forecast["step"].tolist(),
                    "actual": [
                        None if (isinstance(v, float) and math.isnan(v)) else v
                        for v in forecast["actual"].tolist()
                    ],
                    "predicted": forecast["predicted"].tolist(),
                    "moving_avg": [
                        None if (isinstance(v, float) and math.isnan(v)) else v
                        for v in forecast["moving_avg"].tolist()
                    ],
                },
            }

        result["thresholds"] = self.predict_all_thresholds()
        return result

    def to_markdown(self) -> str:
        """Markdown report with regression summary table and threshold predictions."""
        lines: list[str] = []
        lines.append("# Parameter Trend Prediction")
        lines.append("")
        lines.append(f"**Session:** {self.session.csv_path.name}")
        lines.append(f"**Window:** {self.window}")
        lines.append("")

        # Regression summary table
        lines.append("## Regression Summary")
        lines.append("")
        lines.append("| Parameter | Slope | Intercept | R² | Trend |")
        lines.append("|-----------|-------|-----------|-----|-------|")
        for param in self.session.parameters:
            reg = self.linear_regression(param)
            trend = "rising" if reg["slope"] > 0 else ("falling" if reg["slope"] < 0 else "flat")
            lines.append(
                f"| {param} | {reg['slope']:.4f} | {reg['intercept']:.4f} "
                f"| {reg['r_squared']:.4f} | {trend} |"
            )
        lines.append("")

        # Threshold predictions
        thresholds = self.predict_all_thresholds()
        lines.append("## Threshold Predictions")
        lines.append("")
        lines.append("| Parameter | Threshold | Direction | Est. Step | Current | Slope |")
        lines.append("|-----------|-----------|-----------|-----------|---------|-------|")
        for t in thresholds:
            est = str(t["estimated_step"]) if t["estimated_step"] is not None else "N/A"
            lines.append(
                f"| {t['parameter']} | {t['threshold']:.2f} | {t['direction']} "
                f"| {est} | {t['current_value']:.2f} | {t['slope']:.4f} |"
            )
        lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def plot_prediction(
    predictor: ParameterPredictor,
    param: str,
    extra_steps: int = 20,
    output_path: Path = Path("prediction.png"),
    thresholds: list[float] | None = None,
) -> Path:
    """Generate a prediction chart for a single parameter.

    - Blue line: actual values
    - Orange dashed: linear regression (extended into future)
    - Green line: moving average
    - Red horizontal lines: threshold markers
    - Grey shaded area: forecast zone
    """
    forecast = predictor.forecast_series(param, extra_steps)
    max_actual_step = int(predictor.session.df["step"].max())

    fig, ax = plt.subplots(figsize=(10, 5))

    # Actual values
    mask_actual = forecast["step"] <= max_actual_step
    ax.plot(
        forecast.loc[mask_actual, "step"],
        forecast.loc[mask_actual, "actual"],
        color="blue", linewidth=1.2, label="Actual",
    )

    # Moving average
    ax.plot(
        forecast.loc[mask_actual, "step"],
        forecast.loc[mask_actual, "moving_avg"],
        color="green", linewidth=1.0, label="Moving Avg",
    )

    # Linear regression (full range)
    ax.plot(
        forecast["step"],
        forecast["predicted"],
        color="orange", linewidth=1.0, linestyle="--", label="Linear Regression",
    )

    # Forecast zone shading
    ax.axvspan(
        max_actual_step + 0.5,
        forecast["step"].max() + 0.5,
        alpha=0.1, color="grey", label="Forecast Zone",
    )

    # Threshold markers
    if thresholds:
        for thresh in thresholds:
            ax.axhline(y=thresh, color="red", linewidth=0.8, linestyle=":", alpha=0.7)

    ax.set_xlabel("Step")
    ax.set_ylabel(param)
    ax.set_title(f"Prediction: {param}")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    logger.info("Saved prediction chart: %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Session Parameter Trend Prediction",
    )
    sub = parser.add_subparsers(dest="command")

    # predict
    p_predict = sub.add_parser("predict", help="Predict all parameter trends")
    p_predict.add_argument("csv_path", type=Path, help="Session CSV file")
    p_predict.add_argument("--window", type=int, default=10, help="Moving average window")
    p_predict.add_argument("--extra-steps", type=int, default=20, help="Future steps to forecast")
    p_predict.add_argument(
        "--format", dest="fmt", choices=["markdown", "json"], default="markdown",
        help="Output format",
    )

    # forecast
    p_forecast = sub.add_parser("forecast", help="Forecast a single parameter")
    p_forecast.add_argument("csv_path", type=Path, help="Session CSV file")
    p_forecast.add_argument("--param", required=True, help="Parameter name")
    p_forecast.add_argument("--steps", type=int, default=30, help="Extra steps to forecast")
    p_forecast.add_argument("--window", type=int, default=10, help="Moving average window")

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    session = SessionData.from_log_path(args.csv_path)
    predictor = ParameterPredictor(session, window=args.window)

    if args.command == "predict":
        if args.fmt == "json":
            print(json.dumps(predictor.to_dict(), indent=2))
        else:
            print(predictor.to_markdown())

    elif args.command == "forecast":
        forecast_df = predictor.forecast_series(args.param, extra_steps=args.steps)
        print(forecast_df.to_string(index=False))


if __name__ == "__main__":
    main()
