"""Tests for replay_diff.py — StepDiff, ParamDelta, ReplayDiff, CLI."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from replay_diff import (
    ParamDelta,
    ReplayDiff,
    StepDiff,
    main as cli_main,
)
from session_replay import SessionData


# ---------------------------------------------------------------------------
# Helpers — create two synthetic sessions with controlled differences
# ---------------------------------------------------------------------------

def _write_session_files(
    directory: Path,
    game_id: str = "DEMO",
    timestamp: str = "20250101_120000",
    num_steps: int = 10,
    *,
    actions: list[str] | None = None,
    hp_values: list[int] | None = None,
    mp_values: list[int] | None = None,
    gold_values: list[int] | None = None,
) -> Path:
    """Create CSV + .session.json + .history.json and return CSV path."""
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = directory / f"{stem}.csv"
    session_path = directory / f"{stem}.session.json"
    history_path = directory / f"{stem}.history.json"

    if actions is None:
        actions = [f"action_{i % 3}" for i in range(num_steps)]
    if hp_values is None:
        hp_values = [100 - i for i in range(num_steps)]
    if mp_values is None:
        mp_values = [50 + i * 2 for i in range(num_steps)]
    if gold_values is None:
        gold_values = [200 + i * 10 for i in range(num_steps)]

    base_time = datetime(2025, 1, 1, 12, 0, 0)
    rows: list[list] = []
    for i in range(num_steps):
        ts = base_time + timedelta(seconds=i * 5)
        rows.append([
            ts.isoformat(), i, actions[i],
            f"reason_{i}", f"obs_{i}",
            hp_values[i], mp_values[i], gold_values[i],
        ])
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning", "observations",
                         "hp", "mp", "gold"])
        writer.writerows(rows)

    session_path.write_text(json.dumps({
        "cost": {"total_cost_usd": 0.1234},
        "strategy": {"current": "balanced"},
        "total_steps": num_steps,
    }))
    history_path.write_text(json.dumps([]))

    return csv_path


def _make_two_sessions(tmp_path: Path) -> tuple[SessionData, SessionData]:
    """Create two sessions with controlled differences for testing."""
    # Session A: standard sequence
    csv_a = _write_session_files(
        tmp_path,
        timestamp="20250101_120000",
        actions=["attack", "defend", "attack", "heal", "attack",
                 "defend", "heal", "attack", "defend", "attack"],
        hp_values=[100, 95, 90, 95, 85, 80, 90, 80, 75, 70],
        mp_values=[50, 48, 46, 40, 44, 42, 36, 40, 38, 36],
        gold_values=[200, 210, 230, 230, 250, 250, 250, 270, 270, 290],
    )
    # Session B: different actions at steps 2, 5, 7
    b_dir = tmp_path / "b"
    b_dir.mkdir(exist_ok=True)
    csv_b = _write_session_files(
        b_dir,
        timestamp="20250101_130000",
        actions=["attack", "defend", "heal", "heal", "attack",
                 "attack", "heal", "defend", "defend", "attack"],
        hp_values=[100, 95, 98, 100, 90, 85, 95, 88, 83, 78],
        mp_values=[50, 48, 42, 36, 40, 38, 32, 36, 34, 32],
        gold_values=[200, 210, 210, 210, 230, 250, 250, 250, 250, 270],
    )

    session_a = SessionData.from_log_path(csv_a)
    session_b = SessionData.from_log_path(csv_b)
    return session_a, session_b


# ---------------------------------------------------------------------------
# TestStepDiff
# ---------------------------------------------------------------------------

class TestStepDiff:
    def test_to_dict(self) -> None:
        pd1 = ParamDelta(value_a=100.0, value_b=95.0, diff=-5.0, pct_diff=-5.0)
        sd = StepDiff(
            step=0,
            action_a="attack",
            action_b="defend",
            action_diverged=True,
            param_deltas={"hp": pd1},
        )
        d = sd.to_dict()
        assert d["step"] == 0
        assert d["action_a"] == "attack"
        assert d["action_b"] == "defend"
        assert d["action_diverged"] is True
        assert "hp" in d["param_deltas"]
        assert d["param_deltas"]["hp"]["diff"] == -5.0


# ---------------------------------------------------------------------------
# TestParamDelta
# ---------------------------------------------------------------------------

class TestParamDelta:
    def test_to_dict(self) -> None:
        pd1 = ParamDelta(value_a=100.0, value_b=110.0, diff=10.0, pct_diff=10.0)
        d = pd1.to_dict()
        assert d["value_a"] == 100.0
        assert d["value_b"] == 110.0
        assert d["diff"] == 10.0
        assert d["pct_diff"] == 10.0

    def test_none_values(self) -> None:
        pd1 = ParamDelta(value_a=None, value_b=50.0, diff=None, pct_diff=None)
        d = pd1.to_dict()
        assert d["value_a"] is None
        assert d["diff"] is None
        assert d["pct_diff"] is None


# ---------------------------------------------------------------------------
# TestReplayDiff
# ---------------------------------------------------------------------------

class TestReplayDiff:
    def test_requires_two_sessions(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        assert differ.session_a is sa
        assert differ.session_b is sb

    def test_step_diffs_length(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        diffs = differ.step_diffs()
        # Both sessions have 10 steps (0-9), union should be 10
        assert len(diffs) == 10

    def test_step_diffs_common_steps(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        diffs = differ.step_diffs()
        # All 10 steps should have both actions present
        for sd in diffs:
            assert sd.action_a is not None
            assert sd.action_b is not None

    def test_step_diffs_action_diverged(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        diffs = differ.step_diffs()
        # Steps 2, 5, 7 have different actions
        diverged_steps = [sd.step for sd in diffs if sd.action_diverged]
        assert 2 in diverged_steps
        assert 5 in diverged_steps
        assert 7 in diverged_steps

    def test_step_diffs_unequal_lengths(self, tmp_path: Path) -> None:
        csv_a = _write_session_files(tmp_path, num_steps=10, timestamp="20250101_120000")
        sub = tmp_path / "short"
        sub.mkdir()
        csv_b = _write_session_files(sub, num_steps=5, timestamp="20250101_130000")
        sa = SessionData.from_log_path(csv_a)
        sb = SessionData.from_log_path(csv_b)
        differ = ReplayDiff(sa, sb)
        diffs = differ.step_diffs()
        assert len(diffs) == 10  # union of 0-9 and 0-4
        # Steps 5-9 should have action_b as None
        for sd in diffs:
            if sd.step >= 5:
                assert sd.action_b is None

    def test_divergence_points(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        div_pts = differ.divergence_points()
        assert len(div_pts) == 3  # steps 2, 5, 7

    def test_divergence_points_identical(self, tmp_path: Path) -> None:
        csv_a = _write_session_files(tmp_path, timestamp="20250101_120000")
        sub = tmp_path / "same"
        sub.mkdir()
        csv_b = _write_session_files(sub, timestamp="20250101_130000")
        sa = SessionData.from_log_path(csv_a)
        sb = SessionData.from_log_path(csv_b)
        differ = ReplayDiff(sa, sb)
        assert differ.divergence_points() == []

    def test_param_comparison(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        pc = differ.param_comparison("hp")
        assert isinstance(pc, pd.DataFrame)
        assert "step" in pc.columns
        assert "hp_a" in pc.columns
        assert "hp_b" in pc.columns
        assert "diff" in pc.columns
        assert "pct_diff" in pc.columns
        assert len(pc) == 10

    def test_param_comparison_diff_values(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        pc = differ.param_comparison("hp")
        # At step 0, both have hp=100, diff should be 0
        row0 = pc[pc["step"] == 0].iloc[0]
        assert row0["hp_a"] == 100.0
        assert row0["hp_b"] == 100.0
        assert row0["diff"] == 0.0

    def test_param_comparison_missing_param(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        with pytest.raises(KeyError, match="not found"):
            differ.param_comparison("nonexistent_param")

    def test_summary(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        s = differ.summary()
        assert "session_a" in s
        assert "session_b" in s
        assert "total_steps_a" in s
        assert "total_steps_b" in s
        assert "common_steps" in s
        assert "divergence_count" in s
        assert "divergence_rate" in s
        assert "param_diffs" in s

    def test_summary_divergence_rate(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        s = differ.summary()
        assert s["common_steps"] == 10
        assert s["divergence_count"] == 3
        assert s["divergence_rate"] == 0.3

    def test_summary_param_diffs(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        s = differ.summary()
        assert "hp" in s["param_diffs"]
        assert isinstance(s["param_diffs"]["hp"], float)
        assert s["param_diffs"]["hp"] > 0

    def test_to_markdown(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        md = differ.to_markdown()
        assert "# Session Diff Report" in md
        assert "## Summary" in md
        assert "## Divergence Points" in md
        assert "## Parameter Comparison" in md

    def test_to_markdown_divergence_table(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        md = differ.to_markdown()
        # Should contain action names from divergence points
        assert "attack" in md
        assert "heal" in md or "defend" in md

    def test_to_dict(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        d = differ.to_dict()
        assert "summary" in d
        assert "step_diffs" in d
        assert "divergence_points" in d

    def test_to_dict_json_serializable(self, tmp_path: Path) -> None:
        sa, sb = _make_two_sessions(tmp_path)
        differ = ReplayDiff(sa, sb)
        d = differ.to_dict()
        # Should not raise
        output = json.dumps(d)
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert parsed["summary"]["divergence_count"] == 3


# ---------------------------------------------------------------------------
# TestReplayDiffCLI
# ---------------------------------------------------------------------------

class TestReplayDiffCLI:
    def test_cli_diff_markdown(self, tmp_path: Path, capsys) -> None:
        csv_a = _write_session_files(tmp_path, timestamp="20250101_120000")
        sub = tmp_path / "b"
        sub.mkdir()
        csv_b = _write_session_files(sub, timestamp="20250101_130000")
        cli_main(["diff", str(csv_a), str(csv_b)])
        captured = capsys.readouterr()
        assert "Session Diff Report" in captured.out

    def test_cli_diff_json(self, tmp_path: Path, capsys) -> None:
        csv_a = _write_session_files(tmp_path, timestamp="20250101_120000")
        sub = tmp_path / "b"
        sub.mkdir()
        csv_b = _write_session_files(sub, timestamp="20250101_130000")
        cli_main(["diff", str(csv_a), str(csv_b), "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "summary" in data
        assert "step_diffs" in data

    def test_cli_diff_output_file(self, tmp_path: Path) -> None:
        csv_a = _write_session_files(tmp_path, timestamp="20250101_120000")
        sub = tmp_path / "b"
        sub.mkdir()
        csv_b = _write_session_files(sub, timestamp="20250101_130000")
        out = tmp_path / "report.md"
        cli_main(["diff", str(csv_a), str(csv_b), "--output", str(out)])
        assert out.exists()
        content = out.read_text()
        assert "Session Diff Report" in content

    def test_cli_diff_param_filter(self, tmp_path: Path, capsys) -> None:
        csv_a = _write_session_files(tmp_path, timestamp="20250101_120000")
        sub = tmp_path / "b"
        sub.mkdir()
        csv_b = _write_session_files(sub, timestamp="20250101_130000")
        cli_main(["diff", str(csv_a), str(csv_b), "--param", "hp"])
        captured = capsys.readouterr()
        assert "hp" in captured.out

    def test_cli_no_command(self) -> None:
        with pytest.raises(SystemExit):
            cli_main([])

    def test_cli_missing_csv(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            cli_main(["diff", str(tmp_path / "nope_a.csv"), str(tmp_path / "nope_b.csv")])
