"""Shared pytest fixtures for ps1-ai-player tests."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SAMPLE_CSV = PROJECT_ROOT / "sample_data" / "sample_log.csv"
DEMO_CHAINS = PROJECT_ROOT / "reports" / "demo_causal_chains.json"


@pytest.fixture
def sample_csv_path() -> Path:
    """Path to sample_data/sample_log.csv."""
    assert SAMPLE_CSV.exists(), f"Sample CSV not found: {SAMPLE_CSV}"
    return SAMPLE_CSV


@pytest.fixture
def demo_chains_path() -> Path:
    """Path to reports/demo_causal_chains.json."""
    assert DEMO_CHAINS.exists(), f"Demo chains not found: {DEMO_CHAINS}"
    return DEMO_CHAINS


@pytest.fixture
def tmp_csv(tmp_path: Path) -> Path:
    """Create a minimal CSV file for testing."""
    csv_path = tmp_path / "test_log.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "frame", "money", "visitors", "satisfaction"])
        for i in range(50):
            writer.writerow([f"2025-01-01T12:00:{i:02d}", i, 5000 + i * 10, 50 + i, 70.0 - i * 0.2])
    return csv_path


@pytest.fixture
def tmp_addresses_dir(tmp_path: Path) -> Path:
    """Create a temp addresses directory with a test game."""
    addr_dir = tmp_path / "addresses"
    addr_dir.mkdir()
    game_data = {
        "game_id": "TEST-001",
        "parameters": {
            "money": {"address": "0x001000", "type": "int32", "description": "Gold"},
            "hp": {"address": "0x001004", "type": "uint16", "description": "Health"},
        },
    }
    (addr_dir / "TEST-001.json").write_text(json.dumps(game_data))
    return addr_dir
