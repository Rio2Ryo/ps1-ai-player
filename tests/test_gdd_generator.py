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
        "descriptive_statistics": {
            "money": {"count": 500, "mean": 5980.0, "std": 420.0, "min": 4800.0, "25%": 5650.0, "50%": 5980.0, "75%": 6300.0, "max": 7200.0},
            "visitors": {"count": 500, "mean": 50.0, "std": 15.0, "min": 10.0, "25%": 40.0, "50%": 50.0, "75%": 60.0, "max": 95.0},
            "satisfaction": {"count": 500, "mean": 55.0, "std": 18.0, "min": 5.0, "25%": 42.0, "50%": 55.0, "75%": 68.0, "max": 100.0},
            "nausea": {"count": 500, "mean": 30.0, "std": 20.0, "min": 0.0, "25%": 14.0, "50%": 28.0, "75%": 45.0, "max": 100.0},
            "hunger": {"count": 500, "mean": 40.0, "std": 22.0, "min": 0.0, "25%": 22.0, "50%": 40.0, "75%": 58.0, "max": 95.0},
        },
        "correlation_matrix": {
            "money": {"money": 1.0, "visitors": 0.12, "satisfaction": 0.45, "nausea": -0.32, "hunger": -0.18},
            "visitors": {"money": 0.12, "visitors": 1.0, "satisfaction": 0.65, "nausea": 0.28, "hunger": 0.05},
            "satisfaction": {"money": 0.45, "visitors": 0.65, "satisfaction": 1.0, "nausea": -0.78, "hunger": -0.55},
            "nausea": {"money": -0.32, "visitors": 0.28, "satisfaction": -0.78, "nausea": 1.0, "hunger": 0.15},
            "hunger": {"money": -0.18, "visitors": 0.05, "satisfaction": -0.55, "hunger": 1.0, "nausea": 0.15},
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


# ------------------------------------------------------------------
# New tests for enhanced GDD features
# ------------------------------------------------------------------


def test_load_causal_chains_with_stats(loaded_generator: GDDGenerator) -> None:
    """Verify descriptive_statistics and correlation_matrix are loaded from JSON."""
    assert "money" in loaded_generator.descriptive_statistics
    assert loaded_generator.descriptive_statistics["money"]["mean"] == 5980.0
    assert "money" in loaded_generator.correlation_matrix
    assert loaded_generator.correlation_matrix["money"]["visitors"] == 0.12


def test_from_csv(sample_csv_path: Path) -> None:
    """Test creating GDDGenerator directly from CSV."""
    gen = GDDGenerator.from_csv([sample_csv_path])
    assert len(gen.chains) > 0
    assert gen.metadata["total_samples"] > 0
    assert len(gen.metadata["parameters"]) > 0
    assert gen.descriptive_statistics  # not empty
    assert gen.correlation_matrix  # not empty
    assert gen.raw_df is not None
    assert len(gen.raw_df) > 0


def test_from_csv_empty(tmp_path: Path) -> None:
    """Test from_csv with a non-existent file."""
    gen = GDDGenerator.from_csv([tmp_path / "nonexistent.csv"])
    assert gen.chains == []
    assert gen.raw_df is None


def test_generate_statistics_section(loaded_generator: GDDGenerator) -> None:
    """Test statistics section generation with tables and classification."""
    text = loaded_generator.generate_statistics_section()
    assert "## Descriptive Statistics" in text
    assert "| Parameter | Min | Max | Mean | Std | Range |" in text
    assert "money" in text
    assert "Parameter Behavior Classification" in text


def test_generate_statistics_section_empty() -> None:
    """Test statistics section with no data."""
    gen = GDDGenerator()
    text = gen.generate_statistics_section()
    assert "No descriptive statistics available" in text


def test_generate_correlation_matrix_section(loaded_generator: GDDGenerator) -> None:
    """Test full correlation matrix section."""
    text = loaded_generator.generate_correlation_matrix_section()
    assert "## Correlation Matrix" in text
    assert "| Pair | r | Strength | Direction |" in text
    # Check that pairs are listed
    assert "money" in text
    assert "Positive" in text or "Negative" in text


def test_generate_correlation_matrix_section_empty() -> None:
    """Test correlation matrix section with no data."""
    gen = GDDGenerator()
    text = gen.generate_correlation_matrix_section()
    assert "No correlation data available" in text


def test_correlation_strength() -> None:
    """Test the correlation strength classifier."""
    assert GDDGenerator._correlation_strength(0.95) == "Very strong"
    assert GDDGenerator._correlation_strength(0.75) == "Strong"
    assert GDDGenerator._correlation_strength(0.55) == "Moderate"
    assert GDDGenerator._correlation_strength(0.35) == "Weak"
    assert GDDGenerator._correlation_strength(0.1) == "Negligible"


def test_generate_data_quality_section(loaded_generator: GDDGenerator) -> None:
    """Test data quality section (without raw_df it should still work)."""
    text = loaded_generator.generate_data_quality_section()
    assert "## Data Quality Report" in text
    assert "Total samples" in text
    assert "500" in text


def test_generate_data_quality_section_with_raw_df(sample_csv_path: Path) -> None:
    """Test data quality section with raw DataFrame available."""
    gen = GDDGenerator.from_csv([sample_csv_path])
    text = gen.generate_data_quality_section()
    assert "## Data Quality Report" in text
    assert "Total samples" in text
    assert "Time range" in text
    assert "Missing Values" in text
    assert "Outliers" in text


def test_generate_event_analysis_section_no_actions(loaded_generator: GDDGenerator) -> None:
    """Test event analysis when no action column exists."""
    text = loaded_generator.generate_event_analysis_section()
    assert "## Event / Action Analysis" in text
    assert "No action/event data available" in text


def test_generate_event_analysis_section_with_actions(tmp_path: Path) -> None:
    """Test event analysis with action data."""
    import csv

    csv_path = tmp_path / "actions.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "frame", "money", "action"])
        for i in range(50):
            action = ["buy_food", "ride", "explore", "rest"][i % 4]
            writer.writerow([f"2025-01-01T12:00:{i:02d}", i, 5000 + i, action])

    gen = GDDGenerator.from_csv([csv_path])
    text = gen.generate_event_analysis_section()
    assert "## Event / Action Analysis" in text
    assert "Top Actions" in text
    assert "buy_food" in text
    assert "ride" in text


def test_generate_local_gdd(loaded_generator: GDDGenerator) -> None:
    """Test local GDD generation (the method moved from pipeline.py)."""
    gdd = loaded_generator.generate_local_gdd(game_id="TESTGAME")
    assert "# Game Design Document: TESTGAME" in gdd
    assert "## Overview" in gdd
    assert "## Parameter Definitions" in gdd
    assert "## Core Mechanics" in gdd
    assert "## Balance Design" in gdd
    assert "## Feedback Loops" in gdd
    assert "## Descriptive Statistics" in gdd
    assert "## Correlation Matrix" in gdd
    assert "## Data Quality Report" in gdd
    assert "## Implementation Priority" in gdd
    assert "Local analysis (no LLM)" in gdd


def test_generate_local_gdd_infer_roles(loaded_generator: GDDGenerator) -> None:
    """Test that parameter roles are inferred, not hardcoded."""
    gdd = loaded_generator.generate_local_gdd(game_id="TEST")
    assert "Primary resource / economy indicator" in gdd  # money
    assert "Population / demand metric" in gdd  # visitors
    assert "Quality of experience indicator" in gdd  # satisfaction
    assert "Negative status effect" in gdd  # nausea
    assert "Time-dependent need" in gdd  # hunger


def test_to_dict(loaded_generator: GDDGenerator) -> None:
    """Test structured JSON export."""
    d = loaded_generator.to_dict()
    assert "metadata" in d
    assert "descriptive_statistics" in d
    assert "correlation_matrix" in d
    assert "causal_chains" in d
    assert "sections" in d
    assert "mechanics" in d["sections"]
    assert "balance" in d["sections"]
    assert "statistics" in d["sections"]
    assert "correlation_analysis" in d["sections"]
    assert "data_quality" in d["sections"]
    assert "event_analysis" in d["sections"]
    # Verify it's JSON-serializable
    json_str = json.dumps(d)
    assert len(json_str) > 0


def test_save_gdd_json(loaded_generator: GDDGenerator, tmp_path: Path) -> None:
    """Test saving GDD in JSON format."""
    content = "# Test GDD\nMarkdown content."
    path = loaded_generator.save_gdd(
        content, game_id="TEST", output_dir=tmp_path, fmt="json"
    )
    assert path.exists()
    assert path.suffix == ".json"
    data = json.loads(path.read_text())
    assert "metadata" in data
    assert "sections" in data


def test_save_gdd_both(loaded_generator: GDDGenerator, tmp_path: Path) -> None:
    """Test saving GDD in both markdown and JSON formats."""
    content = "# Test GDD\nMarkdown content."
    md_path = loaded_generator.save_gdd(
        content, game_id="TEST", output_dir=tmp_path, fmt="both"
    )
    assert md_path.exists()
    assert md_path.suffix == ".md"
    assert md_path.read_text() == content

    # JSON should also exist with same stem
    json_path = md_path.with_suffix(".json")
    assert json_path.exists()
    data = json.loads(json_path.read_text())
    assert "metadata" in data


def test_from_csv_full_pipeline(sample_csv_path: Path, tmp_path: Path) -> None:
    """End-to-end test: CSV -> GDDGenerator -> local GDD -> save both."""
    gen = GDDGenerator.from_csv([sample_csv_path])
    gdd = gen.generate_local_gdd(game_id="E2E_TEST")
    path = gen.save_gdd(gdd, game_id="E2E_TEST", output_dir=tmp_path, fmt="both")
    assert path.exists()
    text = path.read_text()
    assert "# Game Design Document: E2E_TEST" in text
    assert "## Descriptive Statistics" in text
    assert "## Correlation Matrix" in text
    assert "## Data Quality Report" in text
    # JSON file
    json_path = path.with_suffix(".json")
    assert json_path.exists()


# ------------------------------------------------------------------
# LLM prompt language tests
# ------------------------------------------------------------------


def test_build_llm_prompt_ja() -> None:
    """Default (ja) prompt should be in Japanese."""
    prompt = GDDGenerator._build_llm_prompt("{}", "{}", lang="ja")
    assert "日本語で記述してください" in prompt
    assert "因果チェーンデータ" in prompt


def test_build_llm_prompt_en() -> None:
    """English prompt should be in English."""
    prompt = GDDGenerator._build_llm_prompt("{}", "{}", lang="en")
    assert "Write in English" in prompt
    assert "Causal Chain Data" in prompt
    assert "日本語" not in prompt


def test_build_llm_prompt_default_is_ja() -> None:
    """No lang argument should default to Japanese."""
    prompt = GDDGenerator._build_llm_prompt("{}", "{}")
    assert "日本語で記述してください" in prompt


# ------------------------------------------------------------------
# N-node cycle detection tests
# ------------------------------------------------------------------


def test_feedback_loops_3_node_cycle() -> None:
    """Detect a 3-node cycle A → B → C → A."""
    gen = GDDGenerator()
    gen.chains = []
    gen.metadata = {
        "parameters": ["alpha", "beta", "gamma"],
        "lag_correlations": {
            "alpha -> beta": {
                "source": "alpha",
                "target": "beta",
                "lag": 3,
                "correlation": 0.7,
                "p_value": 0.001,
            },
            "beta -> gamma": {
                "source": "beta",
                "target": "gamma",
                "lag": 4,
                "correlation": 0.5,
                "p_value": 0.01,
            },
            "gamma -> alpha": {
                "source": "gamma",
                "target": "alpha",
                "lag": 2,
                "correlation": 0.6,
                "p_value": 0.005,
            },
        },
    }
    text = gen.generate_feedback_loops_section()
    assert "## Feedback Loops" in text
    # Should detect the 3-node cycle
    assert "alpha" in text
    assert "beta" in text
    assert "gamma" in text
    # All positive correlations → product > 0 → positive feedback
    assert "positive feedback" in text


def test_feedback_loops_3_node_negative_cycle() -> None:
    """A 3-node cycle with odd number of negative edges is negative feedback."""
    gen = GDDGenerator()
    gen.chains = []
    gen.metadata = {
        "parameters": ["x", "y", "z"],
        "lag_correlations": {
            "x -> y": {
                "source": "x", "target": "y",
                "lag": 2, "correlation": 0.6, "p_value": 0.01,
            },
            "y -> z": {
                "source": "y", "target": "z",
                "lag": 3, "correlation": -0.5, "p_value": 0.02,
            },
            "z -> x": {
                "source": "z", "target": "x",
                "lag": 1, "correlation": 0.4, "p_value": 0.03,
            },
        },
    }
    text = gen.generate_feedback_loops_section()
    # Product: 0.6 * (-0.5) * 0.4 = -0.12 → negative
    assert "negative feedback" in text


def test_find_cycles_static() -> None:
    """Direct test of the _find_cycles static method."""
    edges = {
        "A": [("B", 0.5)],
        "B": [("C", 0.6), ("A", 0.4)],
        "C": [("A", 0.7)],
    }
    cycles = GDDGenerator._find_cycles(edges)
    # Should find 2-node cycle A↔B and 3-node cycle A→B→C→A
    assert len(cycles) == 2
    cycle_lengths = sorted(len(c) for c in cycles)
    assert cycle_lengths == [2, 3]
