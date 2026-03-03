"""Tests for session_search.py — Session Search & Filter."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from session_search import ParamCondition, SessionSearch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_session(
    log_dir: Path,
    timestamp: str = "20250101_120000",
    game_id: str = "DEMO",
    rows: int = 30,
    hp_start: int = 100,
    gold_start: int = 500,
) -> Path:
    """Create a synthetic session CSV + sidecar files."""
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = log_dir / f"{stem}.csv"
    session_path = log_dir / f"{stem}.session.json"
    history_path = log_dir / f"{stem}.history.json"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning",
                         "observations", "hp", "gold"])
        for i in range(rows):
            writer.writerow([
                f"2025-01-01T12:00:{i:02d}", i, "observe", "testing", "ok",
                hp_start - i * 2, gold_start + i * 50,
            ])

    session_path.write_text(json.dumps({
        "cost": {"total_cost_usd": 0.05},
        "strategy": {"mode": "balanced"},
    }))
    history_path.write_text(json.dumps([{"action": "observe"}]))
    return csv_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def log_dir(tmp_path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def two_sessions(log_dir) -> list[Path]:
    p1 = _create_session(log_dir, "20250101_120000", rows=30, hp_start=100, gold_start=500)
    p2 = _create_session(log_dir, "20250201_120000", rows=50, hp_start=80, gold_start=2000)
    return [p1, p2]


# ---------------------------------------------------------------------------
# TestParamCondition
# ---------------------------------------------------------------------------

class TestParamCondition:
    def test_parse_basic(self):
        c = ParamCondition.parse("hp last > 50")
        assert c.parameter == "hp"
        assert c.aggregator == "last"
        assert c.operator == ">"
        assert c.value == 50.0

    def test_parse_float_value(self):
        c = ParamCondition.parse("gold mean >= 1000.5")
        assert c.parameter == "gold"
        assert c.aggregator == "mean"
        assert c.operator == ">="
        assert c.value == 1000.5

    def test_parse_negative_value(self):
        c = ParamCondition.parse("hp min < -10")
        assert c.value == -10.0

    def test_parse_all_aggregators(self):
        for agg in ["last", "first", "mean", "min", "max", "std"]:
            c = ParamCondition.parse(f"hp {agg} > 0")
            assert c.aggregator == agg

    def test_parse_all_operators(self):
        for op in [">", ">=", "<", "<=", "==", "!="]:
            c = ParamCondition.parse(f"hp last {op} 0")
            assert c.operator == op

    def test_parse_invalid(self):
        with pytest.raises(ValueError, match="Invalid condition"):
            ParamCondition.parse("invalid")

    def test_parse_case_insensitive_aggregator(self):
        c = ParamCondition.parse("hp LAST > 50")
        assert c.aggregator == "last"

    def test_to_dict(self):
        c = ParamCondition.parse("hp last > 50")
        d = c.to_dict()
        assert d == {
            "parameter": "hp",
            "aggregator": "last",
            "operator": ">",
            "value": 50.0,
        }

    def test_evaluate_last(self, log_dir):
        _create_session(log_dir, rows=10, hp_start=100)
        from session_replay import SessionData
        s = SessionData.discover_sessions(log_dir)[0]
        # last hp = 100 - 9*2 = 82
        c = ParamCondition.parse("hp last > 50")
        assert c.evaluate(s) is True
        c2 = ParamCondition.parse("hp last > 90")
        assert c2.evaluate(s) is False

    def test_evaluate_mean(self, log_dir):
        _create_session(log_dir, rows=10, hp_start=100)
        from session_replay import SessionData
        s = SessionData.discover_sessions(log_dir)[0]
        # hp values: 100, 98, 96, ..., 82 → mean = 91
        c = ParamCondition.parse("hp mean > 90")
        assert c.evaluate(s) is True

    def test_evaluate_missing_param(self, log_dir):
        _create_session(log_dir, rows=10)
        from session_replay import SessionData
        s = SessionData.discover_sessions(log_dir)[0]
        c = ParamCondition.parse("nonexistent last > 0")
        assert c.evaluate(s) is False


# ---------------------------------------------------------------------------
# TestSessionSearch
# ---------------------------------------------------------------------------

class TestSessionSearch:
    def test_search_no_filters(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir)
        results = ss.search()
        assert len(results) == 2

    def test_filter_by_param_condition(self, log_dir, two_sessions):
        # Session 1: 30 rows, gold last = 500 + 29*50 = 1950
        # Session 2: 50 rows, gold last = 2000 + 49*50 = 4450
        ss = SessionSearch(
            log_dir=log_dir,
            param_conditions=[ParamCondition.parse("gold last > 3000")],
        )
        results = ss.search()
        assert len(results) == 1
        assert results[0].timestamp == "20250201_120000"

    def test_filter_by_min_steps(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir, min_steps=40)
        results = ss.search()
        assert len(results) == 1
        assert results[0].total_steps == 50

    def test_filter_by_max_steps(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir, max_steps=35)
        results = ss.search()
        assert len(results) == 1
        assert results[0].total_steps == 30

    def test_filter_by_step_range(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir, min_steps=25, max_steps=35)
        results = ss.search()
        assert len(results) == 1

    def test_filter_by_date_from(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir, date_from="20250201")
        results = ss.search()
        assert len(results) == 1
        assert results[0].timestamp == "20250201_120000"

    def test_filter_by_date_to(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir, date_to="20250115")
        results = ss.search()
        assert len(results) == 1
        assert results[0].timestamp == "20250101_120000"

    def test_filter_by_date_range(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir, date_from="20250101", date_to="20250101")
        results = ss.search()
        assert len(results) == 1

    def test_filter_by_tag(self, log_dir, two_sessions):
        from session_tagger import SessionTagger
        tagger = SessionTagger(log_dir=log_dir)
        tagger.tag(two_sessions[0].name, "good_run")

        ss = SessionSearch(log_dir=log_dir, tag="good_run")
        results = ss.search()
        assert len(results) == 1
        assert results[0].csv_path.name == two_sessions[0].name

    def test_filter_by_tag_no_match(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir, tag="nonexistent")
        results = ss.search()
        assert len(results) == 0

    def test_filter_by_note(self, log_dir, two_sessions):
        from session_tagger import SessionTagger
        tagger = SessionTagger(log_dir=log_dir)
        tagger.set_note(two_sessions[1].name, "Boss fight at step 42")

        ss = SessionSearch(log_dir=log_dir, note_query="boss fight")
        results = ss.search()
        assert len(results) == 1
        assert results[0].csv_path.name == two_sessions[1].name

    def test_filter_by_note_case_insensitive(self, log_dir, two_sessions):
        from session_tagger import SessionTagger
        tagger = SessionTagger(log_dir=log_dir)
        tagger.set_note(two_sessions[0].name, "LOW HP strategy")

        ss = SessionSearch(log_dir=log_dir, note_query="low hp")
        results = ss.search()
        assert len(results) == 1

    def test_combined_filters(self, log_dir, two_sessions):
        from session_tagger import SessionTagger
        tagger = SessionTagger(log_dir=log_dir)
        tagger.tag(two_sessions[0].name, "short")
        tagger.tag(two_sessions[1].name, "short")

        # Both tagged "short", but only session 2 has > 40 steps
        ss = SessionSearch(log_dir=log_dir, tag="short", min_steps=40)
        results = ss.search()
        assert len(results) == 1
        assert results[0].total_steps == 50

    def test_to_dict(self, log_dir):
        ss = SessionSearch(
            log_dir=log_dir,
            param_conditions=[ParamCondition.parse("hp last > 50")],
            min_steps=10,
            max_steps=100,
            date_from="20250101",
            date_to="20250201",
            tag="good_run",
            note_query="boss",
        )
        d = ss.to_dict()
        assert d["min_steps"] == 10
        assert d["max_steps"] == 100
        assert d["date_from"] == "20250101"
        assert d["date_to"] == "20250201"
        assert d["tag"] == "good_run"
        assert d["note_query"] == "boss"
        assert len(d["param_conditions"]) == 1

    def test_to_markdown(self, log_dir, two_sessions):
        ss = SessionSearch(log_dir=log_dir)
        results = ss.search()
        md = ss.to_markdown(results)
        assert "Session Search Results" in md
        assert "2 sessions" in md
        assert "20250101_120000" in md

    def test_to_markdown_empty(self, log_dir):
        ss = SessionSearch(log_dir=log_dir)
        md = ss.to_markdown([])
        assert "0 sessions" in md
        assert "No sessions matched" in md

    def test_empty_log_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        ss = SessionSearch(log_dir=empty)
        assert ss.search() == []


# ---------------------------------------------------------------------------
# TestSessionSearchCLI
# ---------------------------------------------------------------------------

class TestSessionSearchCLI:
    def _run_cli(self, *args):
        cmd = [sys.executable, str(PROJECT_ROOT / "session_search.py")] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_cli_search(self, log_dir, two_sessions):
        result = self._run_cli("search", "--log-dir", str(log_dir))
        assert result.returncode == 0
        assert "Session Search Results" in result.stdout

    def test_cli_search_json(self, log_dir, two_sessions):
        result = self._run_cli("search", "--log-dir", str(log_dir), "--format", "json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["count"] == 2
        assert len(data["sessions"]) == 2

    def test_cli_search_with_param(self, log_dir, two_sessions):
        result = self._run_cli(
            "search", "--log-dir", str(log_dir),
            "--param", "gold last > 3000",
        )
        assert result.returncode == 0
        assert "1 sessions" in result.stdout

    def test_cli_no_command(self):
        result = self._run_cli()
        assert result.returncode != 0
