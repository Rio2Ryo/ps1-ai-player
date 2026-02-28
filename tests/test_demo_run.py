"""Tests for demo_run.py end-to-end demo script."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from demo_run import run_demo, _ensure_sample_data

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "sample_data" / "sample_log.csv"


def test_demo_run_creates_outputs(tmp_path: Path) -> None:
    """Full demo produces GDD, charts, and simulation CSV."""
    output_dir = tmp_path / "demo_out"
    files = run_demo(frames=60, output_dir=output_dir)

    assert output_dir.exists()
    assert len(files) >= 4  # chains JSON + GDD + charts + sim CSV

    extensions = {p.suffix for p in files}
    assert ".json" in extensions  # causal chains
    assert ".md" in extensions    # GDD markdown
    assert ".png" in extensions   # charts
    assert ".csv" in extensions   # simulation output


def test_demo_run_generates_sample_if_missing(tmp_path: Path) -> None:
    """Sample CSV is auto-generated when absent."""
    fake_csv = tmp_path / "sample_data" / "sample_log.csv"
    assert not fake_csv.exists()

    # _ensure_sample_data with a missing path triggers generate()
    # We create a minimal generate_sample.py in the same dir
    sample_dir = tmp_path / "sample_data"
    sample_dir.mkdir()
    gen_script = sample_dir / "generate_sample.py"
    gen_script.write_text(
        "from pathlib import Path\n"
        "def generate(output_path=None, num_rows=10, seed=42):\n"
        "    output_path = output_path or Path(__file__).parent / 'sample_log.csv'\n"
        "    output_path.write_text('timestamp,frame,money\\n2025-01-01,0,100\\n')\n"
        "    return output_path\n"
    )

    result = _ensure_sample_data(fake_csv)
    assert result.exists()
    assert "timestamp" in result.read_text()


def test_demo_run_custom_frames(tmp_path: Path) -> None:
    """--frames parameter controls simulation length."""
    output_dir = tmp_path / "custom_frames"
    files = run_demo(frames=30, output_dir=output_dir)

    # Find simulation CSV
    sim_csvs = [p for p in files if p.name == "simulation_output.csv"]
    assert len(sim_csvs) == 1

    lines = sim_csvs[0].read_text().strip().splitlines()
    # header + 30 data rows
    assert len(lines) == 31


def test_demo_run_output_dir_created(tmp_path: Path) -> None:
    """Output directory is created automatically even when nested."""
    output_dir = tmp_path / "a" / "b" / "c"
    assert not output_dir.exists()

    files = run_demo(frames=10, output_dir=output_dir)
    assert output_dir.exists()
    assert len(files) > 0
