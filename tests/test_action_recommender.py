"""Tests for action_recommender.py — action recommendation engine."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from action_recommender import ActionRecommender, ActionScore, main as rec_main
from session_replay import SessionData


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
            # attack: hp down, score up; defend: hp stable; heal: hp up, score stable
            if act == "attack":
                hp_delta, score_delta = -2, 5
            elif act == "defend":
                hp_delta, score_delta = 0, 1
            elif act == "heal":
                hp_delta, score_delta = 3, 0
            else:
                hp_delta, score_delta = 0, 0
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
def training_sessions(log_dir) -> list[SessionData]:
    _create_session(log_dir, "20250101_120000")
    _create_session(log_dir, "20250102_120000")
    _create_session(log_dir, "20250103_120000")
    return SessionData.discover_sessions(log_dir)


@pytest.fixture
def target_session(log_dir) -> SessionData:
    path = _create_session(log_dir, "20250104_120000")
    return SessionData.from_log_path(path)


# ---------------------------------------------------------------------------
# TestActionRecommender
# ---------------------------------------------------------------------------

class TestActionRecommender:

    def test_requires_sessions(self):
        with pytest.raises(ValueError, match="requires at least 1"):
            ActionRecommender([])

    def test_known_actions(self, training_sessions):
        rec = ActionRecommender(training_sessions)
        actions = rec.known_actions
        assert "attack" in actions
        assert "defend" in actions
        assert "heal" in actions

    def test_impact_model_has_params(self, training_sessions):
        rec = ActionRecommender(training_sessions)
        model = rec.impact_model
        assert "attack" in model
        assert "hp" in model["attack"]
        assert "mean_delta" in model["attack"]["hp"]
        assert "count" in model["attack"]["hp"]

    def test_recommend_returns_list(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions)
        recs = rec.recommend(target_session)
        assert isinstance(recs, list)
        assert len(recs) <= 3

    def test_recommend_returns_action_scores(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions)
        recs = rec.recommend(target_session)
        for r in recs:
            assert isinstance(r, ActionScore)
            assert isinstance(r.action, str)
            assert isinstance(r.score, float)
            assert isinstance(r.param_impacts, dict)

    def test_recommend_top_n(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions, top_n=2)
        recs = rec.recommend(target_session)
        assert len(recs) <= 2

    def test_recommend_sorted_descending(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions, top_n=10)
        recs = rec.recommend(target_session)
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_recommend_has_reason(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions)
        recs = rec.recommend(target_session)
        for r in recs:
            assert isinstance(r.reason, str)
            assert len(r.reason) > 0

    def test_param_weights(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions)
        weights = rec._compute_param_weights(target_session)
        assert "hp" in weights
        assert "gold" in weights
        for w in weights.values():
            assert w >= 1.0

    def test_to_dict(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions)
        d = rec.to_dict(target_session)
        assert "session" in d
        assert "recommendations" in d
        assert "param_weights" in d
        assert "known_actions" in d
        assert "training_sessions" in d
        assert d["training_sessions"] == 3

    def test_to_dict_recommendations_structure(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions)
        d = rec.to_dict(target_session)
        for r in d["recommendations"]:
            assert "rank" in r
            assert "action" in r
            assert "score" in r
            assert "param_impacts" in r
            assert "reason" in r

    def test_to_markdown(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions)
        md = rec.to_markdown(target_session)
        assert "# Action Recommendations" in md
        assert "Parameter Urgency Weights" in md
        assert "Top Recommendations" in md

    def test_to_markdown_has_impacts(self, training_sessions, target_session):
        rec = ActionRecommender(training_sessions)
        md = rec.to_markdown(target_session)
        assert "Expected Delta" in md

    def test_single_session_training(self, log_dir):
        _create_session(log_dir, "20250110_120000")
        sessions = SessionData.discover_sessions(log_dir)
        # Use same session as both training and target
        rec = ActionRecommender(sessions[:1])
        recs = rec.recommend(sessions[0])
        assert isinstance(recs, list)


# ---------------------------------------------------------------------------
# TestActionRecommenderCLI
# ---------------------------------------------------------------------------

class TestActionRecommenderCLI:

    def test_cli_no_command(self):
        with pytest.raises(SystemExit):
            rec_main([])

    def test_cli_recommend_markdown(self, log_dir, capsys):
        _create_session(log_dir, "20250101_120000")
        _create_session(log_dir, "20250102_120000")
        sessions = SessionData.discover_sessions(log_dir)
        target_path = sessions[0].csv_path
        rec_main(["recommend", str(target_path), "--log-dir", str(log_dir)])
        captured = capsys.readouterr()
        assert "Action Recommendations" in captured.out

    def test_cli_recommend_json(self, log_dir, capsys):
        _create_session(log_dir, "20250101_120000")
        sessions = SessionData.discover_sessions(log_dir)
        target_path = sessions[0].csv_path
        rec_main(["recommend", str(target_path), "--log-dir", str(log_dir),
                   "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "recommendations" in data

    def test_cli_recommend_top(self, log_dir, capsys):
        _create_session(log_dir, "20250101_120000")
        sessions = SessionData.discover_sessions(log_dir)
        target_path = sessions[0].csv_path
        rec_main(["recommend", str(target_path), "--log-dir", str(log_dir),
                   "--format", "json", "--top", "1"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["recommendations"]) <= 1

    def test_cli_no_training_sessions(self, tmp_path, capsys):
        empty = tmp_path / "empty"
        empty.mkdir()
        # Create a target session
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        path = _create_session(log_dir, "20250101_120000")
        rec_main(["recommend", str(path), "--log-dir", str(empty)])
        captured = capsys.readouterr()
        assert "No training sessions" in captured.out
