#!/usr/bin/env python3
"""Visualization module for gameplay data and causal chain analysis.

Generates PNG charts: correlation heatmap, parameter time-series,
lag correlation bar chart, and causal chain graph.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # headless rendering
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from log_config import get_logger

logger = get_logger(__name__)

DEFAULT_OUTPUT_DIR = Path.home() / "ps1-ai-player" / "reports"


def plot_correlation_heatmap(
    df: pd.DataFrame,
    numeric_cols: list[str],
    output_path: Path,
) -> Path:
    """Generate a correlation heatmap between all numeric parameters."""
    corr = df[numeric_cols].corr()

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(numeric_cols)))
    ax.set_yticks(range(len(numeric_cols)))
    ax.set_xticklabels(numeric_cols, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(numeric_cols, fontsize=9)

    # Annotate cells
    for i in range(len(numeric_cols)):
        for j in range(len(numeric_cols)):
            val = corr.values[i, j]
            color = "white" if abs(val) > 0.6 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=8, color=color)

    fig.colorbar(im, ax=ax, label="Pearson r")
    ax.set_title("Parameter Correlation Heatmap")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    logger.info("Saved correlation heatmap: %s", output_path)
    return output_path


def plot_time_series(
    df: pd.DataFrame,
    numeric_cols: list[str],
    output_path: Path,
) -> Path:
    """Plot all parameters as time-series subplots."""
    n = len(numeric_cols)
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.5 * n), sharex=True)
    if n == 1:
        axes = [axes]

    x = df.index if "frame" not in df.columns else df["frame"]

    for ax, col in zip(axes, numeric_cols):
        ax.plot(x, df[col], linewidth=0.8, alpha=0.9)
        ax.set_ylabel(col, fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=8)

    axes[-1].set_xlabel("Frame")
    fig.suptitle("Parameter Time Series", fontsize=12)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    logger.info("Saved time-series plot: %s", output_path)
    return output_path


def plot_lag_correlations(
    lag_data: dict[str, Any],
    output_path: Path,
) -> Path:
    """Bar chart of lag correlations (source→target with lag and r-value)."""
    if not lag_data:
        logger.warning("No lag correlations to plot.")
        return output_path

    labels = []
    corrs = []
    lags = []
    for key, data in lag_data.items():
        labels.append(f"{data['source']}→{data['target']}")
        corrs.append(data["correlation"])
        lags.append(data["lag"])

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.5)))
    y_pos = range(len(labels))
    colors = ["#d32f2f" if c < 0 else "#1976d2" for c in corrs]

    bars = ax.barh(y_pos, corrs, color=colors, alpha=0.8, height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Correlation (r)")
    ax.set_title("Lag Cross-Correlations")
    ax.axvline(x=0, color="black", linewidth=0.5)
    ax.set_xlim(-1, 1)

    # Annotate with lag values
    for i, (bar, lag) in enumerate(zip(bars, lags)):
        width = bar.get_width()
        x_pos = width + 0.02 if width >= 0 else width - 0.02
        ha = "left" if width >= 0 else "right"
        ax.text(x_pos, i, f"lag={lag}", va="center", ha=ha, fontsize=8, color="gray")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    logger.info("Saved lag correlation chart: %s", output_path)
    return output_path


def plot_causal_graph(
    chains: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Draw a causal chain graph using matplotlib arrows."""
    if not chains:
        logger.warning("No causal chains to plot.")
        return output_path

    # Collect all unique parameters
    params = set()
    edges: list[tuple[str, str, float, int]] = []
    for chain in chains:
        trigger = chain.get("trigger", "").replace(" change", "")
        params.add(trigger)
        for effect in chain.get("effects", []):
            target = effect.get("parameter", "")
            params.add(target)
            edges.append((
                trigger,
                target,
                effect.get("correlation", 0),
                effect.get("lag_frames", 0),
            ))

    param_list = sorted(params)
    n = len(param_list)

    # Position nodes in a circle
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    positions = {p: (np.cos(a), np.sin(a)) for p, a in zip(param_list, angles)}

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_aspect("equal")

    # Draw nodes
    for param, (x, y) in positions.items():
        circle = plt.Circle((x, y), 0.12, fill=True, facecolor="#e3f2fd",
                            edgecolor="#1565c0", linewidth=2, zorder=3)
        ax.add_patch(circle)
        ax.text(x, y, param, ha="center", va="center", fontsize=8,
                fontweight="bold", zorder=4)

    # Draw edges
    for src, tgt, corr, lag in edges:
        sx, sy = positions[src]
        tx, ty = positions[tgt]

        color = "#d32f2f" if corr < 0 else "#2e7d32"
        width = max(0.5, abs(corr) * 3)

        ax.annotate(
            "", xy=(tx, ty), xytext=(sx, sy),
            arrowprops=dict(
                arrowstyle="->",
                color=color,
                lw=width,
                alpha=0.7,
                connectionstyle="arc3,rad=0.1",
            ),
            zorder=2,
        )

        # Label edge
        mx, my = (sx + tx) / 2, (sy + ty) / 2
        ax.text(mx, my + 0.05, f"r={corr:.2f}\nlag={lag}",
                fontsize=6, ha="center", color=color, alpha=0.9)

    ax.set_xlim(-1.5, 1.5)
    ax.set_ylim(-1.5, 1.5)
    ax.set_title("Causal Chain Graph", fontsize=13)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    logger.info("Saved causal graph: %s", output_path)
    return output_path


def generate_all_charts(
    csv_path: Path,
    chains_json_path: Path | None = None,
    output_dir: Path | None = None,
) -> list[Path]:
    """Generate all visualization charts from a CSV log and optional chains JSON.

    Returns:
        List of generated file paths.
    """
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    # Load CSV
    df = pd.read_csv(csv_path)
    numeric_cols = [
        c for c in df.columns
        if c not in ("timestamp", "frame", "source_file", "action", "reasoning", "observations")
        and pd.api.types.is_numeric_dtype(df[c])
    ]

    if not numeric_cols:
        logger.warning("No numeric columns found in %s", csv_path)
        return generated

    stem = csv_path.stem

    # 1. Correlation heatmap
    generated.append(plot_correlation_heatmap(
        df, numeric_cols, output_dir / f"{stem}_correlation.png"
    ))

    # 2. Time series
    generated.append(plot_time_series(
        df, numeric_cols, output_dir / f"{stem}_timeseries.png"
    ))

    # 3. Lag correlations + causal graph (from chains JSON)
    if chains_json_path and chains_json_path.exists():
        data = json.loads(chains_json_path.read_text())
        lag_corrs = data.get("lag_correlations", {})
        chains = data.get("chains", [])

        generated.append(plot_lag_correlations(
            lag_corrs, output_dir / f"{stem}_lag_correlations.png"
        ))
        generated.append(plot_causal_graph(
            chains, output_dir / f"{stem}_causal_graph.png"
        ))

    logger.info("Generated %d charts in %s", len(generated), output_dir)
    return generated


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate gameplay data visualizations")
    parser.add_argument(
        "--csv", type=Path, required=True, help="CSV log file to visualize"
    )
    parser.add_argument(
        "--chains", type=Path, default=None, help="Causal chains JSON file"
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None, help="Output directory"
    )
    args = parser.parse_args()

    paths = generate_all_charts(
        csv_path=args.csv,
        chains_json_path=args.chains,
        output_dir=args.output,
    )
    for p in paths:
        print(f"  {p}")


if __name__ == "__main__":
    main()
