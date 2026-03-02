"""Tests for strategy_optimizer.py — StrategyOptimizer + CLI."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from session_replay import SessionData
from strategy_optimizer import StrategyOptimizer, main as cli_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_session_files(
    directory: Path,
    game_id: str = "DEMO",
    timestamp: str = "20250101_120000",
    num_steps: int = 20,
    *,
    session_info: dict | None = None,
    hp_base: int = 100,
    gold_base: int = 200,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = directory / f"{stem}.csv"
    session_path = directory / f"{stem}.session.json"
    history_path = directory / f"{stem}.history.json"

    base_time = datetime(2025, 1, 1, 12, 0, 0)
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning",
                         "observations", "hp", "mp", "gold"])
        for i in range(num_steps):
            ts = base_time + timedelta(seconds=i * 5)
            writer.writerow([
                ts.isoformat(), i, f"action_{i % 3}",
                f"reason_{i}", f"obs_{i}",
                hp_base - i, 50 + i * 2, gold_base + i * 10,
            ])

    if session_info is None:
        session_info = {
            "cost": {"total_cost_usd": 0.05},
            "strategy": {"current": "balanced"},
        }
    session_path.write_text(json.dumps(session_info))
    history_path.write_text(json.dumps([]))
    return csv_path


def _make_sessions(tmp_path: Path, count: int = 4) -> list[SessionData]:
    strategies = ["balanced", "aggressive", "balanced", "defensive"]
    paths = []
    for i in range(count):
        ts = f"2025010{i + 1}_120000"
        si = {
            "cost": {"total_cost_usd": 0.05 * (i + 1)},
            "strategy": {"current": strategies[i % len(strategies)]},
        }
        p = _write_session_files(
            tmp_path, game_id="DEMO", timestamp=ts,
            num_steps=20 + i * 5, session_info=si,
            hp_base=80 + i * 5, gold_base=200 + i * 50,
        )
        paths.append(p)
    return [SessionData.from_log_path(p) for p in paths]


_SAMPLE_STRATEGY = {
    "genre": "rpg",
    "description": "Test RPG strategy",
    "thresholds": [
        {"parameter": "hp", "operator": "lt", "value": 30, "target_strategy": "defensive", "priority": 10},
        {"parameter": "hp", "operator": "gt", "value": 80, "target_strategy": "aggressive", "priority": 5},
        {"parameter": "gold", "operator": "gt", "value": 5000, "target_strategy": "equipment_upgrade", "priority": 6},
    ],
}


# ---------------------------------------------------------------------------
# TestStrategyOptimizer
# ---------------------------------------------------------------------------

class TestStrategyOptimizer:
    def test_requires_sessions(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            StrategyOptimizer(_SAMPLE_STRATEGY, [])

    def test_requires_thresholds(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=2)
        with pytest.raises(ValueError, match="thresholds"):
            StrategyOptimizer({"genre": "test"}, sessions)

    def test_tune_thresholds_returns_list(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        tuned = opt.tune_thresholds()
        assert isinstance(tuned, list)
        assert len(tuned) == len(_SAMPLE_STRATEGY["thresholds"])

    def test_tune_thresholds_adjusts_values(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        tuned = opt.tune_thresholds()
        orig_vals = {(t["parameter"], t["operator"]): t["value"]
                     for t in _SAMPLE_STRATEGY["thresholds"]}
        # At least one value should change
        changed = False
        for t in tuned:
            key = (t["parameter"], t["operator"])
            if key in orig_vals and t["value"] != orig_vals[key]:
                changed = True
                break
        assert changed

    def test_tune_thresholds_preserves_structure(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=2)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        tuned = opt.tune_thresholds()
        for t in tuned:
            assert "parameter" in t
            assert "operator" in t
            assert "value" in t
            assert "target_strategy" in t
            assert "priority" in t

    def test_rebalance_priorities(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=4)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        rebalanced = opt.rebalance_priorities()
        assert isinstance(rebalanced, list)
        for t in rebalanced:
            assert 1 <= t["priority"] <= 10

    def test_rebalance_no_crash_single_strategy(self, tmp_path: Path) -> None:
        """Works when all sessions use the same strategy."""
        paths = []
        for i in range(3):
            ts = f"2025010{i + 1}_120000"
            si = {"cost": {"total_cost_usd": 0.05}, "strategy": {"current": "balanced"}}
            p = _write_session_files(tmp_path, timestamp=ts, num_steps=20, session_info=si)
            paths.append(p)
        sessions = [SessionData.from_log_path(p) for p in paths]
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        rebalanced = opt.rebalance_priorities()
        assert isinstance(rebalanced, list)

    def test_suggest_new_thresholds(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        suggestions = opt.suggest_new_thresholds()
        assert isinstance(suggestions, list)
        # mp is not in original thresholds but has variation in data
        mp_suggestions = [s for s in suggestions if s["parameter"] == "mp"]
        assert len(mp_suggestions) >= 1

    def test_suggest_new_has_required_keys(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        suggestions = opt.suggest_new_thresholds()
        for s in suggestions:
            assert "parameter" in s
            assert "operator" in s
            assert "value" in s
            assert "target_strategy" in s

    def test_optimize_returns_valid_config(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        result = opt.optimize()
        assert "genre" in result
        assert "thresholds" in result
        assert "_optimization_notes" in result
        assert "_sessions_analyzed" in result
        assert result["_sessions_analyzed"] == 3

    def test_optimize_json_serializable(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        result = opt.optimize()
        output = json.dumps(result, default=str)
        parsed = json.loads(output)
        assert "thresholds" in parsed

    def test_optimize_does_not_mutate_original(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        original_copy = json.dumps(_SAMPLE_STRATEGY)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        opt.optimize()
        assert json.dumps(_SAMPLE_STRATEGY) == original_copy

    def test_diff_returns_strings(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        diff = opt.diff()
        assert isinstance(diff, list)
        assert len(diff) > 0
        for d in diff:
            assert isinstance(d, str)

    def test_to_markdown(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        md = opt.to_markdown()
        assert "# Strategy Optimisation Report" in md
        assert "rpg" in md
        assert "Sessions analyzed:" in md

    def test_to_markdown_contains_json(self, tmp_path: Path) -> None:
        sessions = _make_sessions(tmp_path, count=3)
        opt = StrategyOptimizer(_SAMPLE_STRATEGY, sessions)
        md = opt.to_markdown()
        assert "```json" in md
        assert '"thresholds"' in md


# ---------------------------------------------------------------------------
# TestStrategyOptimizerCLI
# ---------------------------------------------------------------------------

class TestStrategyOptimizerCLI:
    def _setup(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create sessions + strategy file, return (strategy_path, log_dir)."""
        log_dir = tmp_path / "logs"
        _make_sessions(log_dir, count=3)
        strat_path = tmp_path / "strategy.json"
        strat_path.write_text(json.dumps(_SAMPLE_STRATEGY))
        return strat_path, log_dir

    def test_cli_optimize_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        strat_path, log_dir = self._setup(tmp_path)
        cli_main(["optimize", str(strat_path), "--log-dir", str(log_dir)])
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert "thresholds" in parsed

    def test_cli_optimize_markdown(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        strat_path, log_dir = self._setup(tmp_path)
        cli_main([
            "optimize", str(strat_path),
            "--log-dir", str(log_dir), "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "Strategy Optimisation Report" in out

    def test_cli_optimize_output_file(self, tmp_path: Path) -> None:
        strat_path, log_dir = self._setup(tmp_path)
        out_file = tmp_path / "optimized.json"
        cli_main([
            "optimize", str(strat_path),
            "--log-dir", str(log_dir), "--output", str(out_file),
        ])
        assert out_file.exists()
        parsed = json.loads(out_file.read_text())
        assert "thresholds" in parsed

    def test_cli_no_sessions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        strat_path = tmp_path / "strategy.json"
        strat_path.write_text(json.dumps(_SAMPLE_STRATEGY))
        empty = tmp_path / "empty"
        empty.mkdir()
        cli_main(["optimize", str(strat_path), "--log-dir", str(empty)])
        out = capsys.readouterr().out
        assert "No sessions found" in out

    def test_cli_missing_strategy_file(self) -> None:
        with pytest.raises(SystemExit):
            cli_main(["optimize", "/nonexistent/strategy.json"])

    def test_cli_no_command(self) -> None:
        with pytest.raises(SystemExit):
            cli_main([])
