"""Tests for session_scorer.py — Session Scoring & Ranking."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from session_scorer import DEFAULT_WEIGHTS, ScoreBreakdown, SessionScorer


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
    cost: float = 0.05,
    actions: list[str] | None = None,
) -> Path:
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = log_dir / f"{stem}.csv"
    session_path = log_dir / f"{stem}.session.json"
    history_path = log_dir / f"{stem}.history.json"

    action_cycle = actions or ["observe", "attack", "defend"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning",
                         "observations", "hp", "gold"])
        for i in range(rows):
            act = action_cycle[i % len(action_cycle)]
            writer.writerow([
                f"2025-01-01T12:00:{i:02d}", i, act, "testing", "ok",
                hp_start - i * 2, gold_start + i * 50,
            ])

    session_path.write_text(json.dumps({
        "cost": {"total_cost_usd": cost},
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
def session(log_dir):
    from session_replay import SessionData
    csv_path = _create_session(log_dir, rows=30, hp_start=100, gold_start=500)
    return SessionData.from_log_path(csv_path)


@pytest.fixture
def two_sessions(log_dir):
    from session_replay import SessionData
    # Session 1: 30 steps, 3 actions, cost 0.05
    _create_session(log_dir, "20250101_120000", rows=30, cost=0.05)
    # Session 2: 80 steps, 5 actions, cost 0.02
    _create_session(log_dir, "20250201_120000", rows=80, cost=0.02,
                    actions=["observe", "attack", "defend", "heal", "flee"])
    return SessionData.discover_sessions(log_dir)


# ---------------------------------------------------------------------------
# TestScoreBreakdown
# ---------------------------------------------------------------------------

class TestScoreBreakdown:
    def test_to_dict(self):
        bd = ScoreBreakdown(
            steps_score=80.0, param_improvement_score=60.0,
            action_diversity_score=75.0, cost_efficiency_score=90.0,
            total=75.5,
        )
        d = bd.to_dict()
        assert d["steps_score"] == 80.0
        assert d["total"] == 75.5
        assert "weights" in d

    def test_defaults(self):
        bd = ScoreBreakdown()
        assert bd.total == 0.0
        assert bd.weights == DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# TestSessionScorer
# ---------------------------------------------------------------------------

class TestSessionScorer:
    def test_score_returns_breakdown(self, session):
        scorer = SessionScorer()
        bd = scorer.score(session)
        assert isinstance(bd, ScoreBreakdown)
        assert 0 <= bd.total <= 100
        assert 0 <= bd.steps_score <= 100
        assert 0 <= bd.param_improvement_score <= 100
        assert 0 <= bd.action_diversity_score <= 100
        assert 0 <= bd.cost_efficiency_score <= 100

    def test_steps_score_capped(self, log_dir):
        from session_replay import SessionData
        csv_path = _create_session(log_dir, rows=200)
        s = SessionData.from_log_path(csv_path)
        scorer = SessionScorer(step_target=100)
        bd = scorer.score(s)
        assert bd.steps_score == 100.0

    def test_steps_score_proportional(self, log_dir):
        from session_replay import SessionData
        csv_path = _create_session(log_dir, rows=50)
        s = SessionData.from_log_path(csv_path)
        scorer = SessionScorer(step_target=100)
        bd = scorer.score(s)
        assert bd.steps_score == 50.0

    def test_action_diversity_single_action(self, log_dir):
        from session_replay import SessionData
        csv_path = _create_session(log_dir, rows=10, actions=["observe"])
        s = SessionData.from_log_path(csv_path)
        scorer = SessionScorer()
        bd = scorer.score(s)
        assert bd.action_diversity_score == 0.0

    def test_action_diversity_multiple(self, session):
        scorer = SessionScorer()
        bd = scorer.score(session)
        # 3 unique actions → (3-1) * 25 = 50
        assert bd.action_diversity_score == 50.0

    def test_action_diversity_five_plus(self, log_dir):
        from session_replay import SessionData
        csv_path = _create_session(
            log_dir, rows=20,
            actions=["a", "b", "c", "d", "e"],
        )
        s = SessionData.from_log_path(csv_path)
        scorer = SessionScorer()
        bd = scorer.score(s)
        assert bd.action_diversity_score == 100.0

    def test_param_improvement_increase(self, log_dir):
        from session_replay import SessionData
        # gold increases from 500 to 500+29*50=1950 → improvement
        csv_path = _create_session(log_dir, rows=30, hp_start=100, gold_start=500)
        s = SessionData.from_log_path(csv_path)
        scorer = SessionScorer()
        bd = scorer.score(s)
        # gold improves a lot, hp decreases → mixed, but average > 50 is not guaranteed
        # Just check it's in range
        assert 0 <= bd.param_improvement_score <= 100

    def test_param_improvement_neutral_for_empty(self, log_dir):
        from session_replay import SessionData
        csv_path = _create_session(log_dir, rows=1)
        s = SessionData.from_log_path(csv_path)
        scorer = SessionScorer()
        bd = scorer.score(s)
        assert bd.param_improvement_score == 50.0  # neutral

    def test_cost_efficiency_free(self, log_dir):
        from session_replay import SessionData
        csv_path = _create_session(log_dir, rows=30, cost=0.0)
        s = SessionData.from_log_path(csv_path)
        scorer = SessionScorer()
        bd = scorer.score(s)
        assert bd.cost_efficiency_score == 100.0

    def test_cost_efficiency_expensive(self, log_dir):
        from session_replay import SessionData
        csv_path = _create_session(log_dir, rows=10, cost=10.0)
        s = SessionData.from_log_path(csv_path)
        scorer = SessionScorer()
        bd = scorer.score(s)
        # 10 steps / $10 = 1 step/$, score = 1/10 = 0.1
        assert bd.cost_efficiency_score < 1.0

    def test_custom_weights(self, session):
        # Only count steps
        scorer = SessionScorer(weights={
            "steps": 100, "param_improvement": 0,
            "action_diversity": 0, "cost_efficiency": 0,
        })
        bd = scorer.score(session)
        assert bd.total == bd.steps_score

    def test_rank_sessions(self, two_sessions):
        scorer = SessionScorer()
        ranking = scorer.rank_sessions(two_sessions)
        assert len(ranking) == 2
        assert ranking[0]["rank"] == 1
        assert ranking[1]["rank"] == 2
        assert ranking[0]["score"] >= ranking[1]["score"]

    def test_rank_sessions_order(self, two_sessions):
        scorer = SessionScorer(step_target=100)
        ranking = scorer.rank_sessions(two_sessions)
        # Session with 80 steps should rank higher than 30 steps (all else being equal)
        assert ranking[0]["steps"] == 80

    def test_rank_sessions_empty(self):
        scorer = SessionScorer()
        ranking = scorer.rank_sessions([])
        assert ranking == []

    def test_to_dict(self):
        scorer = SessionScorer(step_target=50)
        d = scorer.to_dict()
        assert d["step_target"] == 50
        assert "weights" in d

    def test_to_markdown(self, two_sessions):
        scorer = SessionScorer()
        ranking = scorer.rank_sessions(two_sessions)
        md = scorer.to_markdown(ranking)
        assert "Session Ranking" in md
        assert "Rank" in md
        assert "20250101_120000" in md
        assert "20250201_120000" in md

    def test_to_markdown_empty(self):
        scorer = SessionScorer()
        md = scorer.to_markdown([])
        assert "No sessions to rank" in md


# ---------------------------------------------------------------------------
# TestSessionScorerCLI
# ---------------------------------------------------------------------------

class TestSessionScorerCLI:
    def _run_cli(self, *args):
        cmd = [sys.executable, str(PROJECT_ROOT / "session_scorer.py")] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_cli_score(self, log_dir):
        csv_path = _create_session(log_dir, rows=30)
        result = self._run_cli("score", str(csv_path))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "score" in data
        assert "breakdown" in data

    def test_cli_rank(self, log_dir):
        _create_session(log_dir, "20250101_120000", rows=30)
        _create_session(log_dir, "20250201_120000", rows=50)
        result = self._run_cli("rank", "--log-dir", str(log_dir))
        assert result.returncode == 0
        assert "Session Ranking" in result.stdout

    def test_cli_rank_json(self, log_dir):
        _create_session(log_dir, "20250101_120000", rows=30)
        result = self._run_cli("rank", "--log-dir", str(log_dir), "--format", "json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert "score" in data[0]

    def test_cli_no_command(self):
        result = self._run_cli()
        assert result.returncode != 0
