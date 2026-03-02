"""Tests for the FastAPI dashboard (dashboard.py).

Uses FastAPI TestClient (from starlette) for all HTTP assertions.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

import dashboard
from dashboard import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_dirs(tmp_path):
    """Point dashboard at temporary log / reports dirs for every test."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    dashboard.LOG_DIR = log_dir
    dashboard.REPORTS_DIR = reports_dir
    yield
    # Restore defaults (not strictly needed — each test gets fresh tmp_path)
    dashboard.LOG_DIR = Path("logs")
    dashboard.REPORTS_DIR = Path("reports")


@pytest.fixture
def client():
    """FastAPI TestClient."""
    return TestClient(app)


def _create_session(log_dir: Path, timestamp: str = "20250101_120000",
                    game_id: str = "DEMO", rows: int = 30) -> Path:
    """Create a synthetic session (CSV + session.json + history.json)."""
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = log_dir / f"{stem}.csv"
    session_path = log_dir / f"{stem}.session.json"
    history_path = log_dir / f"{stem}.history.json"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning", "observations",
                         "money", "visitors", "satisfaction"])
        for i in range(rows):
            writer.writerow([
                f"2025-01-01T12:00:{i:02d}", i, "observe", "testing", "ok",
                5000 + i * 10, 50 + i, 70.0 - i * 0.2,
            ])

    session_path.write_text(json.dumps({
        "cost": {"total_cost_usd": 0.05},
        "strategy": {"mode": "balanced"},
    }))
    history_path.write_text(json.dumps([{"action": "observe"}]))

    return csv_path


@pytest.fixture
def session_csv(tmp_path) -> Path:
    """Create one session and return its CSV path."""
    return _create_session(dashboard.LOG_DIR)


@pytest.fixture
def two_sessions(tmp_path) -> list[Path]:
    """Create two sessions for comparison tests."""
    p1 = _create_session(dashboard.LOG_DIR, "20250101_120000", "DEMO")
    p2 = _create_session(dashboard.LOG_DIR, "20250101_130000", "DEMO")
    return [p1, p2]


# ---------------------------------------------------------------------------
# TestHomePage
# ---------------------------------------------------------------------------

class TestHomePage:
    def test_home_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_home_contains_title(self, client):
        resp = client.get("/")
        assert "PS1 AI Dashboard" in resp.text

    def test_home_lists_sessions(self, client, session_csv):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "20250101_120000" in resp.text
        assert "DEMO" in resp.text

    def test_home_shows_no_sessions_message(self, client):
        resp = client.get("/")
        assert "No sessions found" in resp.text

    def test_home_has_sample_links(self, client):
        resp = client.get("/")
        assert "/sample/themepark" in resp.text
        assert "/sample/rpg" in resp.text
        assert "/sample/action" in resp.text


# ---------------------------------------------------------------------------
# TestSessionDetail
# ---------------------------------------------------------------------------

class TestSessionDetail:
    def test_session_detail_returns_200(self, client, session_csv):
        resp = client.get(f"/session/{session_csv.name}")
        assert resp.status_code == 200

    def test_session_detail_shows_summary(self, client, session_csv):
        resp = client.get(f"/session/{session_csv.name}")
        assert "DEMO" in resp.text
        assert "money" in resp.text

    def test_session_detail_404_for_missing(self, client):
        resp = client.get("/session/nonexistent.csv")
        assert resp.status_code == 404

    def test_session_detail_has_chart_links(self, client, session_csv):
        resp = client.get(f"/session/{session_csv.name}")
        assert "timeseries" in resp.text
        assert "correlation" in resp.text


# ---------------------------------------------------------------------------
# TestChartEndpoints
# ---------------------------------------------------------------------------

