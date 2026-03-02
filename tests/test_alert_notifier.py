"""Tests for alert_notifier.py — AlertNotifier, formatting, and CLI."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alert_notifier import (
    AlertMessage,
    AlertNotifier,
    WebhookConfig,
    _format_discord,
    _format_slack,
    _format_telegram,
    main as cli_main,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_alerts() -> list[AlertMessage]:
    """A list of sample AlertMessages at various severities."""
    return [
        AlertMessage(
            severity="high", title="HP Critical", description="HP dropped below 10",
            source="watcher", parameter="hp", timestamp="2025-01-01T12:00:30",
        ),
        AlertMessage(
            severity="medium", title="Gold Spike", description="Gold spiked by 500",
            source="watcher", parameter="gold", timestamp="2025-01-01T12:00:45",
        ),
        AlertMessage(
            severity="low", title="Score Milestone", description="Score passed 1000",
            source="anomaly", parameter="score", timestamp="2025-01-01T12:01:00",
        ),
    ]


@pytest.fixture
def slack_webhook() -> WebhookConfig:
    return WebhookConfig(backend="slack", url="https://hooks.slack.com/test", name="test-slack")


@pytest.fixture
def discord_webhook() -> WebhookConfig:
    return WebhookConfig(backend="discord", url="https://discord.com/api/webhooks/test", name="test-discord")


@pytest.fixture
def telegram_webhook() -> WebhookConfig:
    return WebhookConfig(
        backend="telegram", url="https://api.telegram.org/bot123",
        chat_id="456", name="test-telegram",
    )


@pytest.fixture
def notifier(slack_webhook, discord_webhook, telegram_webhook) -> AlertNotifier:
    return AlertNotifier([slack_webhook, discord_webhook, telegram_webhook])


@pytest.fixture
def config_file(tmp_path, slack_webhook, discord_webhook) -> Path:
    path = tmp_path / "notifier.json"
    data = {"webhooks": [slack_webhook.to_dict(), discord_webhook.to_dict()]}
    path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------------------
# TestWebhookConfig
# ---------------------------------------------------------------------------

class TestWebhookConfig:
    def test_to_dict(self, slack_webhook):
        d = slack_webhook.to_dict()
        assert d["backend"] == "slack"
        assert d["url"] == "https://hooks.slack.com/test"
        assert d["enabled"] is True

    def test_from_dict(self):
        wh = WebhookConfig.from_dict({
            "backend": "discord",
            "url": "https://discord.com/test",
            "min_severity": "high",
        })
        assert wh.backend == "discord"
        assert wh.min_severity == "high"
        assert wh.enabled is True

    def test_telegram_chat_id_in_dict(self, telegram_webhook):
        d = telegram_webhook.to_dict()
        assert d["chat_id"] == "456"


# ---------------------------------------------------------------------------
# TestAlertMessage
# ---------------------------------------------------------------------------

class TestAlertMessage:
    def test_to_dict(self, sample_alerts):
        d = sample_alerts[0].to_dict()
        assert d["severity"] == "high"
        assert d["title"] == "HP Critical"
        assert d["source"] == "watcher"
        assert d["parameter"] == "hp"


# ---------------------------------------------------------------------------
# TestFormatting
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_format_slack(self, sample_alerts):
        payload = _format_slack(sample_alerts)
        assert "blocks" in payload
        # Header + 3 alerts
        assert len(payload["blocks"]) == 4
        assert payload["blocks"][0]["type"] == "header"
        assert "3 Alert(s)" in payload["blocks"][0]["text"]["text"]

    def test_format_discord(self, sample_alerts):
        payload = _format_discord(sample_alerts)
        assert "embeds" in payload
        assert len(payload["embeds"]) == 3
        assert "content" in payload
        assert payload["embeds"][0]["color"] == 0xE53935  # high = red

    def test_format_telegram(self, sample_alerts):
        text = _format_telegram(sample_alerts)
        assert "<b>PS1 AI Player" in text
        assert "[HIGH]" in text
        assert "HP Critical" in text
        assert "<code>hp</code>" in text

    def test_format_slack_empty(self):
        payload = _format_slack([])
        assert "blocks" in payload
        assert len(payload["blocks"]) == 1  # just header


# ---------------------------------------------------------------------------
# TestAlertNotifier
# ---------------------------------------------------------------------------

class TestAlertNotifier:
    def test_filter_by_severity_low(self, notifier, sample_alerts):
        filtered = notifier.filter_by_severity(sample_alerts, "low")
        assert len(filtered) == 3

    def test_filter_by_severity_medium(self, notifier, sample_alerts):
        filtered = notifier.filter_by_severity(sample_alerts, "medium")
        assert len(filtered) == 2
        severities = {a.severity for a in filtered}
        assert "low" not in severities

    def test_filter_by_severity_high(self, notifier, sample_alerts):
        filtered = notifier.filter_by_severity(sample_alerts, "high")
        assert len(filtered) == 1
        assert filtered[0].severity == "high"

    def test_from_watcher_alerts(self):
        watcher_dicts = [
            {"kind": "threshold", "severity": "high", "parameter": "hp",
             "value": 5, "description": "HP < 10", "timestamp": "2025-01-01T12:00:00",
             "details": {}},
        ]
        msgs = AlertNotifier.from_watcher_alerts(watcher_dicts)
        assert len(msgs) == 1
        assert msgs[0].source == "watcher"
        assert msgs[0].severity == "high"
        assert "hp" in msgs[0].parameter

    def test_from_anomalies(self):
        anomaly_dicts = [
            {"kind": "spike", "severity": "medium", "session": "20250101_120000",
             "description": "Gold spiked", "details": {"parameter": "gold"}},
        ]
        msgs = AlertNotifier.from_anomalies(anomaly_dicts)
        assert len(msgs) == 1
        assert msgs[0].source == "anomaly"
        assert "spike" in msgs[0].title.lower()

    @patch.object(AlertNotifier, "_post_json", return_value=True)
    def test_send_to_slack(self, mock_post, notifier, slack_webhook, sample_alerts):
        ok = notifier.send_to_webhook(slack_webhook, sample_alerts)
        assert ok is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "hooks.slack.com" in call_args[0][0]

    @patch.object(AlertNotifier, "_post_json", return_value=True)
    def test_send_to_discord(self, mock_post, notifier, discord_webhook, sample_alerts):
        ok = notifier.send_to_webhook(discord_webhook, sample_alerts)
        assert ok is True
        mock_post.assert_called_once()

    @patch.object(AlertNotifier, "_post_json", return_value=True)
    def test_send_to_telegram(self, mock_post, notifier, telegram_webhook, sample_alerts):
        ok = notifier.send_to_webhook(telegram_webhook, sample_alerts)
        assert ok is True
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "/sendMessage" in call_url

    @patch.object(AlertNotifier, "_post_json", return_value=True)
    def test_send_all(self, mock_post, notifier, sample_alerts):
        result = notifier.send_all(sample_alerts)
        assert result["total_alerts"] == 3
        assert len(result["webhooks"]) == 3
        assert all(w.get("success", False) for w in result["webhooks"])

    @patch.object(AlertNotifier, "_post_json", return_value=True)
    def test_send_all_disabled_webhook(self, mock_post, sample_alerts):
        wh = WebhookConfig(backend="slack", url="https://test", enabled=False)
        n = AlertNotifier([wh])
        result = n.send_all(sample_alerts)
        assert result["webhooks"][0]["skipped"] is True
        mock_post.assert_not_called()

    @patch.object(AlertNotifier, "_post_json", return_value=False)
    def test_send_failure(self, mock_post, notifier, slack_webhook, sample_alerts):
        ok = notifier.send_to_webhook(slack_webhook, sample_alerts)
        assert ok is False

    def test_send_log(self, notifier, slack_webhook, sample_alerts):
        with patch.object(AlertNotifier, "_post_json", return_value=True):
            notifier.send_to_webhook(slack_webhook, sample_alerts)
        assert len(notifier.send_log) == 1
        assert notifier.send_log[0]["success"] is True

    def test_severity_filter_on_webhook(self, sample_alerts):
        wh = WebhookConfig(backend="slack", url="https://test", min_severity="high")
        n = AlertNotifier([wh])
        with patch.object(AlertNotifier, "_post_json", return_value=True) as mock:
            n.send_all(sample_alerts)
            # Only 1 high-severity alert should be sent
            call_payload = mock.call_args[0][1]
            # Slack blocks: header + 1 alert = 2
            assert len(call_payload["blocks"]) == 2

    def test_from_config_file(self, config_file):
        n = AlertNotifier.from_config_file(config_file)
        assert len(n.webhooks) == 2
        assert n.webhooks[0].backend == "slack"

    def test_save_config(self, tmp_path, notifier):
        path = tmp_path / "out.json"
        notifier.save_config(path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data["webhooks"]) == 3

    def test_to_dict(self, notifier):
        d = notifier.to_dict()
        assert "webhooks" in d
        assert "send_log" in d
        json.dumps(d)  # must be serialisable

    def test_to_markdown(self, notifier):
        md = notifier.to_markdown()
        assert "# Alert Notifier Report" in md
        assert "Webhook Configuration" in md
        assert "slack" in md


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------

class TestAlertNotifierCLI:
    def test_cli_no_command(self):
        with pytest.raises(SystemExit):
            cli_main([])

    def test_cli_show_config(self, config_file, capsys):
        cli_main(["show-config", str(config_file)])
        out = capsys.readouterr().out
        assert "Alert Notifier Report" in out
        assert "slack" in out

    @patch.object(AlertNotifier, "_post_json", return_value=True)
    def test_cli_test(self, mock_post, config_file, capsys):
        cli_main(["test", str(config_file)])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "total_alerts" in data
        assert data["total_alerts"] == 1
