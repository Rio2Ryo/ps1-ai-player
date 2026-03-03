"""Tests for batch_report.py — unified report generation."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from batch_report import BatchReportGenerator, main as batch_main
from session_replay import SessionData


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_session(log_dir: Path, timestamp: str = "20250101_120000",
                    game_id: str = "DEMO", rows: int = 30) -> Path:
    """Create a synthetic session CSV + sidecar files."""
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = log_dir / f"{stem}.csv"
    session_path = log_dir / f"{stem}.session.json"
    history_path = log_dir / f"{stem}.history.json"

    action_cycle = ["observe", "attack", "defend"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning", "observations",
                         "hp", "gold", "score"])
        for i in range(rows):
            writer.writerow([
                f"2025-01-01T12:00:{i:02d}", i, action_cycle[i % 3],
                "testing", "ok",
                100 - i, 50 + i * 10, 10 + i * 5,
            ])

    session_path.write_text(json.dumps({
        "cost": {"total_cost_usd": 0.05},
        "strategy": {"current": "balanced"},
    }))
    history_path.write_text(json.dumps([]))
    return csv_path


@pytest.fixture
def log_dir(tmp_path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def single_session(log_dir) -> list[SessionData]:
    _create_session(log_dir)
    return SessionData.discover_sessions(log_dir)


@pytest.fixture
def multi_sessions(log_dir) -> list[SessionData]:
    _create_session(log_dir, "20250101_120000", "DEMO", 30)
    _create_session(log_dir, "20250102_120000", "DEMO", 25)
    _create_session(log_dir, "20250103_120000", "DEMO", 35)
    return SessionData.discover_sessions(log_dir)


@pytest.fixture
def strategy_config() -> dict:
    return {
        "genre": "rpg",
        "thresholds": [
            {"parameter": "hp", "operator": "lt", "value": 30,
             "target_strategy": "defensive", "priority": 8},
            {"parameter": "gold", "operator": "gt", "value": 200,
             "target_strategy": "aggressive", "priority": 4},
        ],
    }


# ---------------------------------------------------------------------------
# TestBatchReportGenerator
# ---------------------------------------------------------------------------

class TestBatchReportGenerator:

    def test_requires_sessions(self):
        with pytest.raises(ValueError, match="requires at least 1"):
            BatchReportGenerator([])

    def test_generate_returns_dict(self, single_session):
        gen = BatchReportGenerator(single_session)
        report = gen.generate()
        assert isinstance(report, dict)
        assert "generated_at" in report
        assert report["session_count"] == 1

    def test_generate_has_all_sections(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        report = gen.generate()
        assert "cross_session" in report
        assert "anomalies" in report
        assert "predictions" in report

    def test_generate_no_strategy_section_without_config(self, single_session):
        gen = BatchReportGenerator(single_session)
        report = gen.generate()
        assert "strategy_optimization" not in report

    def test_generate_has_strategy_section_with_config(self, multi_sessions, strategy_config):
        gen = BatchReportGenerator(multi_sessions, strategy_config=strategy_config)
        report = gen.generate()
        assert "strategy_optimization" in report
        assert "diff" in report["strategy_optimization"]
        assert "notes" in report["strategy_optimization"]

    def test_cross_session_section(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        section = gen.cross_session_section()
        assert "session_count" in section
        assert section["session_count"] == 3
        assert "parameter_evolution" in section
        assert "recommendations" in section

    def test_anomaly_section(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        section = gen.anomaly_section()
        assert "total" in section
        assert "anomalies" in section

    def test_prediction_section(self, single_session):
        gen = BatchReportGenerator(single_session)
        section = gen.prediction_section()
        assert len(section) == 1
        assert "parameters" in section[0]
        assert "hp" in section[0]["parameters"]

    def test_prediction_section_multi(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        section = gen.prediction_section()
        assert len(section) == 3

    def test_strategy_section_none_without_config(self, single_session):
        gen = BatchReportGenerator(single_session)
        assert gen.strategy_section() is None

    def test_strategy_section_with_config(self, multi_sessions, strategy_config):
        gen = BatchReportGenerator(multi_sessions, strategy_config=strategy_config)
        section = gen.strategy_section()
        assert section is not None
        assert "diff" in section
        assert "optimized_config" in section


# ---------------------------------------------------------------------------
# TestOutputFormats
# ---------------------------------------------------------------------------

class TestOutputFormats:

    def test_to_dict(self, single_session):
        gen = BatchReportGenerator(single_session)
        d = gen.to_dict()
        assert isinstance(d, dict)
        assert d["session_count"] == 1

    def test_to_json(self, single_session):
        gen = BatchReportGenerator(single_session)
        j = gen.to_json()
        parsed = json.loads(j)
        assert parsed["session_count"] == 1

    def test_to_markdown(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        md = gen.to_markdown()
        assert "# Batch Analysis Report" in md
        assert "Cross-Session Analysis" in md
        assert "Anomaly Detection" in md
        assert "Parameter Predictions" in md

    def test_to_markdown_has_recommendations(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        md = gen.to_markdown()
        assert "Recommendations" in md

    def test_to_markdown_has_anomaly_counts(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        md = gen.to_markdown()
        assert "Total anomalies" in md

    def test_to_markdown_has_prediction_table(self, single_session):
        gen = BatchReportGenerator(single_session)
        md = gen.to_markdown()
        assert "Slope" in md
        assert "Trend" in md

    def test_to_markdown_with_strategy(self, multi_sessions, strategy_config):
        gen = BatchReportGenerator(multi_sessions, strategy_config=strategy_config)
        md = gen.to_markdown()
        assert "Strategy Optimization" in md

    def test_to_html(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        html = gen.to_html()
        assert "<!DOCTYPE html>" in html
        assert "Batch Analysis Report" in html
        assert "Cross-Session Analysis" in html
        assert "Anomaly Detection" in html
        assert "Parameter Predictions" in html

    def test_to_html_has_tables(self, multi_sessions):
        gen = BatchReportGenerator(multi_sessions)
        html = gen.to_html()
        assert "<table>" in html
        assert "<th>" in html

    def test_to_html_with_strategy(self, multi_sessions, strategy_config):
        gen = BatchReportGenerator(multi_sessions, strategy_config=strategy_config)
        html = gen.to_html()
        assert "Strategy Optimization" in html


# ---------------------------------------------------------------------------
# TestBatchReportCLI
# ---------------------------------------------------------------------------

class TestBatchReportCLI:

    def test_cli_no_command(self):
        with pytest.raises(SystemExit):
            batch_main([])

    def test_cli_generate_no_sessions(self, tmp_path, capsys):
        empty_dir = tmp_path / "empty_logs"
        empty_dir.mkdir()
        batch_main(["generate", "--log-dir", str(empty_dir)])
        captured = capsys.readouterr()
        assert "No sessions found" in captured.out

    def test_cli_generate_markdown(self, log_dir, capsys):
        _create_session(log_dir)
        batch_main(["generate", "--log-dir", str(log_dir)])
        captured = capsys.readouterr()
        assert "Batch Analysis Report" in captured.out

    def test_cli_generate_json(self, log_dir, capsys):
        _create_session(log_dir)
        batch_main(["generate", "--log-dir", str(log_dir), "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["session_count"] == 1

    def test_cli_generate_html(self, log_dir, capsys):
        _create_session(log_dir)
        batch_main(["generate", "--log-dir", str(log_dir), "--format", "html"])
        captured = capsys.readouterr()
        assert "<!DOCTYPE html>" in captured.out

    def test_cli_generate_output_file(self, log_dir, tmp_path):
        _create_session(log_dir)
        out_file = tmp_path / "report.md"
        batch_main(["generate", "--log-dir", str(log_dir), "--output", str(out_file)])
        assert out_file.exists()
        content = out_file.read_text()
        assert "Batch Analysis Report" in content

    def test_cli_generate_with_strategy(self, log_dir, tmp_path, capsys):
        _create_session(log_dir, "20250101_120000")
        _create_session(log_dir, "20250102_120000")
        strat_file = tmp_path / "strat.json"
        strat_file.write_text(json.dumps({
            "genre": "rpg",
            "thresholds": [
                {"parameter": "hp", "operator": "lt", "value": 30,
                 "target_strategy": "defensive", "priority": 8},
            ],
        }))
        batch_main([
            "generate", "--log-dir", str(log_dir),
            "--strategy", str(strat_file),
        ])
        captured = capsys.readouterr()
        assert "Strategy Optimization" in captured.out