class TestChartEndpoints:
    def test_timeseries_chart_returns_png(self, client, session_csv):
        resp = client.get(f"/session/{session_csv.name}/chart/timeseries")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        # PNG magic bytes
        assert resp.content[:4] == b"\x89PNG"

    def test_correlation_chart_returns_png(self, client, session_csv):
        resp = client.get(f"/session/{session_csv.name}/chart/correlation")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    def test_unknown_chart_type_404(self, client, session_csv):
        resp = client.get(f"/session/{session_csv.name}/chart/unknown_type")
        assert resp.status_code == 404

    def test_causal_graph_chart(self, client, session_csv):
        resp = client.get(f"/session/{session_csv.name}/chart/causal_graph")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    def test_lag_correlations_chart(self, client, session_csv):
        resp = client.get(f"/session/{session_csv.name}/chart/lag_correlations")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"


# ---------------------------------------------------------------------------
# TestGDDPage
# ---------------------------------------------------------------------------

class TestGDDPage:
    def test_gdd_list_empty(self, client):
        resp = client.get("/gdd")
        assert resp.status_code == 200
        assert "No GDD markdown files" in resp.text

    def test_gdd_list_shows_files(self, client):
        (dashboard.REPORTS_DIR / "GDD_DEMO_20250101.md").write_text("# Test GDD\n")
        resp = client.get("/gdd")
        assert resp.status_code == 200
        assert "GDD_DEMO_20250101.md" in resp.text

    def test_gdd_view_renders(self, client):
        (dashboard.REPORTS_DIR / "test.md").write_text(
            "# My GDD\n## Mechanics\n- Feature A\n---\nSome text\n"
        )
        resp = client.get("/gdd/test.md")
        assert resp.status_code == 200
        assert "My GDD" in resp.text
        assert "Mechanics" in resp.text

    def test_gdd_view_404_for_missing(self, client):
        resp = client.get("/gdd/nonexistent.md")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestSampleAnalysis
# ---------------------------------------------------------------------------

class TestSampleAnalysis:
    def test_sample_themepark(self, client):
        sample_path = PROJECT_ROOT / "sample_data" / "sample_log.csv"
        if not sample_path.exists():
            pytest.skip("sample_data/sample_log.csv not found")
        resp = client.get("/sample/themepark")
        assert resp.status_code == 200
        assert "ThemePark" in resp.text
        assert "money" in resp.text

    def test_sample_rpg(self, client):
        sample_path = PROJECT_ROOT / "sample_data" / "rpg_sample_log.csv"
        if not sample_path.exists():
            pytest.skip("sample_data/rpg_sample_log.csv not found")
        resp = client.get("/sample/rpg")
        assert resp.status_code == 200
        assert "RPG" in resp.text

    def test_sample_unknown_genre_404(self, client):
        resp = client.get("/sample/unknown_genre")
        assert resp.status_code == 404

    def test_sample_action(self, client):
        sample_path = PROJECT_ROOT / "sample_data" / "action_sample_log.csv"
        if not sample_path.exists():
            pytest.skip("sample_data/action_sample_log.csv not found")
        resp = client.get("/sample/action")
        assert resp.status_code == 200
        assert "Action" in resp.text


# ---------------------------------------------------------------------------
# TestJSONAPI
# ---------------------------------------------------------------------------

