"""Tests for memory_watcher.py — MemoryWatcher + CLI."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memory_watcher import MemoryWatcher, ThresholdRule, WatcherAlert, main as cli_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rules() -> list[ThresholdRule]:
    """Standard set of threshold rules for testing."""
    return [
        ThresholdRule(parameter="hp", operator="lt", value=30, severity="high",
                      message="HP critically low"),
        ThresholdRule(parameter="hp", operator="gt", value=90, severity="low",
                      message="HP very high"),
        ThresholdRule(parameter="gold", operator="gt", value=5000, severity="medium"),
    ]


def _write_session_csv(
    directory: Path,
    *,
    game_id: str = "DEMO",
    timestamp: str = "20250101_120000",
    num_steps: int = 30,
    include_spike: bool = False,
) -> Path:
    """Write a synthetic session CSV for CLI testing."""
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
            hp = 100 - i  # gradual decline
            if include_spike and i == 15:
                hp = 10  # sudden spike at step 15
            writer.writerow([
                ts.isoformat(), i, "action_0", "reason", "obs",
                hp, 50, 200 + i * 10,
            ])

    session_path.write_text(json.dumps({
        "cost": {"total_cost_usd": 0.05},
        "strategy": {"current": "balanced"},
    }))
    history_path.write_text(json.dumps([]))
    return csv_path


_SAMPLE_STRATEGY = {
    "genre": "rpg",
    "description": "Test RPG strategy",
    "thresholds": [
        {"parameter": "hp", "operator": "lt", "value": 30,
         "target_strategy": "defensive", "priority": 10},
        {"parameter": "hp", "operator": "gt", "value": 80,
         "target_strategy": "aggressive", "priority": 5},
        {"parameter": "gold", "operator": "gt", "value": 5000,
         "target_strategy": "equipment_upgrade", "priority": 3},
    ],
}


# ---------------------------------------------------------------------------
# TestWatcherAlert
# ---------------------------------------------------------------------------

class TestWatcherAlert:
    def test_to_dict(self) -> None:
        alert = WatcherAlert(
            kind="threshold", severity="high", parameter="hp",
            value=25.0, description="HP low", timestamp="2025-01-01T12:00:00",
            details={"rule_operator": "lt", "rule_value": 30},
        )
        d = alert.to_dict()
        assert d["kind"] == "threshold"
        assert d["severity"] == "high"
        assert d["parameter"] == "hp"
        assert d["value"] == 25.0
        assert d["description"] == "HP low"
        assert d["timestamp"] == "2025-01-01T12:00:00"
        assert d["details"]["rule_operator"] == "lt"

    def test_to_dict_json_serializable(self) -> None:
        alert = WatcherAlert(
            kind="spike", severity="medium", parameter="gold",
            value=999.0, description="spike", timestamp="t",
            details={"z_score": 3.5},
        )
        output = json.dumps(alert.to_dict())
        parsed = json.loads(output)
        assert parsed["kind"] == "spike"


# ---------------------------------------------------------------------------
# TestThresholdRule
# ---------------------------------------------------------------------------

class TestThresholdRule:
    def test_to_dict(self) -> None:
        rule = ThresholdRule(parameter="hp", operator="lt", value=30,
                             severity="high", message="low HP")
        d = rule.to_dict()
        assert d["parameter"] == "hp"
        assert d["operator"] == "lt"
        assert d["value"] == 30
        assert d["severity"] == "high"
        assert d["message"] == "low HP"

    def test_defaults(self) -> None:
        rule = ThresholdRule(parameter="gold", operator="gt", value=1000)
        assert rule.severity == "medium"
        assert rule.message == ""


# ---------------------------------------------------------------------------
# TestMemoryWatcher
# ---------------------------------------------------------------------------

class TestMemoryWatcher:
    def test_threshold_lt_triggers(self) -> None:
        watcher = MemoryWatcher(_make_rules())
        alerts = watcher.check_value("hp", 20, "t1")
        threshold_alerts = [a for a in alerts if a.kind == "threshold"]
        assert len(threshold_alerts) >= 1
        assert threshold_alerts[0].severity == "high"
        assert "HP critically low" in threshold_alerts[0].description

    def test_threshold_gt_triggers(self) -> None:
        watcher = MemoryWatcher(_make_rules())
        alerts = watcher.check_value("hp", 95, "t1")
        threshold_alerts = [a for a in alerts if a.kind == "threshold"]
        assert len(threshold_alerts) >= 1
        assert any("HP very high" in a.description for a in threshold_alerts)

    def test_threshold_le_triggers(self) -> None:
        rules = [ThresholdRule(parameter="mp", operator="le", value=10, severity="medium")]
        watcher = MemoryWatcher(rules)
        # Exact boundary
        alerts = watcher.check_value("mp", 10, "t1")
        threshold_alerts = [a for a in alerts if a.kind == "threshold"]
        assert len(threshold_alerts) == 1

    def test_threshold_ge_triggers(self) -> None:
        rules = [ThresholdRule(parameter="gold", operator="ge", value=100, severity="low")]
        watcher = MemoryWatcher(rules)
        alerts = watcher.check_value("gold", 100, "t1")
        threshold_alerts = [a for a in alerts if a.kind == "threshold"]
        assert len(threshold_alerts) == 1

    def test_threshold_no_match(self) -> None:
        watcher = MemoryWatcher(_make_rules())
        alerts = watcher.check_value("hp", 50, "t1")
        threshold_alerts = [a for a in alerts if a.kind == "threshold"]
        assert len(threshold_alerts) == 0

    def test_threshold_custom_severity(self) -> None:
        rules = [ThresholdRule(parameter="x", operator="gt", value=0, severity="high")]
        watcher = MemoryWatcher(rules)
        alerts = watcher.check_value("x", 5, "t")
        assert alerts[0].severity == "high"

    def test_threshold_custom_message(self) -> None:
        rules = [ThresholdRule(parameter="x", operator="gt", value=0,
                               message="X is positive")]
        watcher = MemoryWatcher(rules)
        alerts = watcher.check_value("x", 5, "t")
        assert "X is positive" in alerts[0].description

    def test_rules_from_dict(self) -> None:
        """Rules can be passed as plain dicts."""
        watcher = MemoryWatcher([
            {"parameter": "hp", "operator": "lt", "value": 30, "severity": "high"},
        ])
        alerts = watcher.check_value("hp", 10, "t")
        assert len(alerts) >= 1

    def test_spike_detection(self) -> None:
        """Spike is detected when a sudden large delta occurs."""
        watcher = MemoryWatcher([], spike_threshold=2.5, window_size=20)
        # Feed steady values
        for i in range(15):
            watcher.check_value("hp", 100 - i, f"t{i}")
        # Sudden drop
        alerts = watcher.check_value("hp", 20, "t15")
        spike_alerts = [a for a in alerts if a.kind == "spike"]
        assert len(spike_alerts) >= 1
        assert spike_alerts[0].details["z_score"] >= 2.5

    def test_spike_severity_levels(self) -> None:
        """Severity maps correctly: z>=4 high, z>=3 medium, else low."""
        watcher = MemoryWatcher([], spike_threshold=2.5, window_size=20)
        for i in range(15):
            watcher.check_value("hp", 100 - i, f"t{i}")
        # Large spike should be high severity
        alerts = watcher.check_value("hp", 0, "t15")
        spike_alerts = [a for a in alerts if a.kind == "spike"]
        assert len(spike_alerts) >= 1
        # The z-score should be very high for such a large drop
        assert spike_alerts[0].severity in ("high", "medium")

    def test_spike_below_threshold(self) -> None:
        """No spike alert when deltas are consistent."""
        watcher = MemoryWatcher([], spike_threshold=2.5, window_size=20)
        # Feed perfectly linear values
        for i in range(20):
            alerts = watcher.check_value("hp", 100 - i * 2, f"t{i}")
            spike_alerts = [a for a in alerts if a.kind == "spike"]
            assert len(spike_alerts) == 0

    def test_sliding_window_size(self) -> None:
        """Internal window doesn't grow beyond window_size."""
        watcher = MemoryWatcher([], window_size=5)
        for i in range(20):
            watcher.check_value("x", float(i), f"t{i}")
        assert len(watcher._windows["x"]) <= 5

    def test_check_values_multiple(self) -> None:
        rules = [
            ThresholdRule(parameter="hp", operator="lt", value=30, severity="high"),
            ThresholdRule(parameter="gold", operator="gt", value=5000, severity="medium"),
        ]
        watcher = MemoryWatcher(rules)
        alerts = watcher.check_values({"hp": 10, "gold": 6000}, "t1")
        assert len(alerts) >= 2
        params = {a.parameter for a in alerts}
        assert "hp" in params
        assert "gold" in params

    def test_alerts_accumulate(self) -> None:
        rules = [ThresholdRule(parameter="hp", operator="lt", value=30, severity="high")]
        watcher = MemoryWatcher(rules)
        watcher.check_value("hp", 10, "t1")
        watcher.check_value("hp", 20, "t2")
        assert len(watcher.alerts) >= 2

    def test_clear_alerts(self) -> None:
        rules = [ThresholdRule(parameter="hp", operator="lt", value=30, severity="high")]
        watcher = MemoryWatcher(rules)
        watcher.check_value("hp", 10, "t1")
        assert len(watcher.alerts) >= 1
        watcher.clear_alerts()
        assert len(watcher.alerts) == 0

    def test_alert_summary(self) -> None:
        rules = [
            ThresholdRule(parameter="hp", operator="lt", value=30, severity="high"),
            ThresholdRule(parameter="gold", operator="gt", value=100, severity="low"),
        ]
        watcher = MemoryWatcher(rules)
        watcher.check_value("hp", 10, "t1")
        watcher.check_value("gold", 200, "t2")
        summary = watcher.alert_summary()
        assert summary["total"] >= 2
        assert "threshold" in summary["by_kind"]
        assert "by_severity" in summary
        assert "by_parameter" in summary

    def test_to_dict(self) -> None:
        watcher = MemoryWatcher(_make_rules(), spike_threshold=3.0, window_size=10)
        watcher.check_value("hp", 10, "t1")
        d = watcher.to_dict()
        assert "rules" in d
        assert "spike_threshold" in d
        assert d["spike_threshold"] == 3.0
        assert "window_size" in d
        assert d["window_size"] == 10
        assert "summary" in d
        assert "alerts" in d
        assert len(d["alerts"]) >= 1

    def test_to_dict_json_serializable(self) -> None:
        watcher = MemoryWatcher(_make_rules())
        watcher.check_value("hp", 10, "t1")
        output = json.dumps(watcher.to_dict(), default=str)
        parsed = json.loads(output)
        assert "alerts" in parsed

    def test_to_markdown(self) -> None:
        watcher = MemoryWatcher(_make_rules())
        watcher.check_value("hp", 10, "t1")
        md = watcher.to_markdown()
        assert "# Memory Watcher Report" in md
        assert "Threshold Alerts" in md
        assert "[HIGH]" in md

    def test_to_markdown_no_alerts(self) -> None:
        watcher = MemoryWatcher(_make_rules())
        md = watcher.to_markdown()
        assert "No alerts triggered" in md

    def test_from_strategy_config(self) -> None:
        watcher = MemoryWatcher.from_strategy_config(_SAMPLE_STRATEGY)
        assert len(watcher.rules) == 3
        # priority 10 -> high, priority 5 -> medium, priority 3 -> low
        severities = {r.parameter + "_" + r.operator: r.severity for r in watcher.rules}
        assert severities["hp_lt"] == "high"
        assert severities["hp_gt"] == "medium"
        assert severities["gold_gt"] == "low"

    def test_from_strategy_config_messages(self) -> None:
        watcher = MemoryWatcher.from_strategy_config(_SAMPLE_STRATEGY)
        for rule in watcher.rules:
            assert rule.message  # All rules should have auto-generated messages
            assert "->" in rule.message


