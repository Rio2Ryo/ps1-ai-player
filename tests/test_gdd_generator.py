"""Tests for gdd_generator.py sections and local generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gdd_generator import GDDGenerator


@pytest.fixture
def loaded_generator(tmp_path: Path) -> GDDGenerator:
    """Create a GDDGenerator with test causal chain data."""
    chains_data = {
        "generated_at": "2025-01-01T00:00:00",
        "total_samples": 500,
        "parameters": ["money", "visitors", "satisfaction", "nausea", "hunger"],
        "chains": [
            {
                "trigger": "ride_intensity change",
                "effects": [
                    {"parameter": "nausea", "delta": "+3.5/step", "lag_frames": 5, "correlation": 0.85},
                    {"parameter": "satisfaction", "delta": "-1.2/step", "lag_frames": 10, "correlation": -0.6},
                ],
                "confidence": 0.72,
            },
            {
                "trigger": "hunger change",
                "effects": [
                    {"parameter": "satisfaction", "delta": "-0.8/step", "lag_frames": 3, "correlation": -0.45},
                ],
                "confidence": 0.45,
            },
        ],
        "lag_correlations": {
            "ride_intensity -> nausea": {
                "source": "ride_intensity",
                "target": "nausea",
                "lag": 5,
                "correlation": 0.85,
                "p_value": 0.001,
            },
            "nausea -> satisfaction": {
                "source": "nausea",
                "target": "satisfaction",
                "lag": 10,
                "correlation": -0.6,
                "p_value": 0.002,
            },
            "satisfaction -> nausea": {
                "source": "satisfaction",
                "target": "nausea",
                "lag": 8,
                "correlation": -0.35,
                "p_value": 0.04,
            },
        },
    }
    chains_path = tmp_path / "test_chains.json"
    chains_path.write_text(json.dumps(chains_data))

    gen = GDDGenerator()
    gen.load_causal_chains(chains_path)
    return gen


def test_load_causal_chains(loaded_generator: GDDGenerator) -> None:
    assert len(loaded_generator.chains) == 2
    assert loaded_generator.metadata["total_samples"] == 500


def test_mechanics_section(loaded_generator: GDDGenerator) -> None:
    text = loaded_generator.generate_mechanics_section()
    assert "## Core Mechanics" in text
    assert "ride_intensity change" in text
    assert "nausea" in text
    assert "Confidence" in text


def test_balance_section(loaded_generator: GDDGenerator) -> None:
    text = loaded_generator.generate_balance_section()
    assert "## Balance Design" in text
    assert "Parameter Interactions" in text
    assert "ride_intensity" in text
    assert "0.85" in text or "0.850" in text


def test_feedback_loops_section(loaded_generator: GDDGenerator) -> None:
    text = loaded_generator.generate_feedback_loops_section()
    assert "## Feedback Loops" in text
    # nausea <-> satisfaction should form a loop
    assert "nausea" in text
    assert "satisfaction" in text


def test_feedback_loops_empty() -> None:
    gen = GDDGenerator()
    gen.chains = []
    gen.metadata = {"lag_correlations": {}, "parameters": []}
    text = gen.generate_feedback_loops_section()
    assert "No feedback loops detected" in text


def test_state_analysis_section(loaded_generator: GDDGenerator) -> None:
    text = loaded_generator.generate_state_analysis_section()
    assert "## Game State Analysis" in text
    assert "Menu" in text
    assert "Gameplay" in text
    assert "Dialog" in text
    assert "Loading" in text


def test_strategy_section(loaded_generator: GDDGenerator) -> None:
    text = loaded_generator.generate_strategy_section()
    assert "## Adaptive Strategy Configuration" in text
    assert "expansion" in text
    assert "cost_reduction" in text
    assert "thresholds" in text


def test_save_gdd(loaded_generator: GDDGenerator, tmp_path: Path) -> None:
    content = "# Test GDD\nSome content."
    path = loaded_generator.save_gdd(content, game_id="TEST", output_dir=tmp_path)
    assert path.exists()
    assert path.read_text() == content
    assert "GDD_TEST_" in path.name