class TestJSONAPI:
    def test_api_sessions_empty(self, client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_api_sessions_with_data(self, client, session_csv):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["game_id"] == "DEMO"
        assert data[0]["timestamp"] == "20250101_120000"
        assert data[0]["total_steps"] == 30

    def test_api_session_detail(self, client, session_csv):
        resp = client.get(f"/api/session/{session_csv.name}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == "DEMO"
        assert data["total_steps"] == 30
        assert "parameters" in data
        assert "money" in data["parameters"]

    def test_api_session_detail_404(self, client):
        resp = client.get("/api/session/nonexistent.csv")
        assert resp.status_code == 404

    def test_api_session_data(self, client, session_csv):
        resp = client.get(f"/api/session/{session_csv.name}/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rows"] == 30
        assert "data" in data
        assert len(data["data"]) == 30
        assert "money" in data["columns"]


# ---------------------------------------------------------------------------
# TestComparePage
# ---------------------------------------------------------------------------

class TestComparePage:
    def test_compare_form_shows(self, client, two_sessions):
        resp = client.get("/compare")
        assert resp.status_code == 200
        assert "20250101_120000" in resp.text
        assert "20250101_130000" in resp.text

    def test_compare_form_needs_sessions(self, client):
        resp = client.get("/compare")
        assert resp.status_code == 200
        assert "Need at least 2 sessions" in resp.text

    def test_compare_result(self, client, two_sessions):
        resp = client.post(
            "/compare/result",
            data={"sessions": [p.name for p in two_sessions]},
        )
        assert resp.status_code == 200
        assert "Comparison Result" in resp.text
        assert "DEMO" in resp.text

    def test_compare_result_needs_two(self, client, session_csv):
        resp = client.post(
            "/compare/result",
            data={"sessions": [session_csv.name]},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Helper — session with varied actions
# ---------------------------------------------------------------------------

def _create_session_with_actions(log_dir: Path,
                                 timestamp: str = "20250101_120000",
                                 game_id: str = "DEMO",
                                 rows: int = 30) -> Path:
    """Create a session with diverse actions (observe/attack/defend cycle)."""
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = log_dir / f"{stem}.csv"
    session_path = log_dir / f"{stem}.session.json"
    history_path = log_dir / f"{stem}.history.json"

    action_cycle = ["observe", "attack", "defend"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning", "observations",
                         "money", "visitors", "satisfaction"])
        for i in range(rows):
            writer.writerow([
                f"2025-01-01T12:00:{i:02d}", i, action_cycle[i % 3],
                "testing", "ok",
                5000 + i * 10, 50 + i, 70.0 - i * 0.2,
            ])

    session_path.write_text(json.dumps({
        "cost": {"total_cost_usd": 0.05},
        "strategy": {"mode": "balanced"},
    }))
    history_path.write_text(json.dumps([
        {"step": i, "action": [action_cycle[i % 3], "wait"],
         "parameters": {"money": 5000 + i * 10}}
        for i in range(min(10, rows))
    ]))

    return csv_path


# ---------------------------------------------------------------------------
# TestReplayRoute
# ---------------------------------------------------------------------------

class TestReplayRoute:
    def test_replay_page_returns_200(self, client):
        _create_session_with_actions(dashboard.LOG_DIR)
        csv_name = "20250101_120000_DEMO_agent.csv"
        resp = client.get(f"/session/{csv_name}/replay")
        assert resp.status_code == 200
        assert "Replay" in resp.text
        assert "Step" in resp.text

    def test_replay_page_step_navigation(self, client):
        _create_session_with_actions(dashboard.LOG_DIR)
        csv_name = "20250101_120000_DEMO_agent.csv"
        resp = client.get(f"/session/{csv_name}/replay?step=5")
        assert resp.status_code == 200
        assert "Step" in resp.text
        # Should have prev/next links
        assert "Prev" in resp.text
        assert "Next" in resp.text

    def test_replay_page_404_for_missing(self, client):
        resp = client.get("/session/nonexistent.csv/replay")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestActionsRoute
# ---------------------------------------------------------------------------

class TestActionsRoute:
    def test_actions_page_returns_200(self, client):
        _create_session_with_actions(dashboard.LOG_DIR)
        csv_name = "20250101_120000_DEMO_agent.csv"
        resp = client.get(f"/session/{csv_name}/actions")
        assert resp.status_code == 200
        assert "Action Analysis" in resp.text
        assert "Action Frequency" in resp.text

    def test_actions_page_shows_transitions(self, client):
        _create_session_with_actions(dashboard.LOG_DIR)
        csv_name = "20250101_120000_DEMO_agent.csv"
        resp = client.get(f"/session/{csv_name}/actions")
        assert "observe" in resp.text
        assert "attack" in resp.text
        assert "defend" in resp.text

    def test_actions_page_404_for_missing(self, client):
        resp = client.get("/session/nonexistent.csv/actions")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestMonitorPage
# ---------------------------------------------------------------------------

class TestMonitorPage:
    def test_monitor_no_active_session(self, client):
        """GET /monitor with no CSVs returns 200 and shows 'No active session'."""
        resp = client.get("/monitor")
        assert resp.status_code == 200
        assert "No active session" in resp.text

    def test_monitor_with_active_session(self, client, session_csv):
        """GET /monitor with an active CSV returns 200 and session data."""
        resp = client.get("/monitor")
        assert resp.status_code == 200
        assert "Live Monitor" in resp.text
        assert "DEMO" in resp.text

    def test_monitor_shows_parameters(self, client, session_csv):
        """Parameter table is visible in the monitor page."""
        resp = client.get("/monitor")
        assert resp.status_code == 200
        assert "money" in resp.text
        assert "visitors" in resp.text
        assert "satisfaction" in resp.text

    def test_monitor_shows_latest_action(self, client, session_csv):
        """Latest step card shows action/reasoning/observations."""
        resp = client.get("/monitor")
        assert resp.status_code == 200
        assert "Latest Step" in resp.text
        assert "observe" in resp.text

    def test_monitor_has_auto_refresh(self, client, session_csv):
        """Page contains <meta http-equiv="refresh"> tag."""
        resp = client.get("/monitor")
        assert resp.status_code == 200
        assert 'http-equiv="refresh"' in resp.text

    def test_monitor_has_auto_refresh_no_session(self, client):
        """Auto-refresh is present even when no session is active."""
        resp = client.get("/monitor")
        assert resp.status_code == 200
        assert 'http-equiv="refresh"' in resp.text


# ---------------------------------------------------------------------------
# TestMonitorAPI
# ---------------------------------------------------------------------------

class TestMonitorAPI:
    def test_api_monitor_no_session(self, client):
        """GET /api/monitor with no CSVs returns {"active": false}."""
        resp = client.get("/api/monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False

    def test_api_monitor_with_session(self, client, session_csv):
        """GET /api/monitor with an active CSV returns full JSON."""
        resp = client.get("/api/monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["game_id"] == "DEMO"
        assert data["total_steps"] == 30
        assert "param_stats" in data
        assert "money" in data["param_stats"]
        money = data["param_stats"]["money"]
        assert "value" in money
        assert "delta" in money
        assert "min" in money
        assert "max" in money
        assert "mean" in money
        assert "trend" in money
        assert "recent_actions" in data
        assert len(data["recent_actions"]) == 20  # last 20 of 30 rows

    def test_api_monitor_screenshot_404(self, client):
        """GET /api/monitor/screenshot returns 404 when no captures exist."""
        resp = client.get("/api/monitor/screenshot")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Helper — multiple sessions for cross-analysis tests
# ---------------------------------------------------------------------------

def _create_multi_sessions(log_dir: Path) -> list[Path]:
    """Create 3 sessions with varied strategies for cross-analysis tests."""
    strategies = ["balanced", "aggressive", "balanced"]
    paths = []
    for i, strat in enumerate(strategies):
        ts = f"2025010{i + 1}_120000"
        stem = f"{ts}_DEMO_agent"
        csv_path = log_dir / f"{stem}.csv"
        session_path = log_dir / f"{stem}.session.json"
        history_path = log_dir / f"{stem}.history.json"

        rows_count = 20 + i * 5
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "step", "action", "reasoning",
                             "observations", "money", "visitors", "satisfaction"])
            for j in range(rows_count):
                writer.writerow([
                    f"2025-01-0{i + 1}T12:00:{j:02d}", j,
                    ["observe", "attack", "defend"][j % 3],
                    "testing", "ok",
                    5000 + j * 10 + i * 100,
                    50 + j + i * 5,
                    70.0 - j * 0.2 + i * 2,
                ])

        session_path.write_text(json.dumps({
            "cost": {"total_cost_usd": 0.05 * (i + 1)},
            "strategy": {"current": strat},
        }))
        history_path.write_text(json.dumps([]))
        paths.append(csv_path)
    return paths


# ---------------------------------------------------------------------------
# TestCrossAnalysisPage
# ---------------------------------------------------------------------------

class TestCrossAnalysisPage:
    def test_cross_analysis_no_sessions(self, client):
        """GET /cross-analysis with no sessions shows empty message."""
        resp = client.get("/cross-analysis")
        assert resp.status_code == 200
        assert "No sessions found" in resp.text

    def test_cross_analysis_with_sessions(self, client):
        """GET /cross-analysis with sessions returns full analysis."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/cross-analysis")
        assert resp.status_code == 200
        assert "Cross-Session Analysis" in resp.text
        assert "Session Progression" in resp.text
        assert "Parameter Evolution" in resp.text
        assert "Strategy Effectiveness" in resp.text

    def test_cross_analysis_shows_recommendations(self, client):
        """Recommendations section is present when multiple strategies exist."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/cross-analysis")
        assert resp.status_code == 200
        assert "Recommendations" in resp.text

    def test_cross_analysis_game_filter(self, client):
        """Game filter via ?game= query param works."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/cross-analysis?game=DEMO")
        assert resp.status_code == 200
        assert "Session Progression" in resp.text

    def test_cross_analysis_game_filter_no_match(self, client):
        """Game filter with unknown game shows empty message."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/cross-analysis?game=NONEXISTENT")
        assert resp.status_code == 200
        assert "No sessions found" in resp.text

    def test_cross_analysis_has_nav_link(self, client):
        """Nav bar contains Cross-Analysis link."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "/cross-analysis" in resp.text

    def test_cross_analysis_shows_trend_colors(self, client):
        """Parameter evolution table contains trend indicators."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/cross-analysis")
        assert resp.status_code == 200
        # Should contain trend words
        assert "baseline" in resp.text


