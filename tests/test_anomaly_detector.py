"""Tests for anomaly_detector.py — AnomalyDetector + CLI."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from anomaly_detector import Anomaly, AnomalyDetector, main as cli_main
from session_replay import SessionData


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
    hp_values: list[int] | None = None,
    action_pattern: list[str] | None = None,
) -> Path:
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
            hp = hp_values[i] if hp_values else 100 - i
            act = action_pattern[i % len(action_pattern)] if action_pattern else f"action_{i % 3}"
            writer.writerow([
                ts.isoformat(), i, act,
                f"reason_{i}", f"obs_{i}",
                hp, 50 + i * 2, 200 + i * 10,
            ])

    if session_info is None:
        session_info = {
            "cost": {"total_cost_usd": 0.05},
            "strategy": {"current": "balanced"},
        }
    session_path.write_text(json.dumps(session_info))
    history_path.write_text(json.dumps([]))
    return csv_path


def _make_sessions_with_spike(tmp_path: Path) -> list[SessionData]:
    """Create a session with a parameter spike (sudden drop in hp)."""
    # Normal values with a spike at step 10
    hp_vals = [100] * 10 + [20] + [100] * 9  # spike from 100 to 20 at step 10
    p = _write_session_files(
        tmp_path, timestamp="20250101_120000",
        num_steps=20, hp_values=hp_vals,
    )
    return [SessionData.from_log_path(p)]


def _make_sessions_with_regression(tmp_path: Path) -> list[SessionData]:
    """Create multiple sessions where the last one regresses."""
    paths = []
    # First two sessions: hp ends high
    for i in range(2):
        ts = f"2025010{i + 1}_120000"
        hp_vals = [100 - j for j in range(20)]  # ends at 81
        p = _write_session_files(
            tmp_path, timestamp=ts, num_steps=20, hp_values=hp_vals,
        )
        paths.append(p)
    # Third session: hp ends much lower (regression)
    hp_vals = [100] + [50 - j for j in range(19)]  # ends at 32
    p = _write_session_files(
        tmp_path, timestamp="20250103_120000", num_steps=20, hp_values=hp_vals,
    )
    paths.append(p)
    return [SessionData.from_log_path(p) for p in paths]


def _make_sessions_with_action_deviation(tmp_path: Path) -> list[SessionData]:
    """Create sessions where one has a very different action distribution."""
    paths = []
    # Normal sessions: balanced action_0/1/2
    for i in range(3):
        ts = f"2025010{i + 1}_120000"
        p = _write_session_files(
            tmp_path, timestamp=ts, num_steps=30,
            action_pattern=["action_0", "action_1", "action_2"],
        )
        paths.append(p)
    # Deviant session: almost entirely action_0
    p = _write_session_files(
        tmp_path, timestamp="20250104_120000", num_steps=30,
        action_pattern=["action_0", "action_0", "action_0", "action_0",
                        "action_0", "action_0", "action_0", "action_0",
                        "action_0", "action_1"],
    )
    paths.append(p)
    return [SessionData.from_log_path(p) for p in paths]


# ---------------------------------------------------------------------------
# TestAnomaly dataclass
# ---------------------------------------------------------------------------

class TestAnomaly:
    def test_to_dict(self) -> None:
        a = Anomaly(
            kind="spike", severity="high", session="20250101_120000",
            description="test", details={"param": "hp"},
        )
        d = a.to_dict()
        assert d["kind"] == "spike"
        assert d["severity"] == "high"
        assert d["details"]["param"] == "hp"


# ---------------------------------------------------------------------------
# TestAnomalyDetector
# ---------------------------------------------------------------------------

class TestAnomalyDetector:
    def test_requires_sessions(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            AnomalyDetector([])

    def test_detect_spikes(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_spike(tmp_path)
        detector = AnomalyDetector(sessions, spike_threshold=2.0)
        spikes = detector.detect_spikes()
        assert len(spikes) > 0
        assert all(a.kind == "spike" for a in spikes)
        # The spike should be for hp
        hp_spikes = [a for a in spikes if a.details.get("parameter") == "hp"]
        assert len(hp_spikes) > 0

    def test_detect_spikes_no_spikes(self, tmp_path: Path) -> None:
        """Smooth linear data should produce no spikes."""
        hp_vals = list(range(100, 80, -1))
        p = _write_session_files(
            tmp_path, num_steps=20, hp_values=hp_vals,
        )
        sessions = [SessionData.from_log_path(p)]
        detector = AnomalyDetector(sessions, spike_threshold=2.5)
        spikes = detector.detect_spikes()
        # Linear hp decrease means constant deltas, std=0, no spikes
        hp_spikes = [a for a in spikes if a.details.get("parameter") == "hp"]
        assert len(hp_spikes) == 0

    def test_detect_spikes_severity(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_spike(tmp_path)
        detector = AnomalyDetector(sessions, spike_threshold=2.0)
        spikes = detector.detect_spikes()
        for a in spikes:
            assert a.severity in ("low", "medium", "high")

    def test_detect_action_deviations(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_action_deviation(tmp_path)
        detector = AnomalyDetector(sessions, action_deviation_threshold=1.5)
        deviations = detector.detect_action_deviations()
        assert len(deviations) > 0
        assert all(a.kind == "action_deviation" for a in deviations)
        # The deviant session should be flagged
        deviant_session = [a for a in deviations if a.session == "20250104_120000"]
        assert len(deviant_session) > 0

    def test_detect_action_deviations_single_session(self, tmp_path: Path) -> None:
        """Single session can't have action deviations (no cross-session mean)."""
        p = _write_session_files(tmp_path, num_steps=20)
        sessions = [SessionData.from_log_path(p)]
        detector = AnomalyDetector(sessions)
        assert detector.detect_action_deviations() == []

    def test_detect_regressions(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_regression(tmp_path)
        detector = AnomalyDetector(sessions, regression_threshold=0.1)
        regressions = detector.detect_regressions()
        assert len(regressions) > 0
        assert all(a.kind == "regression" for a in regressions)
        hp_reg = [a for a in regressions if a.details.get("parameter") == "hp"]
        assert len(hp_reg) > 0

    def test_detect_regressions_single_session(self, tmp_path: Path) -> None:
        """Single session can't have regressions."""
        p = _write_session_files(tmp_path, num_steps=20)
        sessions = [SessionData.from_log_path(p)]
        detector = AnomalyDetector(sessions)
        assert detector.detect_regressions() == []

    def test_detect_regressions_direction(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_regression(tmp_path)
        detector = AnomalyDetector(sessions, regression_threshold=0.1)
        regressions = detector.detect_regressions()
        hp_reg = [a for a in regressions if a.details.get("parameter") == "hp"]
        if hp_reg:
            assert hp_reg[0].details["direction"] in ("improved", "regressed")

    def test_detect_all(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_regression(tmp_path)
        detector = AnomalyDetector(sessions)
        all_anomalies = detector.detect_all()
        assert isinstance(all_anomalies, list)
        # Should have at least regressions
        kinds = {a.kind for a in all_anomalies}
        assert "regression" in kinds

    def test_summary(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_regression(tmp_path)
        detector = AnomalyDetector(sessions)
        s = detector.summary()
        assert "total" in s
        assert "by_kind" in s
        assert "by_severity" in s
        assert "anomalies" in s
        assert isinstance(s["anomalies"], list)

    def test_summary_json_serializable(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_regression(tmp_path)
        detector = AnomalyDetector(sessions)
        s = detector.summary()
        output = json.dumps(s, default=str)
        parsed = json.loads(output)
        assert parsed["total"] == s["total"]

    def test_to_markdown(self, tmp_path: Path) -> None:
        sessions = _make_sessions_with_regression(tmp_path)
        detector = AnomalyDetector(sessions)
        md = detector.to_markdown()
        assert "# Anomaly Detection Report" in md
        assert "Sessions analyzed:" in md

    def test_to_markdown_no_anomalies(self, tmp_path: Path) -> None:
        """With very high thresholds, nothing should be flagged."""
        hp_vals = list(range(100, 80, -1))
        p = _write_session_files(tmp_path, num_steps=20, hp_values=hp_vals)
        sessions = [SessionData.from_log_path(p)]
        detector = AnomalyDetector(
            sessions, spike_threshold=100.0,
            regression_threshold=100.0,
        )
        md = detector.to_markdown()
        assert "No anomalies detected" in md


# ---------------------------------------------------------------------------
# TestAnomalyDetectorCLI
# ---------------------------------------------------------------------------

class TestAnomalyDetectorCLI:
    def _make_log_dir(self, tmp_path: Path) -> Path:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        for i in range(3):
            ts = f"2025010{i + 1}_120000"
            _write_session_files(log_dir, timestamp=ts, num_steps=20)
        return log_dir

    def test_cli_detect_markdown(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        log_dir = self._make_log_dir(tmp_path)
        cli_main(["detect", "--log-dir", str(log_dir)])
        out = capsys.readouterr().out
        assert "Anomaly Detection Report" in out

    def test_cli_detect_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        log_dir = self._make_log_dir(tmp_path)
        cli_main(["detect", "--log-dir", str(log_dir), "--format", "json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert "total" in parsed

    def test_cli_detect_output_file(self, tmp_path: Path) -> None:
        log_dir = self._make_log_dir(tmp_path)
        out_file = tmp_path / "report.md"
        cli_main(["detect", "--log-dir", str(log_dir), "--output", str(out_file)])
        assert out_file.exists()
        assert "Anomaly Detection Report" in out_file.read_text()

    def test_cli_no_sessions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        cli_main(["detect", "--log-dir", str(empty)])
        out = capsys.readouterr().out
        assert "No sessions found" in out

    def test_cli_no_command(self) -> None:
        with pytest.raises(SystemExit):
            cli_main([])
