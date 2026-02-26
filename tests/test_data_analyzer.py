"""Tests for data_analyzer.py."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_analyzer import CausalChainExtractor


def test_load_logs(sample_csv_path: Path) -> None:
    """Load sample CSV and verify structure."""
    ext = CausalChainExtractor()
    df = ext.load_logs([sample_csv_path])
    assert not df.empty
    assert len(df) == 720
    assert "money" in df.columns
    assert "satisfaction" in df.columns


def test_compute_correlations(sample_csv_path: Path) -> None:
    """Correlation matrix is computed correctly."""
    ext = CausalChainExtractor()
    ext.load_logs([sample_csv_path])
    corr = ext.compute_correlations()
    assert not corr.empty
    # Diagonal should be 1.0
    for col in corr.columns:
        assert abs(corr.loc[col, col] - 1.0) < 1e-10


def test_detect_lag_correlations(sample_csv_path: Path) -> None:
    """Lag correlations are detected with expected structure."""
    ext = CausalChainExtractor()
    ext.load_logs([sample_csv_path])
    ext.compute_correlations()
    results = ext.detect_lag_correlations(max_lag=10)
    assert len(results) > 0
    # Each result should have source, target, lag, correlation, p_value
    for key, data in results.items():
        assert "source" in data
        assert "target" in data
        assert "lag" in data
        assert 1 <= data["lag"] <= 10
        assert -1 <= data["correlation"] <= 1


def test_build_causal_graph(sample_csv_path: Path) -> None:
    """Causal chains are built from lag correlations."""
    ext = CausalChainExtractor()
    ext.load_logs([sample_csv_path])
    ext.compute_correlations()
    ext.detect_lag_correlations()
    chains = ext.build_causal_graph()
    assert len(chains) > 0
    for chain in chains:
        assert "trigger" in chain
        assert "effects" in chain
        assert "confidence" in chain
        assert 0 <= chain["confidence"] <= 1


def test_save_results(sample_csv_path: Path, tmp_path: Path) -> None:
    """Results save to JSON with expected structure."""
    ext = CausalChainExtractor()
    ext.load_logs([sample_csv_path])
    ext.compute_correlations()
    ext.detect_lag_correlations()
    ext.build_causal_graph()
    path = ext.save_results(output_dir=tmp_path)
    assert path.exists()
    import json
    data = json.loads(path.read_text())
    assert "chains" in data
    assert "lag_correlations" in data
    assert "total_samples" in data


def test_empty_logs() -> None:
    """Handles empty log list gracefully."""
    ext = CausalChainExtractor()
    df = ext.load_logs([])
    assert df.empty
