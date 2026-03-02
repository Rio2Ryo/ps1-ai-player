"""Tests for session_replay.py — SessionData, SessionTimeline, SessionComparator, CLI."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from session_replay import (
    ActionAnalyzer,
    SessionComparator,
    SessionData,
    SessionTimeline,
    main as cli_main,
)


# ---------------------------------------------------------------------------
# Helpers — create synthetic session artifacts
# ---------------------------------------------------------------------------

def _write_session_files(
    directory: Path,
    game_id: str = "DEMO",
    timestamp: str = "20250101_120000",
    num_steps: int = 20,
    *,
    session_info: dict | None = None,
    history: list[dict] | None = None,
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
            100 - i, 50 + i * 2, 200 + i * 10,
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
             "observations": f"obs_{i}", "parameters": {"hp": 100 - i}}
            for i in range(min(10, num_steps))
        ]
    history_path.write_text(json.dumps(history))

    return csv_path


# ---------------------------------------------------------------------------
# TestSessionData
# ---------------------------------------------------------------------------

class TestSessionData:
    def test_from_log_path(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        s = SessionData.from_log_path(csv_path)
        assert s.game_id == "DEMO"
        assert s.timestamp == "20250101_120000"
        assert s.total_steps == 20
        assert isinstance(s.df, pd.DataFrame)

    def test_from_log_path_missing_csv(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            SessionData.from_log_path(tmp_path / "nonexistent.csv")

    def test_from_log_path_bad_filename(self, tmp_path: Path) -> None:
        bad = tmp_path / "random_file.csv"
        bad.write_text("a,b\n1,2\n")
        with pytest.raises(ValueError, match="does not match"):
            SessionData.from_log_path(bad)

    def test_from_log_path_missing_sidecars(self, tmp_path: Path) -> None:
        """CSV exists but .session.json / .history.json do not."""
        csv_path = _write_session_files(tmp_path)
        # Remove sidecars
        csv_path.with_suffix(".session.json").unlink()
        csv_path.with_suffix(".history.json").unlink()
        s = SessionData.from_log_path(csv_path)
        assert s.session_info == {}
        assert s.history == []

    def test_properties(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        s = SessionData.from_log_path(csv_path)
        assert s.total_steps == 20
        assert s.duration_seconds == pytest.approx(95.0)  # 19 * 5
        assert s.cost_usd == pytest.approx(0.1234)
        assert set(s.parameters) == {"hp", "mp", "gold"}

    def test_cost_usd_missing(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, session_info={})
        s = SessionData.from_log_path(csv_path)
        assert s.cost_usd == 0.0

    def test_duration_single_row(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=1)
        s = SessionData.from_log_path(csv_path)
        assert s.duration_seconds == 0.0

    def test_discover_sessions(self, tmp_path: Path) -> None:
        _write_session_files(tmp_path, game_id="GAME1", timestamp="20250101_120000")
        _write_session_files(tmp_path, game_id="GAME2", timestamp="20250102_120000")
        _write_session_files(tmp_path, game_id="GAME1", timestamp="20250103_120000")

        all_sessions = SessionData.discover_sessions(tmp_path)
        assert len(all_sessions) == 3
        # Sorted by timestamp
        assert all_sessions[0].timestamp == "20250101_120000"
        assert all_sessions[2].timestamp == "20250103_120000"

    def test_discover_sessions_filter_game(self, tmp_path: Path) -> None:
        _write_session_files(tmp_path, game_id="GAME1", timestamp="20250101_120000")
        _write_session_files(tmp_path, game_id="GAME2", timestamp="20250102_120000")

        filtered = SessionData.discover_sessions(tmp_path, game_id="GAME1")
        assert len(filtered) == 1
        assert filtered[0].game_id == "GAME1"

    def test_discover_sessions_empty_dir(self, tmp_path: Path) -> None:
        assert SessionData.discover_sessions(tmp_path) == []

    def test_discover_sessions_nonexistent_dir(self) -> None:
        assert SessionData.discover_sessions("/nonexistent/dir") == []


# ---------------------------------------------------------------------------
# TestSessionTimeline
# ---------------------------------------------------------------------------

class TestSessionTimeline:
    def test_get_step(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        s = SessionData.from_log_path(csv_path)
        tl = SessionTimeline(s)
        step = tl.get_step(5)
        assert step["step"] == 5
        assert step["action"] == "action_2"
        assert step["hp"] == 95

    def test_get_step_missing(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=5)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        with pytest.raises(KeyError, match="Step 99"):
            tl.get_step(99)

    def test_get_range(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        df = tl.get_range(5, 10)
        assert len(df) == 6
        assert list(df["step"]) == [5, 6, 7, 8, 9, 10]

    def test_parameter_at_step(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        assert tl.parameter_at_step("hp", 0) == 100.0
        assert tl.parameter_at_step("gold", 3) == 230.0

    def test_parameter_at_step_missing_param(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        with pytest.raises(KeyError, match="no_such_param"):
            tl.parameter_at_step("no_such_param", 0)

    def test_find_events_lt(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        # hp = 100 - step, so hp < 85 means step > 15 -> steps 16..19
        steps = tl.find_events("hp", "< 85")
        assert steps == [16, 17, 18, 19]

    def test_find_events_eq(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        steps = tl.find_events("hp", "== 90")
        assert steps == [10]

    def test_find_events_invalid_condition(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        with pytest.raises(ValueError, match="Invalid condition"):
            tl.find_events("hp", "is bad")

    def test_find_events_missing_param(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        with pytest.raises(KeyError, match="nope"):
            tl.find_events("nope", "< 100")

    def test_format_step(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        text = tl.format_step(0)
        assert "Step 0" in text
        assert "action_0" in text
        assert "reason_0" in text
        assert "hp=" in text

    def test_format_timeline(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=5)
        tl = SessionTimeline(SessionData.from_log_path(csv_path))
        text = tl.format_timeline(start=1, end=3)
        assert "Step 1" in text
        assert "Step 3" in text
        assert "Step 0" not in text
        assert "Step 4" not in text


# ---------------------------------------------------------------------------
# TestSessionComparator
# ---------------------------------------------------------------------------

class TestSessionComparator:
    def _make_two_sessions(self, tmp_path: Path) -> list[SessionData]:
        p1 = _write_session_files(
            tmp_path, game_id="DEMO", timestamp="20250101_120000",
            num_steps=20,
            session_info={
                "cost": {"total_cost_usd": 0.10},
                "strategy": {"current": "balanced", "switch_count": 0},
            },
        )
        p2 = _write_session_files(
            tmp_path, game_id="DEMO", timestamp="20250102_120000",
            num_steps=30,
            session_info={
                "cost": {"total_cost_usd": 0.20},
                "strategy": {"current": "aggressive", "switch_count": 2},
            },
        )
        return [SessionData.from_log_path(p1), SessionData.from_log_path(p2)]

    def test_requires_two_sessions(self, tmp_path: Path) -> None:
        p1 = _write_session_files(tmp_path)
        s1 = SessionData.from_log_path(p1)
        with pytest.raises(ValueError, match="at least 2"):
            SessionComparator([s1])

    def test_compare_summary(self, tmp_path: Path) -> None:
        sessions = self._make_two_sessions(tmp_path)
        comp = SessionComparator(sessions)
        df = comp.compare_summary()
        assert len(df) == 2
        assert df.iloc[0]["steps"] == 20
        assert df.iloc[1]["steps"] == 30
        assert "hp_mean" in df.columns

    def test_compare_parameters(self, tmp_path: Path) -> None:
        sessions = self._make_two_sessions(tmp_path)
        comp = SessionComparator(sessions)
        stats = comp.compare_parameters("hp")
        assert len(stats) == 2
        for ts, s in stats.items():
            assert "mean" in s
            assert "min" in s
            assert "max" in s
            assert "std" in s

    def test_diff_strategies(self, tmp_path: Path) -> None:
        sessions = self._make_two_sessions(tmp_path)
        comp = SessionComparator(sessions)
        diffs = comp.diff_strategies()
        assert len(diffs) == 2
        assert diffs[0]["strategy"]["current"] == "balanced"
        assert diffs[1]["strategy"]["current"] == "aggressive"

    def test_to_markdown(self, tmp_path: Path) -> None:
        sessions = self._make_two_sessions(tmp_path)
        comp = SessionComparator(sessions)
        md = comp.to_markdown()
        assert "# Session Comparison Report" in md
        assert "## Summary" in md
        assert "## Parameter Comparison" in md
        assert "## Strategy Differences" in md
        assert "balanced" in md
        assert "aggressive" in md


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_list_sessions(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _write_session_files(tmp_path, game_id="TESTGAME", timestamp="20250101_120000")
        cli_main(["list", "--log-dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert "TESTGAME" in out
        assert "20250101_120000" in out

    def test_list_empty(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        cli_main(["list", "--log-dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert "No sessions found" in out

    def test_show(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path)
        cli_main(["show", str(csv_path)])
        out = capsys.readouterr().out
        assert "DEMO" in out
        assert "Steps:" in out

    def test_timeline(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=10)
        cli_main(["timeline", str(csv_path), "--start", "2", "--end", "4"])
        out = capsys.readouterr().out
        assert "Step 2" in out
        assert "Step 4" in out

    def test_compare(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        p1 = _write_session_files(tmp_path, timestamp="20250101_120000")
        p2 = _write_session_files(tmp_path, timestamp="20250102_120000")
        cli_main(["compare", str(p1), str(p2)])
        out = capsys.readouterr().out
        assert "Session Comparison Report" in out

    def test_events(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        cli_main(["events", str(csv_path), "--param", "hp", "--condition", "< 85"])
        out = capsys.readouterr().out
        assert "4 step(s)" in out

    def test_events_none_found(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=5)
        cli_main(["events", str(csv_path), "--param", "hp", "--condition", "< 0"])
        out = capsys.readouterr().out
        assert "No events found" in out

    def test_no_command(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit):
            cli_main([])


# ---------------------------------------------------------------------------
# TestActionAnalyzer
# ---------------------------------------------------------------------------

class TestActionAnalyzer:
    def test_action_frequency(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        freq = analyzer.action_frequency()
        # actions cycle action_0, action_1, action_2 for 20 steps
        assert freq["action_0"] == 7  # steps 0,3,6,9,12,15,18
        assert freq["action_1"] == 7  # steps 1,4,7,10,13,16,19
        assert freq["action_2"] == 6  # steps 2,5,8,11,14,17

    def test_action_frequency_empty(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=0)
        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        freq = analyzer.action_frequency()
        assert freq == {}

    def test_action_transitions(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=6)
        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        trans = analyzer.action_transitions()
        # sequence: a0, a1, a2, a0, a1, a2
        assert trans["action_0"]["action_1"] == 2
        assert trans["action_1"]["action_2"] == 2
        assert trans["action_2"]["action_0"] == 1

    def test_action_transitions_single_step(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=1)
        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        assert analyzer.action_transitions() == {}

    def test_action_parameter_impact(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        impact = analyzer.action_parameter_impact("hp")
        # hp decreases by 1 each step, so mean_delta should be -1.0 for all
        for act in ("action_0", "action_1", "action_2"):
            assert act in impact
            assert impact[act]["mean_delta"] == pytest.approx(-1.0)
            assert impact[act]["median_delta"] == pytest.approx(-1.0)

    def test_action_parameter_impact_missing_param(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        with pytest.raises(KeyError, match="no_such"):
            analyzer.action_parameter_impact("no_such")

    def test_action_streaks(self, tmp_path: Path) -> None:
        """Build a CSV with a known action streak."""
        stem = "20250101_120000_DEMO_agent"
        csv_path = tmp_path / f"{stem}.csv"
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        # Create streak: 5 x "observe" then 3 x "attack"
        actions = ["observe"] * 5 + ["attack"] * 3
        rows = []
        for i, act in enumerate(actions):
            ts = base_time + timedelta(seconds=i * 5)
            rows.append([ts.isoformat(), i, act, "r", "o", 100 - i, 50 + i, 200])
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "step", "action", "reasoning",
                             "observations", "hp", "mp", "gold"])
            writer.writerows(rows)
        (tmp_path / f"{stem}.session.json").write_text("{}")
        (tmp_path / f"{stem}.history.json").write_text("[]")

        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        streaks = analyzer.action_streaks()
        assert len(streaks) == 2
        # Sorted by length descending
        assert streaks[0]["action"] == "observe"
        assert streaks[0]["length"] == 5
        assert streaks[0]["start_step"] == 0
        assert streaks[0]["end_step"] == 4
        assert streaks[1]["action"] == "attack"
        assert streaks[1]["length"] == 3

    def test_action_streaks_no_streak(self, tmp_path: Path) -> None:
        """Alternating actions — no streak of length >= 2."""
        stem = "20250101_120000_DEMO_agent"
        csv_path = tmp_path / f"{stem}.csv"
        base_time = datetime(2025, 1, 1, 12, 0, 0)
        actions = ["a", "b", "a", "b"]
        rows = []
        for i, act in enumerate(actions):
            ts = base_time + timedelta(seconds=i * 5)
            rows.append([ts.isoformat(), i, act, "r", "o", 100, 50, 200])
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "step", "action", "reasoning",
                             "observations", "hp", "mp", "gold"])
            writer.writerows(rows)
        (tmp_path / f"{stem}.session.json").write_text("{}")
        (tmp_path / f"{stem}.history.json").write_text("[]")

        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        assert analyzer.action_streaks() == []

    def test_format_report(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        report = analyzer.format_report()
        assert "# Action Analysis Report" in report
        assert "## Action Frequency" in report
        assert "action_0" in report
        assert "## Action Transitions" in report
        assert "## Action-Parameter Impact" in report

    def test_format_report_empty_session(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=0)
        s = SessionData.from_log_path(csv_path)
        analyzer = ActionAnalyzer(s)
        report = analyzer.format_report()
        assert "No actions found" in report


# ---------------------------------------------------------------------------
# TestGetStepEnriched
# ---------------------------------------------------------------------------

class TestGetStepEnriched:
    def test_enriched_with_history(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        s = SessionData.from_log_path(csv_path)
        tl = SessionTimeline(s)
        info = tl.get_step_enriched(3)
        assert info["step"] == 3
        # History has multi-action list for steps 0-9
        assert "actions" in info
        assert isinstance(info["actions"], list)
        assert "history_parameters" in info

    def test_enriched_without_history(self, tmp_path: Path) -> None:
        """Steps beyond history range fall back to CSV action."""
        csv_path = _write_session_files(tmp_path, num_steps=20)
        s = SessionData.from_log_path(csv_path)
        tl = SessionTimeline(s)
        # History only covers steps 0-9
        info = tl.get_step_enriched(15)
        assert info["step"] == 15
        assert "actions" not in info
        assert info["action"] == "action_0"

    def test_enriched_no_history_file(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=5, history=[])
        s = SessionData.from_log_path(csv_path)
        tl = SessionTimeline(s)
        info = tl.get_step_enriched(0)
        assert info["step"] == 0
        assert "actions" not in info


# ---------------------------------------------------------------------------
# TestComparatorActions
# ---------------------------------------------------------------------------

class TestComparatorActions:
    def _make_two_sessions(self, tmp_path: Path) -> list[SessionData]:
        p1 = _write_session_files(
            tmp_path, game_id="DEMO", timestamp="20250101_120000",
            num_steps=20,
            session_info={"cost": {"total_cost_usd": 0.10}, "strategy": {}},
        )
        p2 = _write_session_files(
            tmp_path, game_id="DEMO", timestamp="20250102_120000",
            num_steps=30,
            session_info={"cost": {"total_cost_usd": 0.20}, "strategy": {}},
        )
        return [SessionData.from_log_path(p1), SessionData.from_log_path(p2)]

    def test_compare_actions(self, tmp_path: Path) -> None:
        sessions = self._make_two_sessions(tmp_path)
        comp = SessionComparator(sessions)
        df = comp.compare_actions()
        assert not df.empty
        assert "action" in df.columns
        assert "20250101_120000_count" in df.columns
        assert "20250102_120000_pct" in df.columns
        # All 3 actions present
        actions = set(df["action"])
        assert actions == {"action_0", "action_1", "action_2"}

    def test_compare_action_transitions(self, tmp_path: Path) -> None:
        sessions = self._make_two_sessions(tmp_path)
        comp = SessionComparator(sessions)
        result = comp.compare_action_transitions()
        assert "20250101_120000" in result
        assert "20250102_120000" in result
        # Each should have transition data
        for ts, trans in result.items():
            assert "action_0" in trans

    def test_to_markdown_includes_actions(self, tmp_path: Path) -> None:
        sessions = self._make_two_sessions(tmp_path)
        comp = SessionComparator(sessions)
        md = comp.to_markdown()
        assert "## Action Comparison" in md


# ---------------------------------------------------------------------------
# TestReplayCLI
# ---------------------------------------------------------------------------

class TestReplayCLI:
    def test_replay_full_report(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        cli_main(["replay", str(csv_path)])
        out = capsys.readouterr().out
        assert "Action Analysis Report" in out
        assert "Action Frequency" in out

    def test_replay_actions_only(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        cli_main(["replay", str(csv_path), "--actions"])
        out = capsys.readouterr().out
        assert "action_0" in out
        assert "Count" in out

    def test_replay_step(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path, num_steps=20)
        cli_main(["replay", str(csv_path), "--step", "3"])
        out = capsys.readouterr().out
        assert "Step 3 (enriched)" in out
        assert "Actions:" in out  # history exists for step 3