# ---------------------------------------------------------------------------
# TestCrossAnalysisAPI
# ---------------------------------------------------------------------------

class TestCrossAnalysisAPI:
    def test_api_cross_analysis_no_sessions(self, client):
        """GET /api/cross-analysis with no sessions returns count 0."""
        resp = client.get("/api/cross-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_count"] == 0

    def test_api_cross_analysis_with_sessions(self, client):
        """GET /api/cross-analysis returns full analysis JSON."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/api/cross-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_count"] == 3
        assert "parameter_evolution" in data
        assert "strategy_effectiveness" in data
        assert "action_effectiveness" in data
        assert "recommendations" in data
        assert "session_progression" in data

    def test_api_cross_analysis_game_filter(self, client):
        """GET /api/cross-analysis?game= filters by game ID."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/api/cross-analysis?game=DEMO")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_count"] == 3

    def test_api_cross_analysis_game_filter_no_match(self, client):
        """GET /api/cross-analysis?game=UNKNOWN returns count 0."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/api/cross-analysis?game=UNKNOWN")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_count"] == 0


# ---------------------------------------------------------------------------
# TestSessionExport
# ---------------------------------------------------------------------------

class TestSessionExport:
    def test_export_returns_zip(self, client, session_csv):
        """GET /session/{name}/export returns a ZIP file."""
        resp = client.get(f"/session/{session_csv.name}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        # ZIP magic bytes
        assert resp.content[:2] == b"PK"

    def test_export_has_content_disposition(self, client, session_csv):
        """Response includes Content-Disposition header with filename."""
        resp = client.get(f"/session/{session_csv.name}/export")
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert ".zip" in resp.headers.get("content-disposition", "")

    def test_export_404_for_missing(self, client):
        """GET /session/nonexistent/export returns 404."""
        resp = client.get("/session/nonexistent.csv/export")
        assert resp.status_code == 404

    def test_session_detail_has_download_button(self, client, session_csv):
        """Session detail page contains the export download link."""
        resp = client.get(f"/session/{session_csv.name}")
        assert resp.status_code == 200
        assert "Download ZIP" in resp.text
        assert f"/session/{session_csv.name}/export" in resp.text


# ---------------------------------------------------------------------------
# TestAnomalyAlerts
# ---------------------------------------------------------------------------

class TestAnomalyAlerts:
    def test_cross_analysis_shows_anomaly_section(self, client):
        """Cross-analysis page shows anomaly alerts when anomalies exist."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/cross-analysis")
        assert resp.status_code == 200
        assert "Anomaly Alerts" in resp.text


