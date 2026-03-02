"""Tests for cross_session_analyzer.py — CrossSessionAnalyzer + CLI."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cross_session_analyzer import CrossSessionAnalyzer, main as cli_main
from session_replay import SessionData


# ---------------------------------------------------------------------------
# Helpers — create synthetic multi-session datasets
# ---------------------------------------------------------------------------

def _write_session_files(
    directory: Path,
    game_id: str = "DEMO",
    timestamp: str = "20250101_120000",
    num_steps: int = 20,
    *,
    session_info: dict | None = None,
    history: list[dict] | None = None,
    hp_base: int = 100,
    gold_base: int = 200,
) -> Path:
    """Create CSV + .session.json + .history.json and return CSV path."""
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = directory / f"{stem}.csv"
    session_path = directory / f"{stem}.session.json"
    history_path = directory / f"{stem}.history.json"

    base_time = datetime(2025, 1, 1, 12, 0, 0)
    rows: list[list] = []
    for i in range(num_steps):
        ts = base_time + timedelta(seconds=i * 5)
        rows.append([
            ts.isoformat(), i, f"action_{i % 3}",
            f"reason_{i}", f"obs_{i}",
            hp_base - i, 50 + i * 2, gold_base + i * 10,
        ])
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning", "observations",
                         "hp", "mp", "gold"])
        writer.writerows(rows)

    if session_info is None:
        session_info = {
            "cost": {"total_cost_usd": 0.1234, "api_calls": num_steps},
            "game_state": {"transitions": 3},
            "strategy": {"current": "balanced", "switch_count": 1},
            "total_steps": num_steps,
        }
    session_path.write_text(json.dumps(session_info))

    if history is None:
        history = [
            {"step": i, "action": [f"action_{i % 3}"], "reasoning": f"reason_{i}",
             "observations": f"obs_{i}", "parameters": {"hp": hp_base - i}}
            for i in range(min(10, num_steps))
        ]
    history_path.write_text(json.dumps(history))

    return csv_path


def _make_sessions(tmp_path: Path, count: int = 4) -> list[SessionData]:
    """Create N sessions with progressive improvement + varied strategies."""
    strategies = ["balanced", "aggressive", "balanced", "defensive"]
    paths = []
    for i in range(count):
        ts = f"2025010{i + 1}_120000"
        si = {
            "cost": {"total_cost_usd": 0.05 * (i + 1)},
            "strategy": {"current": strategies[i % len(strategies)]},
        }
        # hp improves across sessions (base goes up); gold also improves
        p = _write_session_files(
            tmp_path,
            game_id="DEMO",
            timestamp=ts,
            num_steps=20 + i * 5,
            session_info=si,
            hp_base=80 + i * 5,   # 80, 85, 90, 95
            gold_base=200 + i * 50,  # 200, 250, 300, 350
        )
        paths.append(p)
    return [SessionData.from_log_path(p) for p in paths]


# ---------------------------------------------------------------------------
# TestCrossSessionAnalyzer
# ---------------------------------------------------------------------------

class TestCrossSessionAnalyzer:
    def test_requires_sessions(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            CrossSessionAnalyzer([])

    def test_merged_df(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        analyzer = CrossSessionAnalyzer(sessions)
        merged = analyzer.merged_df()
        # Total rows = sum of all session steps
        expected_rows = sum(s.total_steps for s in sessions)
        assert len(merged) == expected_rows
        assert "session_id" in merged.columns

    def test_merged_df_preserves_columns(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=2)
        analyzer = CrossSessionAnalyzer(sessions)
        merged = analyzer.merged_df()
        assert "hp" in merged.columns
        assert "mp" in merged.columns
        assert "gold" in merged.columns

    def test_parameter_evolution(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        analyzer = CrossSessionAnalyzer(sessions)
        evol = analyzer.parameter_evolution()
        assert "hp" in evol
        assert len(evol["hp"]) == 3
        # Chronologically ordered
        assert evol["hp"][0]["session"] < evol["hp"][1]["session"]
        # Each entry has required keys
        for entry in evol["hp"]:
            assert "mean" in entry
            assert "min" in entry
            assert "max" in entry
            assert "first" in entry
            assert "last" in entry
            assert "trend" in entry

    def test_parameter_evolution_trend(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=4)
        analyzer = CrossSessionAnalyzer(sessions)
        evol = analyzer.parameter_evolution()
        # hp_base increases across sessions (80, 85, 90, 95) so means rise
        # First entry is baseline
        assert evol["hp"][0]["trend"] == "baseline"
        # Subsequent entries should be rising (since hp_base increases by 5)
        for entry in evol["hp"][1:]:
            assert entry["trend"] == "rising"

    def test_strategy_effectiveness(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=4)
        analyzer = CrossSessionAnalyzer(sessions)
        df = analyzer.strategy_effectiveness()
        assert "strategy" in df.columns
        assert "sessions" in df.columns
        assert "avg_steps" in df.columns
        # 3 strategies: balanced(2), aggressive(1), defensive(1)
        assert len(df) == 3
        assert set(df["strategy"]) == {"balanced", "aggressive", "defensive"}

    def test_strategy_effectiveness_single(self, tmp_path: Path) -> None:
        """Works with only one strategy across all sessions."""
        paths = []
        for i in range(3):
            ts = f"2025010{i + 1}_120000"
            si = {
                "cost": {"total_cost_usd": 0.05},
                "strategy": {"current": "balanced"},
            }
            p = _write_session_files(
                tmp_path, game_id="DEMO", timestamp=ts,
                num_steps=20, session_info=si,
            )
            paths.append(p)
        sessions = [SessionData.from_log_path(p) for p in paths]
        analyzer = CrossSessionAnalyzer(sessions)
        df = analyzer.strategy_effectiveness()
        assert len(df) == 1
        assert df.iloc[0]["strategy"] == "balanced"
        assert df.iloc[0]["sessions"] == 3

    def test_action_effectiveness(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        analyzer = CrossSessionAnalyzer(sessions)
        df = analyzer.action_effectiveness("hp")
        assert "action" in df.columns
        assert "mean_delta" in df.columns
        assert "median_delta" in df.columns
        assert "count" in df.columns
        # All actions should have hp delta of -1.0 (hp decreases by 1 each step)
        for _, row in df.iterrows():
            assert row["mean_delta"] == pytest.approx(-1.0)

    def test_action_effectiveness_missing(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=2)
        analyzer = CrossSessionAnalyzer(sessions)
        with pytest.raises(KeyError, match="no_such_param"):
            analyzer.action_effectiveness("no_such_param")

    def test_session_progression(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=4)
        analyzer = CrossSessionAnalyzer(sessions)
        df = analyzer.session_progression()
        assert len(df) == 4
        # Ordered by timestamp
        assert list(df["session"]) == sorted(df["session"])
        assert "total_steps" in df.columns
        assert "game_id" in df.columns

    def test_session_progression_values(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=4)
        analyzer = CrossSessionAnalyzer(sessions)
        df = analyzer.session_progression()
        # First session: 20 steps, last session: 35 steps
        assert df.iloc[0]["total_steps"] == 20
        assert df.iloc[3]["total_steps"] == 35
        # hp_last should be present
        assert "hp_last" in df.columns

    def test_common_patterns(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        analyzer = CrossSessionAnalyzer(sessions)
        patterns = analyzer.common_patterns()
        assert "most_frequent_actions" in patterns
        assert "most_common_transitions" in patterns
        assert "longest_streaks" in patterns
        # Should have actions from all sessions
        freq = patterns["most_frequent_actions"]
        assert len(freq) > 0
        assert "action_0" in freq

    def test_common_patterns_empty_actions(self, tmp_path: Path) -> None:
        """Handles sessions with no action column gracefully."""
        # Create a session with 0 steps (no actions)
        p = _write_session_files(
            tmp_path, game_id="DEMO", timestamp="20250101_120000",
            num_steps=0,
            session_info={"cost": {"total_cost_usd": 0.01}, "strategy": {"current": "balanced"}},
        )
        sessions = [SessionData.from_log_path(p)]
        analyzer = CrossSessionAnalyzer(sessions)
        patterns = analyzer.common_patterns()
        assert patterns["most_frequent_actions"] == {}
        assert patterns["longest_streaks"] == []

    def test_recommendations(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=4)
        analyzer = CrossSessionAnalyzer(sessions)
        recs = analyzer.recommendations()
        assert isinstance(recs, list)
        assert len(recs) > 0
        for r in recs:
            assert isinstance(r, str)

    def test_recommendations_strategy_hint(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=4)
        analyzer = CrossSessionAnalyzer(sessions)
        recs = analyzer.recommendations()
        # Should mention at least one strategy by name
        combined = " ".join(recs)
        assert any(
            s in combined for s in ["balanced", "aggressive", "defensive"]
        )

    def test_to_markdown(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        analyzer = CrossSessionAnalyzer(sessions)
        md = analyzer.to_markdown()
        assert "# Cross-Session Analysis Report" in md
        assert "## Session Progression" in md
        assert "## Parameter Evolution" in md
        assert "## Strategy Effectiveness" in md
        assert "## Common Patterns" in md

    def test_to_dict(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        analyzer = CrossSessionAnalyzer(sessions)
        d = analyzer.to_dict()
        expected_keys = {
            "session_count", "sessions", "parameter_evolution",
            "strategy_effectiveness", "action_effectiveness",
            "session_progression", "common_patterns", "recommendations",
        }
        assert set(d.keys()) == expected_keys
        assert d["session_count"] == 3

    def test_to_dict_json_serializable(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        analyzer = CrossSessionAnalyzer(sessions)
        d = analyzer.to_dict()
        # Should not raise
        output = json.dumps(d, default=str)
        assert isinstance(output, str)
        # Round-trip parse
        parsed = json.loads(output)
        assert parsed["session_count"] == 3


# ---------------------------------------------------------------------------
# TestCrossSessionCLI
# ---------------------------------------------------------------------------

class TestCrossSessionCLI:
    def test_cli_analyze_markdown(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _make_sessions(tmp_path, count=3)
        cli_main(["analyze", "--log-dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert "Cross-Session Analysis Report" in out

    def test_cli_analyze_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _make_sessions(tmp_path, count=3)
        cli_main(["analyze", "--log-dir", str(tmp_path), "--format", "json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert "session_count" in parsed
        assert parsed["session_count"] == 3

    def test_cli_analyze_output_file(self, tmp_path: Path) -> None:
        _make_sessions(tmp_path, count=2)
        out_file = tmp_path / "report.md"
        cli_main([
            "analyze", "--log-dir", str(tmp_path),
            "--output", str(out_file),
        ])
        assert out_file.exists()
        content = out_file.read_text()
        assert "Cross-Session Analysis Report" in content

    def test_cli_no_sessions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        cli_main(["analyze", "--log-dir", str(empty_dir)])
        out = capsys.readouterr().out
        assert "No sessions found" in out

    def test_cli_no_command(self) -> None:
        with pytest.raises(SystemExit):
            cli_main([])
