"""Tests for session_benchmark.py — session benchmark criteria management."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from session_benchmark import (
    BenchmarkCriteria,
    BenchmarkResult,
    ParamThreshold,
    SessionBenchmarkManager,
    main as bench_main,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_session(log_dir: Path, timestamp: str = "20250101_120000",
                    game_id: str = "DEMO", rows: int = 30) -> Path:
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = log_dir / f"{stem}.csv"
    session_path = log_dir / f"{stem}.session.json"
    history_path = log_dir / f"{stem}.history.json"

    actions = ["attack", "defend", "heal", "observe"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning", "observations",
                         "hp", "gold", "score"])
        for i in range(rows):
            act = actions[i % len(actions)]
            hp = max(10, 100 + sum([-2, 0, 3, 0][j % 4] for j in range(i)))
            score_val = 10 + sum([5, 1, 0, 0][j % 4] for j in range(i))
            writer.writerow([
                f"2025-01-01T12:00:{i:02d}", i, act,
                "testing", "ok",
                hp, 50 + i * 2, score_val,
            ])

    session_path.write_text(json.dumps({"cost": {"total_cost_usd": 0.01}}))
    history_path.write_text(json.dumps([]))
    return csv_path


@pytest.fixture
def log_dir(tmp_path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def mgr(log_dir) -> SessionBenchmarkManager:
    return SessionBenchmarkManager(log_dir=log_dir)


@pytest.fixture
def session(log_dir):
    from session_replay import SessionData
    _create_session(log_dir, "20250101_120000", "DEMO")
    sessions = SessionData.discover_sessions(log_dir)
    return sessions[0]


@pytest.fixture
def mgr_with_benchmark(log_dir):
    mgr = SessionBenchmarkManager(log_dir=log_dir)
    mgr.create_benchmark(
        "DEMO",
        min_steps=10,
        min_score=20.0,
        param_thresholds=[
            ParamThreshold("hp", ">=", 50.0),
            ParamThreshold("gold", ">", 40.0),
        ],
        description="Demo benchmark",
    )
    return mgr


# ---------------------------------------------------------------------------
# TestParamThreshold
# ---------------------------------------------------------------------------

class TestParamThreshold:

    def test_to_dict(self):
        t = ParamThreshold("hp", ">=", 50.0, aggregator="last")
        d = t.to_dict()
        assert d["parameter"] == "hp"
        assert d["operator"] == ">="
        assert d["value"] == 50.0
        assert d["aggregator"] == "last"

    def test_from_dict(self):
        d = {"parameter": "gold", "operator": ">", "value": 100, "aggregator": "mean"}
        t = ParamThreshold.from_dict(d)
        assert t.parameter == "gold"
        assert t.aggregator == "mean"

    def test_from_dict_default_aggregator(self):
        t = ParamThreshold.from_dict({"parameter": "hp", "operator": ">=", "value": 50})
        assert t.aggregator == "last"

    def test_parse_simple(self):
        t = ParamThreshold.parse("hp >= 50")
        assert t.parameter == "hp"
        assert t.operator == ">="
        assert t.value == 50.0
        assert t.aggregator == "last"

    def test_parse_with_aggregator(self):
        t = ParamThreshold.parse("gold mean > 1000")
        assert t.parameter == "gold"
        assert t.aggregator == "mean"
        assert t.operator == ">"
        assert t.value == 1000.0

    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            ParamThreshold.parse("hp")

    def test_parse_bad_operator(self):
        with pytest.raises(ValueError):
            ParamThreshold.parse("hp ~~ 50")

    def test_evaluate_pass(self, session):
        t = ParamThreshold("hp", ">=", 50.0)
        assert t.evaluate(session) is True

    def test_evaluate_fail(self, session):
        t = ParamThreshold("hp", ">=", 99999.0)
        assert t.evaluate(session) is False

    def test_evaluate_missing_param(self, session):
        t = ParamThreshold("nonexistent", ">=", 0)
        assert t.evaluate(session) is False

    def test_evaluate_mean_aggregator(self, session):
        t = ParamThreshold("gold", "mean", ">", 0)
        # gold starts at 50 and increases, mean > 0 should pass
        t2 = ParamThreshold("gold", ">", 0, aggregator="mean")
        assert t2.evaluate(session) is True

    def test_evaluate_min_aggregator(self, session):
        t = ParamThreshold("gold", ">=", 50, aggregator="min")
        assert t.evaluate(session) is True

    def test_evaluate_max_aggregator(self, session):
        # gold max = 50 + (rows-1)*2 = 50 + 58 = 108
        t = ParamThreshold("gold", ">=", 100, aggregator="max")
        assert t.evaluate(session) is True

    def test_str(self):
        t = ParamThreshold("hp", ">=", 50.0)
        assert str(t) == "hp >= 50.0"

    def test_str_with_aggregator(self):
        t = ParamThreshold("hp", ">=", 50.0, aggregator="mean")
        assert "mean" in str(t)

    def test_operators(self, session):
        # Test various operators
        t_gt = ParamThreshold("gold", ">", 0)
        assert t_gt.evaluate(session) is True

        t_lt = ParamThreshold("gold", "<", 99999)
        assert t_lt.evaluate(session) is True

        t_le = ParamThreshold("gold", "<=", 99999)
        assert t_le.evaluate(session) is True

        t_ne = ParamThreshold("gold", "!=", -1)
        assert t_ne.evaluate(session) is True

        t_eq = ParamThreshold("gold", "==", -1)
        assert t_eq.evaluate(session) is False


# ---------------------------------------------------------------------------
# TestBenchmarkCriteria
# ---------------------------------------------------------------------------

class TestBenchmarkCriteria:

    def test_to_dict(self):
        c = BenchmarkCriteria(
            game_id="DEMO",
            min_steps=50,
            min_score=30.0,
            param_thresholds=[ParamThreshold("hp", ">=", 50)],
            description="test",
        )
        d = c.to_dict()
        assert d["game_id"] == "DEMO"
        assert d["min_steps"] == 50
        assert d["min_score"] == 30.0
        assert len(d["param_thresholds"]) == 1

    def test_from_dict(self):
        d = {
            "game_id": "TEST",
            "min_steps": 10,
            "min_score": None,
            "param_thresholds": [{"parameter": "hp", "operator": ">=", "value": 50}],
            "description": "hello",
        }
        c = BenchmarkCriteria.from_dict(d)
        assert c.game_id == "TEST"
        assert c.min_steps == 10
        assert len(c.param_thresholds) == 1

    def test_criteria_count(self):
        c = BenchmarkCriteria(
            game_id="DEMO",
            min_steps=50,
            min_score=30.0,
            param_thresholds=[ParamThreshold("hp", ">=", 50)],
        )
        assert c.criteria_count == 3  # min_steps + min_score + 1 param

    def test_criteria_count_no_steps_no_score(self):
        c = BenchmarkCriteria(game_id="DEMO")
        assert c.criteria_count == 0


# ---------------------------------------------------------------------------
# TestBenchmarkResult
# ---------------------------------------------------------------------------

class TestBenchmarkResult:

    def test_to_dict(self):
        r = BenchmarkResult(
            game_id="DEMO", csv_filename="test.csv",
            status="pass", total_criteria=3, passed_criteria=3,
        )
        d = r.to_dict()
        assert d["status"] == "pass"
        assert d["pass_rate"] == 1.0

    def test_pass_rate_zero(self):
        r = BenchmarkResult(
            game_id="DEMO", csv_filename="test.csv",
            status="fail", total_criteria=3, passed_criteria=0,
        )
        assert r.pass_rate == 0.0

    def test_pass_rate_partial(self):
        r = BenchmarkResult(
            game_id="DEMO", csv_filename="test.csv",
            status="partial", total_criteria=4, passed_criteria=2,
        )
        assert r.pass_rate == 0.5

    def test_pass_rate_no_criteria(self):
        r = BenchmarkResult(
            game_id="DEMO", csv_filename="test.csv",
            status="pass", total_criteria=0, passed_criteria=0,
        )
        assert r.pass_rate == 1.0


# ---------------------------------------------------------------------------
# TestSessionBenchmarkManager
# ---------------------------------------------------------------------------

class TestSessionBenchmarkManager:

    def test_create_benchmark(self, mgr):
        c = mgr.create_benchmark("DEMO", min_steps=10, description="test")
        assert c.game_id == "DEMO"
        assert c.min_steps == 10

    def test_create_empty_game_id_raises(self, mgr):
        with pytest.raises(ValueError, match="must not be empty"):
            mgr.create_benchmark("")

    def test_create_replaces_existing(self, mgr):
        mgr.create_benchmark("DEMO", min_steps=10)
        mgr.create_benchmark("DEMO", min_steps=20)
        c = mgr.get_benchmark("DEMO")
        assert c.min_steps == 20

    def test_delete_benchmark(self, mgr):
        mgr.create_benchmark("DEMO")
        mgr.delete_benchmark("DEMO")
        assert len(mgr.list_benchmarks()) == 0

    def test_delete_nonexistent_raises(self, mgr):
        with pytest.raises(KeyError, match="not found"):
            mgr.delete_benchmark("NOPE")

    def test_get_benchmark(self, mgr):
        mgr.create_benchmark("DEMO", min_score=50.0)
        c = mgr.get_benchmark("DEMO")
        assert c.min_score == 50.0

    def test_get_nonexistent_raises(self, mgr):
        with pytest.raises(KeyError, match="not found"):
            mgr.get_benchmark("NOPE")

    def test_list_benchmarks_empty(self, mgr):
        assert mgr.list_benchmarks() == []

    def test_list_benchmarks_sorted(self, mgr):
        mgr.create_benchmark("ZZGAME")
        mgr.create_benchmark("AAGAME")
        benchmarks = mgr.list_benchmarks()
        assert benchmarks[0].game_id == "AAGAME"
        assert benchmarks[1].game_id == "ZZGAME"

    def test_persistence(self, log_dir):
        mgr1 = SessionBenchmarkManager(log_dir=log_dir)
        mgr1.create_benchmark("DEMO", min_steps=42)
        mgr2 = SessionBenchmarkManager(log_dir=log_dir)
        c = mgr2.get_benchmark("DEMO")
        assert c.min_steps == 42


# ---------------------------------------------------------------------------
# TestEvaluation
# ---------------------------------------------------------------------------

class TestEvaluation:

    def test_evaluate_pass(self, mgr_with_benchmark, session):
        result = mgr_with_benchmark.evaluate(session)
        # 30 steps >= 10 (pass), score >= 20 (likely pass),
        # hp >= 50 (pass), gold > 40 (pass)
        assert result.status == "pass"
        assert result.passed_criteria == result.total_criteria

    def test_evaluate_fail(self, log_dir, session):
        mgr = SessionBenchmarkManager(log_dir=log_dir)
        mgr.create_benchmark("DEMO", min_steps=99999)
        result = mgr.evaluate(session)
        assert result.status == "fail"
        assert result.passed_criteria == 0

    def test_evaluate_partial(self, log_dir, session):
        mgr = SessionBenchmarkManager(log_dir=log_dir)
        mgr.create_benchmark(
            "DEMO",
            min_steps=10,  # will pass (30 steps)
            param_thresholds=[ParamThreshold("hp", ">=", 99999)],  # will fail
        )
        result = mgr.evaluate(session)
        assert result.status == "partial"
        assert result.passed_criteria == 1
        assert result.total_criteria == 2

    def test_evaluate_no_benchmark(self, mgr, session):
        result = mgr.evaluate(session)
        assert result.status == "pass"
        assert result.total_criteria == 0

    def test_evaluate_has_details(self, mgr_with_benchmark, session):
        result = mgr_with_benchmark.evaluate(session)
        assert len(result.details) > 0
        for d in result.details:
            assert "criterion" in d
            assert "actual" in d
            assert "passed" in d

    def test_evaluate_all(self, log_dir):
        _create_session(log_dir, "20250101_120000", "DEMO")
        _create_session(log_dir, "20250102_120000", "DEMO")
        mgr = SessionBenchmarkManager(log_dir=log_dir)
        mgr.create_benchmark("DEMO", min_steps=10)
        results = mgr.evaluate_all()
        assert len(results) == 2
        for r in results:
            assert isinstance(r, BenchmarkResult)

    def test_evaluate_all_with_game_filter(self, log_dir):
        _create_session(log_dir, "20250101_120000", "DEMO")
        _create_session(log_dir, "20250102_120000", "OTHER")
        mgr = SessionBenchmarkManager(log_dir=log_dir)
        mgr.create_benchmark("DEMO", min_steps=10)
        results = mgr.evaluate_all(game_id="DEMO")
        assert len(results) == 1

    def test_evaluate_score_criterion(self, log_dir, session):
        mgr = SessionBenchmarkManager(log_dir=log_dir)
        mgr.create_benchmark("DEMO", min_score=0.1)  # very low, should pass
        result = mgr.evaluate(session)
        score_details = [d for d in result.details if "min_score" in d["criterion"]]
        assert len(score_details) == 1
        assert score_details[0]["passed"] is True


# ---------------------------------------------------------------------------
# TestOutput
# ---------------------------------------------------------------------------

class TestOutput:

    def test_to_dict(self, mgr_with_benchmark):
        d = mgr_with_benchmark.to_dict()
        assert "benchmarks" in d
        assert "total_benchmarks" in d
        assert d["total_benchmarks"] == 1

    def test_to_markdown_list(self, mgr_with_benchmark):
        md = mgr_with_benchmark.to_markdown()
        assert "# Session Benchmarks" in md
        assert "DEMO" in md

    def test_to_markdown_empty(self, mgr):
        md = mgr.to_markdown()
        assert "No benchmarks defined" in md

    def test_to_markdown_detail(self, mgr_with_benchmark):
        md = mgr_with_benchmark.to_markdown("DEMO")
        assert "# Benchmark: DEMO" in md
        assert "Min Steps" in md
        assert "Min Score" in md
        assert "Parameter Thresholds" in md

    def test_results_to_markdown(self):
        results = [
            BenchmarkResult("DEMO", "test.csv", "pass", 3, 3),
            BenchmarkResult("DEMO", "test2.csv", "fail", 3, 0),
        ]
        md = SessionBenchmarkManager.results_to_markdown(results)
        assert "# Benchmark Results" in md
        assert "PASS" in md
        assert "FAIL" in md

    def test_results_to_markdown_empty(self):
        md = SessionBenchmarkManager.results_to_markdown([])
        assert "No results" in md


# ---------------------------------------------------------------------------
# TestSessionBenchmarkCLI
# ---------------------------------------------------------------------------

class TestSessionBenchmarkCLI:

    def test_cli_no_command(self):
        with pytest.raises(SystemExit):
            bench_main([])

    def test_cli_create(self, log_dir, capsys):
        bench_main(["--log-dir", str(log_dir), "create", "DEMO",
                     "--min-steps", "10", "--min-score", "20",
                     "--param", "hp >= 50", "--description", "test"])
        captured = capsys.readouterr()
        assert "Created benchmark for DEMO" in captured.out

    def test_cli_list(self, log_dir, capsys):
        bench_main(["--log-dir", str(log_dir), "create", "DEMO"])
        capsys.readouterr()
        bench_main(["--log-dir", str(log_dir), "list"])
        captured = capsys.readouterr()
        assert "DEMO" in captured.out

    def test_cli_show(self, log_dir, capsys):
        bench_main(["--log-dir", str(log_dir), "create", "DEMO",
                     "--min-steps", "10"])
        capsys.readouterr()
        bench_main(["--log-dir", str(log_dir), "show", "DEMO"])
        captured = capsys.readouterr()
        assert "Benchmark: DEMO" in captured.out

    def test_cli_delete(self, log_dir, capsys):
        bench_main(["--log-dir", str(log_dir), "create", "DEMO"])
        capsys.readouterr()
        bench_main(["--log-dir", str(log_dir), "delete", "DEMO"])
        captured = capsys.readouterr()
        assert "Deleted" in captured.out

    def test_cli_evaluate(self, log_dir, capsys):
        _create_session(log_dir, "20250101_120000", "DEMO")
        bench_main(["--log-dir", str(log_dir), "create", "DEMO", "--min-steps", "10"])
        capsys.readouterr()
        csv_path = log_dir / "20250101_120000_DEMO_agent.csv"
        bench_main(["--log-dir", str(log_dir), "evaluate", str(csv_path)])
        captured = capsys.readouterr()
        assert "Benchmark Results" in captured.out

    def test_cli_evaluate_json(self, log_dir, capsys):
        _create_session(log_dir, "20250101_120000", "DEMO")
        bench_main(["--log-dir", str(log_dir), "create", "DEMO", "--min-steps", "10"])
        capsys.readouterr()
        csv_path = log_dir / "20250101_120000_DEMO_agent.csv"
        bench_main(["--log-dir", str(log_dir), "evaluate", str(csv_path),
                     "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "status" in data
        assert "pass_rate" in data

    def test_cli_evaluate_all(self, log_dir, capsys):
        _create_session(log_dir, "20250101_120000", "DEMO")
        bench_main(["--log-dir", str(log_dir), "create", "DEMO", "--min-steps", "10"])
        capsys.readouterr()
        bench_main(["--log-dir", str(log_dir), "evaluate-all"])
        captured = capsys.readouterr()
        assert "Benchmark Results" in captured.out

    def test_cli_delete_nonexistent(self, log_dir):
        with pytest.raises(SystemExit):
            bench_main(["--log-dir", str(log_dir), "delete", "NOPE"])
