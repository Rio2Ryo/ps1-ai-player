"""Tests for visualizer.py — validates chart properties via matplotlib introspection."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

# Restore real PIL if it was replaced by a MagicMock (test_agent_components does this)
_pil = sys.modules.get("PIL")
if _pil is not None and not hasattr(_pil, "__path__"):
    for key in list(sys.modules):
        if key == "PIL" or key.startswith("PIL."):
            del sys.modules[key]

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from visualizer import (
    generate_all_charts,
    plot_causal_graph,
    plot_correlation_heatmap,
    plot_lag_correlations,
    plot_time_series,
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Small DataFrame for chart tests."""
    rng = np.random.default_rng(42)
    n = 50
    return pd.DataFrame({
        "frame": np.arange(n),
        "money": 5000 + rng.normal(0, 100, n),
        "visitors": 50 + rng.normal(0, 10, n),
        "satisfaction": 70 + rng.normal(0, 5, n),
    })


@pytest.fixture
def numeric_cols() -> list[str]:
    return ["money", "visitors", "satisfaction"]


@pytest.fixture
def sample_lag_data() -> dict:
    return {
        "money -> visitors": {
            "source": "money",
            "target": "visitors",
            "lag": 3,
            "correlation": 0.65,
            "p_value": 0.001,
        },
        "visitors -> satisfaction": {
            "source": "visitors",
            "target": "satisfaction",
            "lag": 5,
            "correlation": -0.45,
            "p_value": 0.01,
        },
    }


@pytest.fixture
def sample_chains() -> list[dict]:
    return [
        {
            "trigger": "money change",
            "effects": [
                {"parameter": "visitors", "delta": "+2.0/step", "lag_frames": 3, "correlation": 0.65},
            ],
            "confidence": 0.65,
        },
        {
            "trigger": "visitors change",
            "effects": [
                {"parameter": "satisfaction", "delta": "-1.0/step", "lag_frames": 5, "correlation": -0.45},
            ],
            "confidence": 0.45,
        },
    ]


# ---- Helpers ----

def _call_with_open_fig(func, *args, **kwargs):
    """Call a plot function with plt.close patched to no-op, return (result, fig)."""
    with patch.object(plt, "close"):
        result = func(*args, **kwargs)
        fig = plt.gcf()
    return result, fig


# ---- Tests ----


def test_plot_correlation_heatmap_color_range(
    sample_df: pd.DataFrame,
    numeric_cols: list[str],
    tmp_path: Path,
) -> None:
    """Heatmap image clim should be (-1, 1), axis labels match cols, colorbar exists."""
    out = tmp_path / "corr.png"
    _, fig = _call_with_open_fig(plot_correlation_heatmap, sample_df, numeric_cols, out)

    ax = fig.axes[0]
    images = ax.get_images()
    assert len(images) == 1
    assert images[0].get_clim() == (-1.0, 1.0)

    # Axis labels
    xlabels = [t.get_text() for t in ax.get_xticklabels()]
    ylabels = [t.get_text() for t in ax.get_yticklabels()]
    assert xlabels == numeric_cols
    assert ylabels == numeric_cols

    # Colorbar axis should exist (fig has 2 axes: main + colorbar)
    assert len(fig.axes) >= 2

    plt.close(fig)
    assert out.exists()


def test_plot_correlation_heatmap_annotations(
    sample_df: pd.DataFrame,
    numeric_cols: list[str],
    tmp_path: Path,
) -> None:
    """Text annotations should exist for every cell in the heatmap."""
    out = tmp_path / "corr_ann.png"
    _, fig = _call_with_open_fig(plot_correlation_heatmap, sample_df, numeric_cols, out)

    ax = fig.axes[0]
    texts = ax.texts
    expected_count = len(numeric_cols) ** 2
    assert len(texts) == expected_count

    plt.close(fig)


def test_plot_time_series_subplots(
    sample_df: pd.DataFrame,
    numeric_cols: list[str],
    tmp_path: Path,
) -> None:
    """Time-series should have one subplot per numeric column with matching ylabels."""
    out = tmp_path / "ts.png"
    _, fig = _call_with_open_fig(plot_time_series, sample_df, numeric_cols, out)

    axes = fig.axes
    assert len(axes) == len(numeric_cols)
    for ax, col in zip(axes, numeric_cols):
        assert ax.get_ylabel() == col

    plt.close(fig)
    assert out.exists()


def test_plot_lag_correlations_bars(
    sample_lag_data: dict,
    tmp_path: Path,
) -> None:
    """Bar count should match number of lag correlations, xlim is (-1, 1)."""
    out = tmp_path / "lag.png"
    _, fig = _call_with_open_fig(plot_lag_correlations, sample_lag_data, out)

    ax = fig.axes[0]
    # barh creates horizontal bars — count patches
    bars = [p for p in ax.patches if hasattr(p, "get_width")]
    assert len(bars) == len(sample_lag_data)
    assert ax.get_xlim() == (-1.0, 1.0)

    plt.close(fig)
    assert out.exists()


def test_plot_lag_correlations_empty(tmp_path: Path) -> None:
    """Empty lag data should return path without error."""
    out = tmp_path / "lag_empty.png"
    result = plot_lag_correlations({}, out)
    assert result == out


def test_plot_causal_graph_nodes_and_edges(
    sample_chains: list[dict],
    tmp_path: Path,
) -> None:
    """Causal graph should have circle patches for nodes and annotations for edges."""
    out = tmp_path / "causal.png"
    _, fig = _call_with_open_fig(plot_causal_graph, sample_chains, out)

    ax = fig.axes[0]

    # Count Circle patches (nodes)
    circles = [p for p in ax.patches if isinstance(p, plt.Circle)]
    # Unique params: money, visitors, satisfaction
    expected_params = {"money", "visitors", "satisfaction"}
    assert len(circles) == len(expected_params)

    # Annotations (edges) — at least one arrow annotation should exist
    annotations = [c for c in ax.get_children()
                   if hasattr(c, "arrowprops") and getattr(c, "arrowprops", None) is not None]
    assert len(annotations) >= 2  # 2 edges in sample_chains

    plt.close(fig)
    assert out.exists()


def test_generate_all_charts_count(sample_csv_path: Path, tmp_path: Path) -> None:
    """generate_all_charts should produce the expected number of chart files."""
    # Without chains JSON, only 2 charts (correlation + time-series)
    paths = generate_all_charts(csv_path=sample_csv_path, output_dir=tmp_path)
    assert len(paths) == 2
    for p in paths:
        assert p.exists()
        assert p.suffix == ".png"
