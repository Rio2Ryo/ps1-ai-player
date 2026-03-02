#!/usr/bin/env python3
"""Alert notification module — send watcher/anomaly alerts to external webhooks.

Supports Slack, Discord, and Telegram webhook integrations with
per-platform message formatting, severity filtering, and batch sends.

Configuration is stored in a JSON file (default: ``alert_notifier.json``
in the log directory) with one entry per webhook backend.

Usage:
    python alert_notifier.py send <session_csv> [--config notifier.json] [--min-severity low]
    python alert_notifier.py test <config_json>
    python alert_notifier.py show-config <config_json>
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from log_config import get_logger

logger = get_logger(__name__)

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WebhookConfig:
    """Configuration for a single webhook endpoint."""

    backend: str  # "slack", "discord", "telegram"
    url: str  # webhook URL (Slack/Discord) or API base for Telegram
    enabled: bool = True
    min_severity: str = "low"  # minimum severity to send
    # Telegram-specific
    chat_id: str = ""
    # Optional display name for this webhook
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "backend": self.backend,
            "url": self.url,
            "enabled": self.enabled,
            "min_severity": self.min_severity,
        }
        if self.chat_id:
            d["chat_id"] = self.chat_id
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookConfig:
        return cls(
            backend=data["backend"],
            url=data["url"],
            enabled=data.get("enabled", True),
            min_severity=data.get("min_severity", "low"),
            chat_id=data.get("chat_id", ""),
            name=data.get("name", ""),
        )


@dataclass
class AlertMessage:
    """A normalized alert message ready for delivery."""

    severity: str  # "low", "medium", "high"
    title: str
    description: str
    source: str = ""  # "watcher" or "anomaly"
    parameter: str = ""
    timestamp: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "parameter": self.parameter,
            "timestamp": self.timestamp,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Message formatting per backend
# ---------------------------------------------------------------------------

_SEVERITY_EMOJI = {"high": "\u26a0\ufe0f", "medium": "\u26a1", "low": "\u2139\ufe0f"}


def _format_slack(alerts: list[AlertMessage]) -> dict[str, Any]:
    """Format alerts as a Slack incoming webhook payload."""
    blocks: list[dict] = []
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"PS1 AI Player — {len(alerts)} Alert(s)"},
    })

    for a in alerts:
        emoji = _SEVERITY_EMOJI.get(a.severity, "")
        text = f"{emoji} *[{a.severity.upper()}]* {a.title}\n{a.description}"
        if a.parameter:
            text += f"\n_Parameter:_ `{a.parameter}`"
        if a.timestamp:
            text += f"\n_Time:_ {a.timestamp}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    return {"blocks": blocks}


def _format_discord(alerts: list[AlertMessage]) -> dict[str, Any]:
    """Format alerts as a Discord webhook payload."""
    embeds: list[dict] = []
    color_map = {"high": 0xE53935, "medium": 0xFFA726, "low": 0x42A5F5}

    for a in alerts:
        emoji = _SEVERITY_EMOJI.get(a.severity, "")
        embed: dict[str, Any] = {
            "title": f"{emoji} [{a.severity.upper()}] {a.title}",
            "description": a.description,
            "color": color_map.get(a.severity, 0x9E9E9E),
        }
        fields = []
        if a.parameter:
            fields.append({"name": "Parameter", "value": a.parameter, "inline": True})
        if a.timestamp:
            fields.append({"name": "Time", "value": a.timestamp, "inline": True})
        if a.source:
            fields.append({"name": "Source", "value": a.source, "inline": True})
        if fields:
            embed["fields"] = fields
        embeds.append(embed)

    # Discord allows max 10 embeds per message
    return {"content": f"**PS1 AI Player — {len(alerts)} Alert(s)**", "embeds": embeds[:10]}


def _format_telegram(alerts: list[AlertMessage]) -> str:
    """Format alerts as Telegram HTML message text."""
    lines = [f"<b>PS1 AI Player — {len(alerts)} Alert(s)</b>", ""]
    for a in alerts:
        emoji = _SEVERITY_EMOJI.get(a.severity, "")
        lines.append(f"{emoji} <b>[{a.severity.upper()}]</b> {a.title}")
        lines.append(a.description)
        if a.parameter:
            lines.append(f"<i>Parameter:</i> <code>{a.parameter}</code>")
        if a.timestamp:
            lines.append(f"<i>Time:</i> {a.timestamp}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AlertNotifier
# ---------------------------------------------------------------------------

class AlertNotifier:
    """Send alert messages to configured webhook endpoints.

    Parameters
    ----------
    webhooks : list[WebhookConfig]
        One or more webhook configurations.
    """

    def __init__(self, webhooks: list[WebhookConfig] | None = None) -> None:
        self.webhooks: list[WebhookConfig] = webhooks or []
        self._send_log: list[dict[str, Any]] = []

    # -- Configuration -------------------------------------------------------

    @classmethod
    def from_config_file(cls, path: Path) -> AlertNotifier:
        """Load notifier configuration from a JSON file."""
        data = json.loads(path.read_text())
        hooks = data if isinstance(data, list) else data.get("webhooks", [])
        webhooks = [WebhookConfig.from_dict(h) for h in hooks]
        return cls(webhooks)

    def save_config(self, path: Path) -> None:
        """Save current webhook configuration to a JSON file."""
        data = {"webhooks": [w.to_dict() for w in self.webhooks]}
        path.write_text(json.dumps(data, indent=2))
        logger.info("Saved notifier config: %s", path)

    def add_webhook(self, webhook: WebhookConfig) -> None:
        """Add a webhook configuration."""
        self.webhooks.append(webhook)

    # -- Alert conversion ----------------------------------------------------

    @staticmethod
    def from_watcher_alerts(alerts: list) -> list[AlertMessage]:
        """Convert WatcherAlert objects (or dicts) to AlertMessage list."""
        messages: list[AlertMessage] = []
        for a in alerts:
            d = a.to_dict() if hasattr(a, "to_dict") else a
            messages.append(AlertMessage(
                severity=d.get("severity", "medium"),
                title=f"{d.get('kind', 'alert').title()}: {d.get('parameter', '?')}",
                description=d.get("description", ""),
                source="watcher",
                parameter=d.get("parameter", ""),
                timestamp=d.get("timestamp", ""),
                details=d.get("details", {}),
            ))
        return messages

    @staticmethod
    def from_anomalies(anomalies: list) -> list[AlertMessage]:
        """Convert Anomaly objects (or dicts) to AlertMessage list."""
        messages: list[AlertMessage] = []
        for a in anomalies:
            d = a.to_dict() if hasattr(a, "to_dict") else a
            messages.append(AlertMessage(
                severity=d.get("severity", "medium"),
                title=f"Anomaly ({d.get('kind', '?')}): {d.get('session', '?')}",
                description=d.get("description", ""),
                source="anomaly",
                parameter=d.get("details", {}).get("parameter", ""),
                timestamp="",
                details=d.get("details", {}),
            ))
        return messages

    # -- Filtering -----------------------------------------------------------

    def filter_by_severity(
        self,
        alerts: list[AlertMessage],
        min_severity: str = "low",
    ) -> list[AlertMessage]:
        """Filter alerts to those at or above *min_severity*."""
        min_level = _SEVERITY_ORDER.get(min_severity, 0)
        return [a for a in alerts if _SEVERITY_ORDER.get(a.severity, 0) >= min_level]

    # -- Sending -------------------------------------------------------------

    def _post_json(self, url: str, payload: dict | str, *, timeout: int = 10) -> bool:
        """POST JSON payload to a URL. Returns True on success."""
        body = json.dumps(payload).encode() if isinstance(payload, dict) else payload.encode()
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=timeout) as resp:
                status = resp.status
                logger.info("Webhook POST %s → %d", url, status)
                return 200 <= status < 300
        except (URLError, OSError, TimeoutError) as exc:
            logger.error("Webhook POST failed: %s → %s", url, exc)
            return False

    def send_to_webhook(
        self,
        webhook: WebhookConfig,
        alerts: list[AlertMessage],
    ) -> bool:
        """Send alerts to a single webhook. Returns True on success."""
        filtered = self.filter_by_severity(alerts, webhook.min_severity)
        if not filtered:
            logger.info("No alerts above %s for %s — skipping", webhook.min_severity, webhook.name or webhook.backend)
            return True

        success = False
        if webhook.backend == "slack":
            payload = _format_slack(filtered)
            success = self._post_json(webhook.url, payload)
        elif webhook.backend == "discord":
            payload = _format_discord(filtered)
            success = self._post_json(webhook.url, payload)
        elif webhook.backend == "telegram":
            text = _format_telegram(filtered)
            payload = {
                "chat_id": webhook.chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
            url = f"{webhook.url}/sendMessage" if "/sendMessage" not in webhook.url else webhook.url
            success = self._post_json(url, payload)
        else:
            logger.warning("Unknown backend: %s", webhook.backend)

        self._send_log.append({
            "webhook": webhook.name or webhook.backend,
            "backend": webhook.backend,
            "alerts_sent": len(filtered),
            "success": success,
            "timestamp": datetime.now().isoformat(),
        })
        return success

    def send_all(self, alerts: list[AlertMessage]) -> dict[str, Any]:
        """Send alerts to all enabled webhooks.

        Returns a summary dict with per-webhook results.
        """
        results: list[dict[str, Any]] = []
        for wh in self.webhooks:
            if not wh.enabled:
                results.append({
                    "webhook": wh.name or wh.backend,
                    "skipped": True,
                    "reason": "disabled",
                })
                continue
            ok = self.send_to_webhook(wh, alerts)
            results.append({
                "webhook": wh.name or wh.backend,
                "success": ok,
                "alerts_sent": len(self.filter_by_severity(alerts, wh.min_severity)),
            })
        return {
            "total_alerts": len(alerts),
            "webhooks": results,
            "timestamp": datetime.now().isoformat(),
        }

    # -- Output --------------------------------------------------------------

    @property
    def send_log(self) -> list[dict[str, Any]]:
        """History of send attempts."""
        return list(self._send_log)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable summary."""
        return {
            "webhooks": [w.to_dict() for w in self.webhooks],
            "send_log": self._send_log,
        }

    def to_markdown(self) -> str:
        """Markdown report of notifier configuration and send history."""
        lines = [
            "# Alert Notifier Report",
            "",
            f"**Webhooks configured:** {len(self.webhooks)}",
            "",
        ]

        if self.webhooks:
            lines.append("## Webhook Configuration")
            lines.append("")
            lines.append("| Name | Backend | Enabled | Min Severity |")
            lines.append("|------|---------|---------|-------------|")
            for w in self.webhooks:
                name = w.name or "(unnamed)"
                lines.append(f"| {name} | {w.backend} | {w.enabled} | {w.min_severity} |")
            lines.append("")

        if self._send_log:
            lines.append("## Send History")
            lines.append("")
            for entry in self._send_log:
                status = "OK" if entry.get("success") else "FAILED"
                lines.append(
                    f"- [{status}] {entry['webhook']}: "
                    f"{entry.get('alerts_sent', 0)} alerts @ {entry.get('timestamp', '')}"
                )
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Alert notification — send watcher/anomaly alerts to webhooks",
    )
    sub = parser.add_subparsers(dest="command")

    # send
    p_send = sub.add_parser("send", help="Detect alerts and send to webhooks")
    p_send.add_argument("csv_path", type=Path, help="Session CSV file")
    p_send.add_argument("--config", type=Path, default=None, help="Notifier config JSON")
    p_send.add_argument(
        "--min-severity", choices=["low", "medium", "high"], default="low",
        help="Minimum severity to send",
    )

    # test
    p_test = sub.add_parser("test", help="Send a test alert to all configured webhooks")
    p_test.add_argument("config", type=Path, help="Notifier config JSON")

    # show-config
    p_show = sub.add_parser("show-config", help="Display webhook configuration")
    p_show.add_argument("config", type=Path, help="Notifier config JSON")

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    if args.command == "show-config":
        notifier = AlertNotifier.from_config_file(args.config)
        print(notifier.to_markdown())
        return

    if args.command == "test":
        notifier = AlertNotifier.from_config_file(args.config)
        test_alert = AlertMessage(
            severity="low",
            title="Test Alert",
            description="This is a test alert from PS1 AI Player alert_notifier.",
            source="test",
            timestamp=datetime.now().isoformat(),
        )
        result = notifier.send_all([test_alert])
        print(json.dumps(result, indent=2))
        return

    if args.command == "send":
        from memory_watcher import MemoryWatcher, ThresholdRule
        from session_replay import SessionData

        session = SessionData.from_log_path(args.csv_path)

        # Run watcher to detect alerts
        watcher = MemoryWatcher(rules=[], spike_threshold=2.5)
        for _, row in session.df.iterrows():
            vals = {p: float(row[p]) for p in session.parameters if p in row}
            ts = str(row.get("timestamp", ""))
            watcher.check_values(vals, ts)

        watcher_alerts = watcher.alerts

        # Convert to AlertMessages
        messages = AlertNotifier.from_watcher_alerts(watcher_alerts)

        # Load config
        if args.config:
            notifier = AlertNotifier.from_config_file(args.config)
        else:
            # Try default location
            default_cfg = Path("alert_notifier.json")
            if default_cfg.exists():
                notifier = AlertNotifier.from_config_file(default_cfg)
            else:
                print("No config file specified and alert_notifier.json not found.")
                print("Create one with webhook configuration. Example:")
                print(json.dumps({"webhooks": [{
                    "backend": "slack",
                    "url": "https://hooks.slack.com/services/...",
                    "enabled": True,
                    "min_severity": "medium",
                    "name": "my-slack",
                }]}, indent=2))
                raise SystemExit(1)

        # Filter and send
        messages = notifier.filter_by_severity(messages, args.min_severity)
        if not messages:
            print(f"No alerts at or above severity '{args.min_severity}'.")
            return

        result = notifier.send_all(messages)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