# ---------------------------------------------------------------------------
# TestMemoryWatcherCLI
# ---------------------------------------------------------------------------

class TestMemoryWatcherCLI:
    def test_cli_check_markdown(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        csv_path = _write_session_csv(tmp_path, include_spike=True)
        cli_main(["check", str(csv_path)])
        out = capsys.readouterr().out
        assert "Memory Watcher Report" in out

    def test_cli_check_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        csv_path = _write_session_csv(tmp_path, include_spike=True)
        cli_main(["check", str(csv_path), "--format", "json"])
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert "alerts" in parsed
        assert "rules" in parsed

    def test_cli_check_with_rules(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        csv_path = _write_session_csv(tmp_path)
        rules_path = tmp_path / "rules.json"
        rules_path.write_text(json.dumps([
            {"parameter": "hp", "operator": "lt", "value": 80, "severity": "high"},
        ]))
        cli_main(["check", str(csv_path), "--rules", str(rules_path)])
        out = capsys.readouterr().out
        assert "Threshold Alerts" in out

    def test_cli_check_with_strategy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        csv_path = _write_session_csv(tmp_path)
        strat_path = tmp_path / "strategy.json"
        strat_path.write_text(json.dumps(_SAMPLE_STRATEGY))
        cli_main(["check", str(csv_path), "--strategy", str(strat_path)])
        out = capsys.readouterr().out
        assert "Memory Watcher Report" in out

    def test_cli_check_output_file(self, tmp_path: Path) -> None:
        csv_path = _write_session_csv(tmp_path)
        out_file = tmp_path / "report.md"
        cli_main(["check", str(csv_path), "--output", str(out_file)])
        assert out_file.exists()
        content = out_file.read_text()
        assert "Memory Watcher Report" in content

    def test_cli_no_command(self) -> None:
        with pytest.raises(SystemExit):
            cli_main([])

    def test_cli_missing_csv(self) -> None:
        with pytest.raises(SystemExit):
            cli_main(["check", "/nonexistent/session.csv"])
