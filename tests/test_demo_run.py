"""Tests for demo_run.py end-to-end demo script."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from demo_run import run_demo, _ensure_sample_data, GENRE_SAMPLES

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


def test_demo_run_generates_sample_if_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sample CSV is auto-generated when absent."""
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

    # Point PROJECT_ROOT to tmp_path so _ensure_sample_data looks there
    import demo_run
    monkeypatch.setattr(demo_run, "PROJECT_ROOT", tmp_path)

    fake_csv = sample_dir / "sample_log.csv"
    assert not fake_csv.exists()

    result = _ensure_sample_data("themepark")
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


def test_genre_samples_mapping() -> None:
    """GENRE_SAMPLES contains expected genres with valid tuples."""
    assert "themepark" in GENRE_SAMPLES
    assert "rpg" in GENRE_SAMPLES
    assert "action" in GENRE_SAMPLES
    assert "survival_horror" in GENRE_SAMPLES
    assert "fighting" in GENRE_SAMPLES
    for genre, (csv_name, gen_module) in GENRE_SAMPLES.items():
        assert csv_name.endswith(".csv"), f"{genre} csv_name should end with .csv"
        assert isinstance(gen_module, str), f"{genre} gen_module should be a string"


def test_demo_run_rpg_genre(tmp_path: Path) -> None:
    """RPG genre demo runs analysis + GDD + charts, skips simulation."""
    output_dir = tmp_path / "rpg_out"
    files = run_demo(frames=60, output_dir=output_dir, genre="rpg")

    assert output_dir.exists()
    extensions = {p.suffix for p in files}
    assert ".json" in extensions  # causal chains
    assert ".md" in extensions    # GDD
    assert ".png" in extensions   # charts
    # No simulation CSV for non-themepark genres
    sim_csvs = [p for p in files if p.name == "simulation_output.csv"]
    assert len(sim_csvs) == 0


def test_demo_run_action_genre(tmp_path: Path) -> None:
    """Action genre demo runs analysis + GDD + charts, skips simulation."""
    output_dir = tmp_path / "action_out"
    files = run_demo(frames=60, output_dir=output_dir, genre="action")

    assert output_dir.exists()
    extensions = {p.suffix for p in files}
    assert ".json" in extensions
    assert ".md" in extensions


def test_demo_run_survival_horror_genre(tmp_path: Path) -> None:
    """Survival horror genre demo runs analysis + GDD + charts, skips simulation."""
    output_dir = tmp_path / "survival_horror_out"
    files = run_demo(frames=60, output_dir=output_dir, genre="survival_horror")

    assert output_dir.exists()
    extensions = {p.suffix for p in files}
    assert ".json" in extensions
    assert ".md" in extensions
    assert ".png" in extensions
    sim_csvs = [p for p in files if p.name == "simulation_output.csv"]
    assert len(sim_csvs) == 0


def test_demo_run_fighting_genre(tmp_path: Path) -> None:
    """Fighting genre demo runs analysis + GDD + charts, skips simulation."""
    output_dir = tmp_path / "fighting_out"
    files = run_demo(frames=60, output_dir=output_dir, genre="fighting")

    assert output_dir.exists()
    extensions = {p.suffix for p in files}
    assert ".json" in extensions
    assert ".md" in extensions
    assert ".png" in extensions
    sim_csvs = [p for p in files if p.name == "simulation_output.csv"]
    assert len(sim_csvs) == 0