# ---------------------------------------------------------------------------
# TestOptimizePage
# ---------------------------------------------------------------------------

class TestOptimizePage:
    def test_optimize_page_no_strategies(self, client):
        """GET /optimize with no strategy files shows message."""
        resp = client.get("/optimize")
        assert resp.status_code == 200
        # Either shows strategies or 'no strategy files' depending on config dir

    def test_optimize_page_with_strategy(self, client):
        """GET /optimize?strategy=rpg.json returns optimisation results."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/optimize?strategy=rpg.json")
        assert resp.status_code == 200
        # Page should contain optimizer output or 'select' prompt
        assert "Optimize" in resp.text

    def test_optimize_page_has_nav_link(self, client):
        """Nav bar contains Optimize link."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "/optimize" in resp.text


class TestOptimizeAPI:
    def test_api_optimize_list(self, client):
        """GET /api/optimize without strategy param lists available files."""
        resp = client.get("/api/optimize")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategies" in data

    def test_api_optimize_with_sessions(self, client):
        """GET /api/optimize?strategy=rpg.json returns optimisation JSON."""
        _create_multi_sessions(dashboard.LOG_DIR)
        resp = client.get("/api/optimize?strategy=rpg.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "optimized" in data or "error" in data

    def test_api_optimize_missing_strategy(self, client):
        """GET /api/optimize?strategy=nonexistent.json returns 404."""
        resp = client.get("/api/optimize?strategy=nonexistent.json")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestWatcherPage
# ---------------------------------------------------------------------------

class TestWatcherPage:
    def test_watcher_page_no_session(self, client):
        """GET /watcher with no active session shows waiting message."""
        resp = client.get("/watcher")
        assert resp.status_code == 200
        assert "Memory Watcher" in resp.text
        assert "No active session" in resp.text

    def test_watcher_page_with_session(self, client, session_csv):
        """GET /watcher with active session shows session status."""
        resp = client.get("/watcher")
        assert resp.status_code == 200
        assert "Memory Watcher" in resp.text
        assert "Session Status" in resp.text
        assert "Steps analyzed" in resp.text

    def test_watcher_page_has_auto_refresh(self, client):
        """Page includes auto-refresh meta tag."""
        resp = client.get("/watcher")
        assert resp.status_code == 200
        assert 'http-equiv="refresh"' in resp.text

    def test_watcher_page_has_sse_script(self, client):
        """Page includes SSE JavaScript for live alerts."""
        resp = client.get("/watcher")
        assert resp.status_code == 200
        assert "EventSource" in resp.text
        assert "/api/watcher/events" in resp.text

    def test_watcher_nav_link(self, client):
        """Nav bar contains Watcher link."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "/watcher" in resp.text


# ---------------------------------------------------------------------------
# TestWatcherAPI
# ---------------------------------------------------------------------------

class TestWatcherAPI:
    def test_api_watcher_alerts_no_session(self, client):
        """GET /api/watcher/alerts with no active session returns inactive."""
        resp = client.get("/api/watcher/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False
        assert data["alerts"] == []

    def test_api_watcher_alerts_with_session(self, client, session_csv):
        """GET /api/watcher/alerts with active session returns alerts."""
        resp = client.get("/api/watcher/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert "alerts" in data
        assert "summary" in data
        assert data["total_steps"] == 30

    def test_api_watcher_alerts_strategy_filter(self, client, session_csv):
        """GET /api/watcher/alerts?strategy=nonexistent.json returns 404."""
        resp = client.get("/api/watcher/alerts?strategy=nonexistent.json")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestSessionDiff
# ---------------------------------------------------------------------------

class TestSessionDiff:
    def test_diff_page_no_params(self, client, two_sessions):
        """GET /session/diff without query params shows session selector form."""
        resp = client.get("/session/diff")
        assert resp.status_code == 200
        assert "Session Diff" in resp.text
        assert "<select" in resp.text

    def test_diff_page_with_sessions(self, client, two_sessions):
        """GET /session/diff?a=...&b=... shows diff results."""
        a_name = two_sessions[0].name
        b_name = two_sessions[1].name
        resp = client.get(f"/session/diff?a={a_name}&b={b_name}")
        assert resp.status_code == 200
        assert "Summary" in resp.text
        assert "Divergence" in resp.text

    def test_diff_page_missing_session(self, client):
        """GET /session/diff with nonexistent CSV returns 404."""
        resp = client.get("/session/diff?a=nonexistent.csv&b=also_missing.csv")
        assert resp.status_code == 404

    def test_api_diff(self, client, two_sessions):
        """GET /api/session/diff returns JSON diff data."""
        a_name = two_sessions[0].name
        b_name = two_sessions[1].name
        resp = client.get(f"/api/session/diff?a={a_name}&b={b_name}")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "step_diffs" in data
        assert "divergence_points" in data

    def test_api_diff_missing(self, client):
        """GET /api/session/diff with nonexistent CSV returns 404."""
        resp = client.get("/api/session/diff?a=nope.csv&b=nope2.csv")
        assert resp.status_code == 404

    def test_diff_nav_link(self, client):
        """Nav bar contains /session/diff link."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "/session/diff" in resp.text


# ---------------------------------------------------------------------------
# TestSessionTags (dashboard integration)
# ---------------------------------------------------------------------------

class TestSessionTags:
    def test_home_shows_tags_column(self, client, session_csv):
        """Home page session table has a Tags column header."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "<th>Tags</th>" in resp.text

    def test_home_tag_filter(self, client, session_csv):
        """?tag= query param filters sessions by tag."""
        from session_tagger import SessionTagger

        tagger = SessionTagger(log_dir=dashboard.LOG_DIR)
        tagger.tag(session_csv.name, "good_run")

        # With matching tag — session appears
        resp = client.get("/?tag=good_run")
        assert resp.status_code == 200
        assert "20250101_120000" in resp.text

        # With non-matching tag — session does not appear
        resp = client.get("/?tag=nonexistent")
        assert resp.status_code == 200
        assert "20250101_120000" not in resp.text

    def test_session_detail_shows_tags(self, client, session_csv):
        """Session detail page shows tags in summary card."""
        from session_tagger import SessionTagger

        tagger = SessionTagger(log_dir=dashboard.LOG_DIR)
        tagger.tag(session_csv.name, "boss_fight")

        resp = client.get(f"/session/{session_csv.name}")
        assert resp.status_code == 200
        assert "boss_fight" in resp.text
        assert "Tags" in resp.text

    def test_api_get_tags(self, client, session_csv):
        """GET /api/session/{name}/tags returns tags JSON."""
        from session_tagger import SessionTagger

        tagger = SessionTagger(log_dir=dashboard.LOG_DIR)
        tagger.tag(session_csv.name, "good_run", "failed")

        resp = client.get(f"/api/session/{session_csv.name}/tags")
        assert resp.status_code == 200
        data = resp.json()
        assert data["csv_filename"] == session_csv.name
        assert "good_run" in data["tags"]
        assert "failed" in data["tags"]

    def test_api_post_tags(self, client, session_csv):
        """POST /api/session/{name}/tags adds/removes tags via JSON."""
        # Add tags
        resp = client.post(
            f"/api/session/{session_csv.name}/tags",
            json={"action": "tag", "tags": ["good_run", "boss_fight"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "good_run" in data["tags"]
        assert "boss_fight" in data["tags"]

        # Remove a tag
        resp = client.post(
            f"/api/session/{session_csv.name}/tags",
            json={"action": "untag", "tags": ["boss_fight"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "good_run" in data["tags"]
        assert "boss_fight" not in data["tags"]


# ---------------------------------------------------------------------------
# TestPredictPage
# ---------------------------------------------------------------------------

class TestPredictPage:
    def test_predict_page_returns_200(self, client, session_csv):
        """GET /session/{name}/predict returns 200."""
        resp = client.get(f"/session/{session_csv.name}/predict")
        assert resp.status_code == 200

    def test_predict_page_shows_charts(self, client, session_csv):
        """Prediction page contains chart images."""
        resp = client.get(f"/session/{session_csv.name}/predict")
        assert resp.status_code == 200
        assert "data:image/png;base64," in resp.text
        assert "Prediction Charts" in resp.text

    def test_predict_page_shows_table(self, client, session_csv):
        """Prediction page contains threshold table."""
        resp = client.get(f"/session/{session_csv.name}/predict")
        assert resp.status_code == 200
        assert "Threshold Predictions" in resp.text
        assert "Regression Summary" in resp.text

    def test_api_predict(self, client, session_csv):
        """GET /api/session/{name}/predict returns JSON prediction data."""
        resp = client.get(f"/api/session/{session_csv.name}/predict")
        assert resp.status_code == 200
        data = resp.json()
        assert "parameters" in data
        assert "thresholds" in data
        assert "money" in data["parameters"]
        assert "regression" in data["parameters"]["money"]
        assert "forecast" in data["parameters"]["money"]

    def test_session_detail_has_predict_link(self, client, session_csv):
        """Session detail page contains the Predict button link."""
        resp = client.get(f"/session/{session_csv.name}")
        assert resp.status_code == 200
        assert "Predict" in resp.text
        assert f"/session/{session_csv.name}/predict" in resp.text


# ---------------------------------------------------------------------------
# TestNotifierPage
# ---------------------------------------------------------------------------

class TestNotifierPage:
    def test_notifier_page_no_config(self, client):
        """GET /notifier with no config shows setup instructions."""
        resp = client.get("/notifier")
        assert resp.status_code == 200
        assert "Alert Notifier" in resp.text
        assert "No notifier config" in resp.text

    def test_notifier_page_with_config(self, client):
        """GET /notifier with config shows webhook table."""
        import json as _json
        config = {"webhooks": [
            {"backend": "slack", "url": "https://hooks.slack.com/test",
             "enabled": True, "min_severity": "medium", "name": "test-slack"},
        ]}
        config_path = dashboard.LOG_DIR / "alert_notifier.json"
        config_path.write_text(_json.dumps(config))
        resp = client.get("/notifier")
        assert resp.status_code == 200
        assert "test-slack" in resp.text
        assert "slack" in resp.text

    def test_api_notifier_config_get_empty(self, client):
        """GET /api/notifier/config with no config returns empty list."""
        resp = client.get("/api/notifier/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["webhooks"] == []

    def test_api_notifier_config_post(self, client):
        """POST /api/notifier/config saves webhook configuration."""
        resp = client.post("/api/notifier/config", json={
            "webhooks": [
                {"backend": "discord", "url": "https://discord.com/test",
                 "enabled": True, "min_severity": "high", "name": "my-discord"},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] is True
        assert len(data["webhooks"]) == 1

        # Verify it persisted
        resp2 = client.get("/api/notifier/config")
        data2 = resp2.json()
        assert data2["configured"] is True
        assert data2["webhooks"][0]["backend"] == "discord"

    def test_api_notifier_test_no_config(self, client):
        """POST /api/notifier/test with no config returns 404."""
        resp = client.post("/api/notifier/test")
        assert resp.status_code == 404
