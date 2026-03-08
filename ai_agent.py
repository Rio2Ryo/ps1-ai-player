#!/usr/bin/env python3
"""PS1 AI Player Agent.

Captures DuckStation screen, sends to GPT-4o Vision for analysis,
and executes the returned actions via keyboard input. Simultaneously
reads memory parameters and logs everything to CSV.
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from log_config import get_logger

logger = get_logger(__name__)

MAX_API_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # seconds, doubles each retry
DUCKSTATION_WAIT_TIMEOUT = 60  # seconds to wait for DuckStation to start
DUCKSTATION_POLL_INTERVAL = 3  # seconds between PID checks
ACTION_HISTORY_SIZE = 10  # number of recent steps to include as context
TREND_WINDOW_SIZE = 20  # number of steps to track for trend analysis

# GPT-4o pricing per 1M tokens (as of 2024)
COST_PER_1M_INPUT = 2.50
COST_PER_1M_OUTPUT = 10.00

# Game state classification labels
GAME_STATE_MENU = "menu"
GAME_STATE_GAMEPLAY = "gameplay"
GAME_STATE_DIALOG = "dialog"
GAME_STATE_LOADING = "loading"
GAME_STATE_PAUSE = "pause"
GAME_STATE_UNKNOWN = "unknown"

import mss
import mss.tools
from PIL import Image
from pynput.keyboard import Controller as KbdController
from pynput.keyboard import Key

from address_manager import AddressManager
from memory_scanner import MemoryScanner


# ---------------------------------------------------------------------------
# Action History (sliding window for GPT-4o context)
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    """One step of agent history."""

    step: int
    action: list[str]
    reasoning: str
    observations: str
    parameters: dict[str, Any] = field(default_factory=dict)


class ActionHistory:
    """Maintains a sliding window of recent agent actions for GPT-4o context."""

    def __init__(self, max_size: int = ACTION_HISTORY_SIZE) -> None:
        self._max_size = max_size
        self._records: list[ActionRecord] = []

    def add(self, record: ActionRecord) -> None:
        self._records.append(record)
        if len(self._records) > self._max_size:
            self._records = self._records[-self._max_size:]

    def format_for_prompt(self) -> str:
        """Format history as text for the GPT-4o system prompt."""
        if not self._records:
            return ""

        lines = [f"Recent action history (last {len(self._records)} steps):"]
        for rec in self._records:
            action_str = ", ".join(rec.action) if rec.action else "none"
            param_str = ""
            if rec.parameters:
                param_parts = [f"{k}={v}" for k, v in rec.parameters.items()]
                param_str = f" | Params: {', '.join(param_parts)}"
            lines.append(
                f"  Step {rec.step}: [{action_str}] "
                f"Reason: {rec.reasoning[:80]}"
                f"{param_str}"
            )
        return "\n".join(lines)

    def to_dict(self) -> list[dict[str, Any]]:
        """Convert all records to a JSON-serializable list of dicts."""
        return [
            {
                "step": rec.step,
                "action": list(rec.action),
                "reasoning": rec.reasoning,
                "observations": rec.observations,
                "parameters": dict(rec.parameters),
            }
            for rec in self._records
        ]

    def save(self, path: Path) -> Path:
        """Save history to a JSON file. Returns the path written."""
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return path

    @classmethod
    def load(cls, path: Path, max_size: int = ACTION_HISTORY_SIZE) -> ActionHistory:
        """Load history from a JSON file saved by :meth:`save`.

        Returns an empty ActionHistory if *path* does not exist.
        Only the last *max_size* records are kept.
        """
        hist = cls(max_size=max_size)
        path = Path(path)
        if not path.exists():
            return hist
        data = json.loads(path.read_text())
        # Keep only the tail
        for entry in data[-max_size:]:
            hist.add(ActionRecord(
                step=entry.get("step", 0),
                action=entry.get("action", []),
                reasoning=entry.get("reasoning", ""),
                observations=entry.get("observations", ""),
                parameters=entry.get("parameters", {}),
            ))
        return hist

    @classmethod
    def from_session_json(cls, session_json_path: Path, max_size: int = ACTION_HISTORY_SIZE) -> ActionHistory:
        """Not supported — .session.json has a different structure.

        Use :meth:`load` with a file produced by :meth:`save` instead.
        """
        raise NotImplementedError(
            "from_session_json is not supported. "
            "Use ActionHistory.load() with a file saved by ActionHistory.save()."
        )

    @property
    def records(self) -> list[ActionRecord]:
        return list(self._records)


# ---------------------------------------------------------------------------
# API Cost Tracker
# ---------------------------------------------------------------------------

class CostTracker:
    """Track OpenAI API token usage and estimated costs."""

    def __init__(self) -> None:
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.step_costs: list[dict[str, Any]] = []

    def record(self, step: int, input_tokens: int, output_tokens: int) -> float:
        """Record token usage for one API call. Returns estimated cost in USD."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        cost = (
            input_tokens / 1_000_000 * COST_PER_1M_INPUT
            + output_tokens / 1_000_000 * COST_PER_1M_OUTPUT
        )
        self.step_costs.append({
            "step": step,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        })
        return cost

    @property
    def total_cost(self) -> float:
        return (
            self.total_input_tokens / 1_000_000 * COST_PER_1M_INPUT
            + self.total_output_tokens / 1_000_000 * COST_PER_1M_OUTPUT
        )

    def summary(self) -> dict[str, Any]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "api_calls": len(self.step_costs),
            "avg_cost_per_call": round(
                self.total_cost / max(len(self.step_costs), 1), 6
            ),
        }


# ---------------------------------------------------------------------------
# Game State Tracker
# ---------------------------------------------------------------------------

class GameStateTracker:
    """Track game screen state transitions for context-aware AI decisions.

    Classifies screens into states (menu, gameplay, dialog, loading, pause)
    based on GPT-4o observations and parameter change patterns. Maintains
    a state transition history for the AI prompt.
    """

    def __init__(self, max_history: int = 20) -> None:
        self._current_state: str = GAME_STATE_UNKNOWN
        self._previous_state: str = GAME_STATE_UNKNOWN
        self._state_history: list[dict[str, Any]] = []
        self._max_history = max_history
        self._state_duration: int = 0  # ticks in current state
        self._transition_counts: dict[str, int] = {}

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def state_duration(self) -> int:
        return self._state_duration

    def classify_state(
        self,
        observations: str,
        params_changed: bool,
        action_had_effect: bool,
    ) -> str:
        """Classify the current game state from observations and parameter data.

        Args:
            observations: GPT-4o observation text from the current step.
            params_changed: Whether any memory parameters changed since last step.
            action_had_effect: Whether the last action produced visible change.

        Returns:
            Classified state string.
        """
        obs_lower = observations.lower()

        # Keyword-based classification from GPT-4o observations
        if any(kw in obs_lower for kw in ("loading", "please wait", "now loading")):
            return GAME_STATE_LOADING
        if any(kw in obs_lower for kw in ("pause", "paused", "resume")):
            return GAME_STATE_PAUSE
        if any(kw in obs_lower for kw in (
            "menu", "option", "select", "cursor", "choice", "title screen",
            "start game", "new game", "continue", "save", "load",
        )):
            return GAME_STATE_MENU
        if any(kw in obs_lower for kw in (
            "dialog", "dialogue", "speech", "text box", "conversation",
            "character speaking", "npc",
        )):
            return GAME_STATE_DIALOG

        # If parameters are changing, likely in active gameplay
        if params_changed:
            return GAME_STATE_GAMEPLAY

        # If no params changed and no action effect, could be loading or stuck
        if not action_had_effect and not params_changed:
            # If we've been stuck for a while, might be loading
            if self._state_duration > 3 and self._current_state == GAME_STATE_UNKNOWN:
                return GAME_STATE_LOADING
            return self._current_state  # Keep current state

        return GAME_STATE_GAMEPLAY

    def update(
        self,
        step: int,
        observations: str,
        params_changed: bool,
        action_had_effect: bool,
    ) -> str:
        """Update state tracking with new step data.

        Args:
            step: Current step number.
            observations: GPT-4o observation text.
            params_changed: Whether parameters changed.
            action_had_effect: Whether the action had visible effect.

        Returns:
            The new current state.
        """
        new_state = self.classify_state(observations, params_changed, action_had_effect)

        if new_state != self._current_state:
            self._previous_state = self._current_state
            transition_key = f"{self._current_state}->{new_state}"
            self._transition_counts[transition_key] = (
                self._transition_counts.get(transition_key, 0) + 1
            )
            self._state_history.append({
                "step": step,
                "from": self._current_state,
                "to": new_state,
                "duration": self._state_duration,
            })
            if len(self._state_history) > self._max_history:
                self._state_history = self._state_history[-self._max_history:]
            self._current_state = new_state
            self._state_duration = 0
            logger.info("State transition: %s -> %s (step %d)", self._previous_state, new_state, step)
        else:
            self._state_duration += 1

        return self._current_state

    def format_for_prompt(self) -> str:
        """Format state info for the GPT-4o system prompt."""
        lines = [f"Current game state: {self._current_state} (for {self._state_duration} steps)"]
        if self._previous_state != GAME_STATE_UNKNOWN:
            lines.append(f"Previous state: {self._previous_state}")

        # State-specific hints
        if self._current_state == GAME_STATE_MENU:
            lines.append("Hint: Navigate with D-pad, confirm with Z/Circle.")
        elif self._current_state == GAME_STATE_DIALOG:
            lines.append("Hint: Advance dialog with Z/Circle, skip with X/Cross.")
        elif self._current_state == GAME_STATE_LOADING:
            lines.append("Hint: Wait for loading to complete. No action needed.")
        elif self._current_state == GAME_STATE_PAUSE:
            lines.append("Hint: Press Start to resume, or navigate pause menu.")

        if self._state_duration > 5 and self._current_state == GAME_STATE_GAMEPLAY:
            lines.append(
                f"Note: Been in gameplay for {self._state_duration} steps. "
                "Consider changing strategy if parameters are stagnant."
            )

        return "\n".join(lines)

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for logging/serialization."""
        return {
            "current_state": self._current_state,
            "state_duration": self._state_duration,
            "transitions": len(self._state_history),
            "transition_counts": dict(self._transition_counts),
        }


# ---------------------------------------------------------------------------
# Parameter Trend Analyzer
# ---------------------------------------------------------------------------

class ParameterTrendAnalyzer:
    """Analyze real-time parameter trends to detect changes and stagnation.

    Tracks a sliding window of parameter values and computes:
    - Direction: rising / falling / stable / volatile
    - Velocity: rate of change per step
    - Significant changes: jumps that exceed a threshold
    """

    def __init__(self, window_size: int = TREND_WINDOW_SIZE) -> None:
        self._window_size = window_size
        self._history: dict[str, list[float]] = {}
        self._previous: dict[str, float] = {}

    def record(self, params: dict[str, int | float]) -> dict[str, dict[str, Any]]:
        """Record a new set of parameter values and compute trends.

        Args:
            params: Current parameter name→value mapping.

        Returns:
            Dict mapping parameter name to trend info dict.
        """
        trends: dict[str, dict[str, Any]] = {}

        for name, value in params.items():
            fval = float(value)

            if name not in self._history:
                self._history[name] = []

            self._history[name].append(fval)
            if len(self._history[name]) > self._window_size:
                self._history[name] = self._history[name][-self._window_size:]

            history = self._history[name]
            prev = self._previous.get(name)

            # Compute delta
            delta = fval - prev if prev is not None else 0.0

            # Compute trend direction from window
            direction = "stable"
            velocity = 0.0
            if len(history) >= 3:
                diffs = [history[i] - history[i - 1] for i in range(1, len(history))]
                velocity = sum(diffs) / len(diffs)
                positive = sum(1 for d in diffs if d > 0)
                negative = sum(1 for d in diffs if d < 0)
                total = len(diffs)

                if positive > total * 0.6:
                    direction = "rising"
                elif negative > total * 0.6:
                    direction = "falling"
                elif positive > total * 0.3 and negative > total * 0.3:
                    direction = "volatile"
                else:
                    direction = "stable"

            # Detect significant jumps (> 10% of range or > 5 absolute)
            significant = False
            if len(history) >= 2:
                val_range = max(history) - min(history)
                threshold = max(val_range * 0.1, 5.0)
                if abs(delta) > threshold:
                    significant = True

            trends[name] = {
                "value": fval,
                "delta": round(delta, 2),
                "direction": direction,
                "velocity": round(velocity, 2),
                "significant_change": significant,
                "window_size": len(history),
            }

            self._previous[name] = fval

        return trends

    def format_for_prompt(self, trends: dict[str, dict[str, Any]]) -> str:
        """Format trend analysis for the GPT-4o system prompt.

        Args:
            trends: Output from record().

        Returns:
            Human-readable trend summary.
        """
        if not trends:
            return ""

        lines = ["Parameter trends:"]
        alerts = []

        for name, info in trends.items():
            arrow = {
                "rising": "↑",
                "falling": "↓",
                "stable": "→",
                "volatile": "~",
            }.get(info["direction"], "?")
            delta_str = f"{info['delta']:+.1f}" if info["delta"] != 0 else "0"
            lines.append(
                f"  {name}: {info['value']:.0f} {arrow} ({delta_str}/step, {info['direction']})"
            )
            if info["significant_change"]:
                alerts.append(f"  ⚠ {name} changed significantly: {info['delta']:+.1f}")

        if alerts:
            lines.append("Alerts:")
            lines.extend(alerts)

        return "\n".join(lines)

    def params_changed(self, trends: dict[str, dict[str, Any]]) -> bool:
        """Check if any parameter changed from last step."""
        return any(info["delta"] != 0 for info in trends.values())

    def get_stagnant_params(self, trends: dict[str, dict[str, Any]]) -> list[str]:
        """Return parameter names that have been stable for the full window."""
        return [
            name for name, info in trends.items()
            if info["direction"] == "stable" and info["window_size"] >= self._window_size
        ]


# ---------------------------------------------------------------------------
# Adaptive Strategy Engine
# ---------------------------------------------------------------------------

@dataclass
class StrategyThreshold:
    """A threshold condition that triggers a strategy switch."""
    parameter: str
    operator: str  # "lt", "gt", "le", "ge"
    value: float
    target_strategy: str
    priority: int = 0  # higher = evaluated first

    def evaluate(self, params: dict[str, int | float]) -> bool:
        """Check if this threshold is triggered by the current params."""
        if self.parameter not in params:
            return False
        pval = float(params[self.parameter])
        if self.operator == "lt":
            return pval < self.value
        elif self.operator == "gt":
            return pval > self.value
        elif self.operator == "le":
            return pval <= self.value
        elif self.operator == "ge":
            return pval >= self.value
        return False


class AdaptiveStrategyEngine:
    """Dynamically switch AI strategy based on game parameter thresholds.

    When the agent runs in 'balanced' mode, this engine evaluates parameter
    thresholds and selects the most appropriate strategy for the current
    game state. Falls back to the configured default when no threshold fires.
    """

    GENRE_PRESETS: dict[str, str] = {
        "themepark": "config/strategies/themepark.json",
        "rpg": "config/strategies/rpg.json",
        "action": "config/strategies/action.json",
        "sports": "config/strategies/sports.json",
        "puzzle": "config/strategies/puzzle.json",
        "survival_horror": "config/strategies/survival_horror.json",
        "fighting": "config/strategies/fighting.json",
    }

    # Default thresholds for theme park management games
    DEFAULT_THRESHOLDS: list[dict[str, Any]] = [
        {"parameter": "money", "operator": "lt", "value": 1000, "target_strategy": "cost_reduction", "priority": 10},
        {"parameter": "satisfaction", "operator": "lt", "value": 30, "target_strategy": "satisfaction", "priority": 9},
        {"parameter": "visitors", "operator": "lt", "value": 15, "target_strategy": "expansion", "priority": 7},
        {"parameter": "nausea", "operator": "gt", "value": 70, "target_strategy": "satisfaction", "priority": 8},
        {"parameter": "hunger", "operator": "gt", "value": 80, "target_strategy": "satisfaction", "priority": 6},
        {"parameter": "money", "operator": "gt", "value": 8000, "target_strategy": "expansion", "priority": 5},
    ]

    def __init__(
        self,
        default_strategy: str = "balanced",
        thresholds: list[dict[str, Any]] | None = None,
    ) -> None:
        self._default_strategy = default_strategy
        self._current_strategy = default_strategy
        self._previous_strategy = default_strategy
        self._switch_count = 0
        self._strategy_history: list[dict[str, Any]] = []

        raw = thresholds if thresholds is not None else self.DEFAULT_THRESHOLDS
        self._thresholds = sorted(
            [StrategyThreshold(**t) for t in raw],
            key=lambda t: t.priority,
            reverse=True,
        )

    @property
    def current_strategy(self) -> str:
        return self._current_strategy

    def evaluate(
        self, params: dict[str, int | float], step: int = 0
    ) -> str:
        """Evaluate thresholds and return the recommended strategy.

        Args:
            params: Current parameter values.
            step: Current step number.

        Returns:
            Strategy string.
        """
        if not params:
            return self._current_strategy

        for threshold in self._thresholds:
            if threshold.evaluate(params):
                new_strategy = threshold.target_strategy
                if new_strategy != self._current_strategy:
                    self._previous_strategy = self._current_strategy
                    self._current_strategy = new_strategy
                    self._switch_count += 1
                    self._strategy_history.append({
                        "step": step,
                        "from": self._previous_strategy,
                        "to": new_strategy,
                        "trigger": f"{threshold.parameter} {threshold.operator} {threshold.value}",
                    })
                    logger.info(
                        "Strategy switch: %s -> %s (trigger: %s %s %.0f, step %d)",
                        self._previous_strategy, new_strategy,
                        threshold.parameter, threshold.operator, threshold.value, step,
                    )
                return self._current_strategy

        # No threshold fired — revert to default
        if self._current_strategy != self._default_strategy:
            self._previous_strategy = self._current_strategy
            self._current_strategy = self._default_strategy
            self._switch_count += 1
            self._strategy_history.append({
                "step": step,
                "from": self._previous_strategy,
                "to": self._default_strategy,
                "trigger": "no threshold active",
            })
            logger.info("Strategy reverted to %s (step %d)", self._default_strategy, step)

        return self._current_strategy

    def format_for_prompt(self) -> str:
        """Format strategy info for the GPT-4o prompt."""
        lines = [f"Active strategy: {self._current_strategy}"]
        if self._previous_strategy != self._current_strategy:
            lines.append(f"Previous strategy: {self._previous_strategy}")
        if self._switch_count > 0:
            lines.append(f"Total strategy switches: {self._switch_count}")
        return "\n".join(lines)

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for logging."""
        return {
            "current_strategy": self._current_strategy,
            "default_strategy": self._default_strategy,
            "switch_count": self._switch_count,
            "history": self._strategy_history[-10:],
        }

    @classmethod
    def from_json(cls, path: Path, default_strategy: str = "balanced") -> AdaptiveStrategyEngine:
        """Load thresholds from a JSON config file.

        Args:
            path: Path to JSON file with threshold definitions.
            default_strategy: Fallback strategy.

        Returns:
            Configured AdaptiveStrategyEngine.
        """
        import json as _json
        data = _json.loads(path.read_text())
        return cls(
            default_strategy=default_strategy,
            thresholds=data.get("thresholds", cls.DEFAULT_THRESHOLDS),
        )

    @classmethod
    def from_genre(cls, genre: str, default_strategy: str = "balanced") -> AdaptiveStrategyEngine:
        """Load thresholds from a built-in genre preset.

        Args:
            genre: Genre name (themepark, rpg, action, sports, puzzle).
            default_strategy: Fallback strategy.

        Returns:
            Configured AdaptiveStrategyEngine.

        Raises:
            ValueError: If genre is not recognized.
        """
        if genre not in cls.GENRE_PRESETS:
            available = ", ".join(sorted(cls.GENRE_PRESETS))
            raise ValueError(f"Unknown genre '{genre}'. Available: {available}")
        config_path = Path(__file__).parent / cls.GENRE_PRESETS[genre]
        return cls.from_json(config_path, default_strategy=default_strategy)


# ---------------------------------------------------------------------------
# Screen Capture
# ---------------------------------------------------------------------------

class ScreenCapture:
    """Capture the DuckStation window using mss (X11/Wayland compatible)."""

    def __init__(self, default_monitor: int = 1) -> None:
        self._default_monitor = default_monitor
        self._is_wayland = "WAYLAND_DISPLAY" in os.environ

        # Validate display environment before initializing mss
        if not self._is_wayland and not os.environ.get("DISPLAY"):
            raise RuntimeError(
                "No display server detected. Set DISPLAY (e.g., DISPLAY=:99 for Xvfb) "
                "or run under Wayland. If running headless, start Xvfb first:\n"
                "  Xvfb :99 -screen 0 1280x1024x24 &\n"
                "  export DISPLAY=:99"
            )

        try:
            self._sct = mss.mss()
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize screen capture: {e}\n"
                f"DISPLAY={os.environ.get('DISPLAY', '(not set)')}, "
                f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '(not set)')}"
            ) from e

    def capture(self, monitor_index: int | None = None) -> Image.Image:
        """Capture the screen (or specific monitor) as a PIL Image.

        Args:
            monitor_index: Monitor index (default: configured default_monitor).

        Returns:
            PIL Image of the captured screen.
        """
        idx = monitor_index if monitor_index is not None else self._default_monitor
        monitor = self._sct.monitors[idx]
        screenshot = self._sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img

    def capture_to_base64(
        self, monitor_index: int | None = None, max_size: tuple[int, int] = (1024, 768)
    ) -> str:
        """Capture screen and return as base64-encoded JPEG.

        Args:
            monitor_index: Monitor index (default: configured default_monitor).
            max_size: Max dimensions to resize to (for API cost savings).

        Returns:
            Base64-encoded JPEG string.
        """
        img = self.capture(monitor_index)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def save_screenshot(self, path: Path, monitor_index: int | None = None) -> Path:
        """Capture and save screenshot to file."""
        img = self.capture(monitor_index)
        img.save(str(path))
        return path


# ---------------------------------------------------------------------------
# GPT-4o Vision Analyzer
# ---------------------------------------------------------------------------

class GPT4VAnalyzer:
    """Analyze game screenshots using OpenAI GPT-4o Vision."""

    def __init__(self, api_key: str | None = None) -> None:
        import openai

        self.client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    def analyze_screen(
        self,
        image_b64: str,
        context: str = "",
        strategy: str = "balanced",
        parameters: dict[str, Any] | None = None,
        detail: str = "low",
        history: ActionHistory | None = None,
        game_state_text: str = "",
        trend_text: str = "",
        strategy_text: str = "",
        game_state: str = "",
        lang_hint: str = "",
    ) -> dict[str, Any]:
        """Send screenshot to GPT-4o Vision and get action instructions.

        Args:
            image_b64: Base64-encoded JPEG of the game screen.
            context: Additional context about the current game state.
            strategy: Current strategy mode.
            parameters: Current memory parameter values.
            detail: "low" or "high" for Vision API detail level.
            history: Recent action history for context.
            game_state_text: Formatted game state tracker info.
            trend_text: Formatted parameter trend analysis.
            strategy_text: Formatted adaptive strategy info.
            game_state: Current game state label (e.g. "menu", "gameplay").
            lang_hint: Language hint for the game (e.g. "ja", "en").

        Returns:
            Dict with 'action', 'reasoning', 'observations', and token usage.
        """
        param_text = ""
        if parameters:
            param_lines = [f"  {k}: {v}" for k, v in parameters.items()]
            param_text = "\nCurrent parameters:\n" + "\n".join(param_lines)

        history_text = ""
        if history:
            history_text = "\n" + history.format_for_prompt() + "\n"

        # Build extended context sections
        extended_context = ""
        if game_state_text:
            extended_context += "\n" + game_state_text + "\n"
        if trend_text:
            extended_context += "\n" + trend_text + "\n"
        if strategy_text:
            extended_context += "\n" + strategy_text + "\n"

        # Build language-awareness block
        lang_block = (
            "\nMulti-language support:\n"
            "  The game screen may contain text in Japanese, English, or other languages.\n"
            "  If Japanese text (kanji, hiragana, katakana) is visible, read and interpret it\n"
            "  as part of your analysis — it often contains menu labels, dialog, item names,\n"
            "  and status messages critical for decision-making.\n"
            "  Include a brief translation or summary of any on-screen text in your observations.\n"
        )
        if lang_hint:
            lang_block += f"  Language hint for this game: {lang_hint}\n"

        system_prompt = (
            "You are an AI playing a PS1 game via DuckStation emulator. "
            "Analyze the screenshot and decide what action to take.\n\n"
            f"Strategy mode: {strategy}\n"
            "Strategy descriptions:\n"
            "  expansion: Build attractions when funds allow\n"
            "  satisfaction: Prioritize visitor comfort\n"
            "  cost_reduction: Minimize costs\n"
            "  exploration: Try unvisited areas and new actions\n"
            "  balanced: Switch based on parameter thresholds\n\n"
            "Available keys:\n"
            "  arrows: D-pad (Up/Down/Left/Right)\n"
            "  z: Circle (confirm in Japanese games)\n"
            "  x: Cross (cancel/back)\n"
            "  a: Square\n"
            "  s: Triangle\n"
            "  enter: Start\n"
            "  space: Select\n\n"
            f"{lang_block}\n"
            "IMPORTANT: Review the action history and game state below. "
            "Avoid repeating the same action if it didn't produce a change. "
            "If parameters are stagnant, try a different approach. "
            "Adapt your actions to the current game state (menu vs gameplay vs dialog).\n"
            f"{extended_context}"
            f"{history_text}\n"
            "Respond in JSON format:\n"
            '{\n  "action": ["key1", "key2", ...],\n'
            '  "reasoning": "why this action",\n'
            '  "observations": "what I see on screen"\n}'
        )

        # Build user prompt with game state and language context
        user_text_parts = [f"Context: {context}"]
        if game_state:
            user_text_parts.append(f"Current game state: {game_state}")
        if lang_hint:
            user_text_parts.append(f"Game language: {lang_hint}")
        user_text_parts.append(param_text)
        user_text_parts.append("\nWhat action should I take? Respond in JSON.")

        user_content: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}",
                    "detail": detail,
                },
            },
            {
                "type": "text",
                "text": "\n".join(user_text_parts),
            },
        ]

        import json
        import re

        last_error: Exception | None = None
        for attempt in range(MAX_API_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    max_tokens=500,
                    temperature=0.3,
                )
                break
            except Exception as e:
                last_error = e
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "API error (attempt %d/%d): %s. Retrying in %.0fs...",
                    attempt + 1, MAX_API_RETRIES, e, wait,
                )
                time.sleep(wait)
        else:
            return {
                "action": [],
                "reasoning": f"API failed after {MAX_API_RETRIES} retries: {last_error}",
                "observations": "",
            }

        raw = response.choices[0].message.content or "{}"

        # Capture token usage
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        # Parse JSON from response (handle markdown code blocks)
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1)

        result = _parse_and_validate_response(raw)
        result["_input_tokens"] = input_tokens
        result["_output_tokens"] = output_tokens
        return result


# ---------------------------------------------------------------------------
# Keyboard Controller
# ---------------------------------------------------------------------------

# Map string key names to pynput Key objects
KEY_MAP: dict[str, Key | str] = {
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "enter": Key.enter,
    "space": Key.space,
    "z": "z",
    "x": "x",
    "a": "a",
    "s": "s",
    "q": "q",
    "w": "w",
    "e": "e",
    "r": "r",
}

VALID_KEYS: set[str] = set(KEY_MAP.keys())

# Maximum number of actions in a single step to prevent runaway sequences
_MAX_ACTIONS_PER_STEP = 10


def _parse_and_validate_response(raw: str) -> dict[str, Any]:
    """Parse a GPT-4o JSON response and validate its structure.

    Guarantees the returned dict always contains:
      - ``action``: ``list[str]`` of valid key names (invalid keys stripped)
      - ``reasoning``: ``str``
      - ``observations``: ``str``

    Args:
        raw: Raw response text (possibly JSON, possibly garbage).

    Returns:
        Validated result dict.
    """
    import json as _json

    # --- 1. Attempt JSON decode ---
    try:
        parsed = _json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("GPT response is not valid JSON; returning empty action.")
        return {
            "action": [],
            "reasoning": "Could not parse response as JSON",
            "observations": raw[:500] if raw else "",
        }

    if not isinstance(parsed, dict):
        logger.warning("GPT response JSON is not a dict (got %s).", type(parsed).__name__)
        return {
            "action": [],
            "reasoning": "Response JSON was not an object",
            "observations": str(parsed)[:500],
        }

    # --- 2. Extract and coerce fields ---
    action_raw = parsed.get("action", [])
    reasoning = parsed.get("reasoning", "")
    observations = parsed.get("observations", "")

    # reasoning / observations must be strings
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)
    if not isinstance(observations, str):
        observations = str(observations)

    # --- 3. Validate action list ---
    actions: list[str] = []

    if isinstance(action_raw, str):
        # GPT sometimes returns a single key as a string instead of a list
        action_raw = [action_raw]

    if isinstance(action_raw, list):
        for item in action_raw:
            if not isinstance(item, str):
                logger.debug("Skipping non-string action item: %r", item)
                continue
            key = item.strip().lower()
            if key in VALID_KEYS:
                actions.append(key)
            else:
                logger.warning("Ignoring invalid key name from GPT: %r", item)
    else:
        logger.warning(
            "action field is not a list or string (got %s); defaulting to empty.",
            type(action_raw).__name__,
        )

    # Cap the number of actions to prevent absurdly long sequences
    if len(actions) > _MAX_ACTIONS_PER_STEP:
        logger.warning(
            "GPT returned %d actions; truncating to %d.",
            len(actions), _MAX_ACTIONS_PER_STEP,
        )
        actions = actions[:_MAX_ACTIONS_PER_STEP]

    return {
        "action": actions,
        "reasoning": reasoning,
        "observations": observations,
    }


class KeyboardController:
    """Send keyboard input to DuckStation via pynput."""

    def __init__(self) -> None:
        self._kbd = KbdController()

    def press_key(self, key_name: str, duration: float = 0.1) -> None:
        """Press and release a key.

        Args:
            key_name: Key name (e.g., 'up', 'z', 'enter').
            duration: How long to hold the key in seconds.
        """
        key = KEY_MAP.get(key_name.lower())
        if key is None:
            logger.warning("Unknown key '%s'", key_name)
            return

        self._kbd.press(key)
        time.sleep(duration)
        self._kbd.release(key)

    def press_sequence(
        self, keys: list[str], delay: float = 0.5, duration: float = 0.1
    ) -> None:
        """Press a sequence of keys with delays between them.

        Args:
            keys: List of key names to press in order.
            delay: Delay between key presses.
            duration: Duration of each key press.
        """
        for key_name in keys:
            self.press_key(key_name, duration)
            time.sleep(delay)

    def navigate_menu(self, direction: str, count: int = 1) -> None:
        """Navigate a menu by pressing a direction key multiple times.

        Args:
            direction: 'up', 'down', 'left', or 'right'.
            count: Number of presses.
        """
        for _ in range(count):
            self.press_key(direction, 0.1)
            time.sleep(0.2)


# ---------------------------------------------------------------------------
# Memory Reader (bridge to memory_scanner)
# ---------------------------------------------------------------------------

class MemoryReader:
    """Read game parameters from DuckStation memory."""

    def __init__(
        self, game_id: str, scanner: MemoryScanner | None = None
    ) -> None:
        self.game_id = game_id
        self.scanner = scanner or MemoryScanner()
        self.address_manager = AddressManager()
        self.parameters = self.address_manager.get_parameter_addresses(game_id)

    def read_all(self) -> dict[str, int | float]:
        """Read all registered parameters.

        Returns:
            Dict mapping parameter name to current value.
        """
        values: dict[str, int | float] = {}
        for name, (address, data_type) in self.parameters.items():
            try:
                values[name] = self.scanner.read_address(address, data_type)
            except Exception:
                values[name] = -1
        return values

    def close(self) -> None:
        """Close the scanner."""
        self.scanner.close()


# ---------------------------------------------------------------------------
# Game Logger
# ---------------------------------------------------------------------------

class GameLogger:
    """Log agent actions and parameter values to CSV."""

    def __init__(self, game_id: str, log_dir: Path | None = None) -> None:
        self.game_id = game_id
        self.log_dir = log_dir or Path.home() / "ps1-ai-player" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = self.log_dir / f"{timestamp}_{game_id}_agent.csv"
        self._file = open(self.log_path, "w", newline="")
        self._writer = csv.writer(self._file)
        self._header_written = False
        self._param_names: list[str] = []

    def log(
        self,
        step: int,
        action: list[str],
        reasoning: str,
        observations: str,
        parameters: dict[str, int | float],
    ) -> None:
        """Log one agent step."""
        if not self._header_written:
            self._param_names = sorted(parameters.keys())
            header = [
                "timestamp",
                "step",
                "action",
                "reasoning",
                "observations",
            ] + self._param_names
            self._writer.writerow(header)
            self._header_written = True

        row = [
            datetime.now().isoformat(),
            step,
            ";".join(action),
            reasoning,
            observations,
        ] + [parameters.get(k, -1) for k in self._param_names]
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        """Close the log file."""
        self._file.close()


# ---------------------------------------------------------------------------
# AI Agent (main loop)
# ---------------------------------------------------------------------------

@dataclass
class AIAgent:
    """Main AI agent that plays the PS1 game autonomously.

    Loop:
        1. Capture screenshot
        2. Read memory parameters
        3. Send image + parameters to GPT-4o Vision
        4. Execute returned key presses
        5. Log everything
    """

    game_id: str
    strategy: str = "balanced"
    detail: str = "low"
    interval: float = 5.0
    api_key: str | None = None
    lang_hint: str = ""
    resume_history_path: Path | None = None
    strategy_config: str | None = None
    monitor_index: int = 1

    _running: bool = field(default=False, init=False, repr=False)
    _step: int = field(default=0, init=False, repr=False)

    @staticmethod
    def _check_duckstation_running() -> bool:
        """Check if DuckStation is currently running."""
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_text()
                if "duckstation" in cmdline.lower():
                    return True
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
        return False

    def _wait_for_duckstation(self) -> bool:
        """Wait for DuckStation to start, polling up to DUCKSTATION_WAIT_TIMEOUT seconds.

        Returns:
            True if DuckStation was found, False if timeout.
        """
        if self._check_duckstation_running():
            logger.info("DuckStation is running.")
            return True

        logger.info(
            "DuckStation not detected. Waiting up to %ds for it to start...",
            DUCKSTATION_WAIT_TIMEOUT,
        )
        elapsed = 0.0
        while elapsed < DUCKSTATION_WAIT_TIMEOUT:
            time.sleep(DUCKSTATION_POLL_INTERVAL)
            elapsed += DUCKSTATION_POLL_INTERVAL
            if self._check_duckstation_running():
                logger.info("DuckStation detected after %.0fs.", elapsed)
                return True
            logger.debug("Waiting... (%.0f/%ds)", elapsed, DUCKSTATION_WAIT_TIMEOUT)

        logger.warning(
            "DuckStation not found after timeout. "
            "Memory reading will be unavailable. "
            "Agent will operate in screenshot-only mode."
        )
        return False

    def run(self) -> None:
        """Start the agent loop. Blocks until Ctrl+C."""
        # Pre-flight checks
        if not self.api_key and not os.environ.get("OPENAI_API_KEY"):
            logger.error("No OpenAI API key. Set OPENAI_API_KEY or use --openai-key.")
            sys.exit(1)

        self._wait_for_duckstation()

        screen = ScreenCapture(default_monitor=getattr(self, 'monitor_index', 1))
        analyzer = GPT4VAnalyzer(api_key=self.api_key)
        keyboard = KeyboardController()
        memory = MemoryReader(self.game_id)
        game_logger = GameLogger(self.game_id)
        if self.resume_history_path:
            history = ActionHistory.load(self.resume_history_path)
            logger.info("Resumed %d history records from %s", len(history.records), self.resume_history_path)
        else:
            history = ActionHistory()
        cost_tracker = CostTracker()
        state_tracker = GameStateTracker()
        trend_analyzer = ParameterTrendAnalyzer()
        if self.strategy_config:
            config_path = Path(self.strategy_config)
            if config_path.is_file():
                strategy_engine = AdaptiveStrategyEngine.from_json(config_path, default_strategy=self.strategy)
                logger.info("Loaded strategy config from %s", config_path)
            elif self.strategy_config in AdaptiveStrategyEngine.GENRE_PRESETS:
                strategy_engine = AdaptiveStrategyEngine.from_genre(self.strategy_config, default_strategy=self.strategy)
                logger.info("Loaded genre preset: %s", self.strategy_config)
            else:
                logger.warning("Strategy config '%s' not found. Using defaults.", self.strategy_config)
                strategy_engine = AdaptiveStrategyEngine(default_strategy=self.strategy)
        else:
            strategy_engine = AdaptiveStrategyEngine(default_strategy=self.strategy)

        self._running = True
        consecutive_errors = 0
        last_observations = ""

        def stop(sig: int, frame: object) -> None:
            logger.info("Stopping agent...")
            self._running = False

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

        logger.info("=== AI Agent Started ===")
        logger.info("Game: %s | Strategy: %s | Detail: %s | Interval: %.1fs",
                     self.game_id, self.strategy, self.detail, self.interval)
        logger.info("History window: %d steps | Trend window: %d steps",
                     ACTION_HISTORY_SIZE, TREND_WINDOW_SIZE)
        logger.info("Adaptive strategy: enabled (default: %s)", self.strategy)
        logger.info("Log: %s", game_logger.log_path)

        try:
            while self._running:
                self._step += 1
                logger.info("--- Step %d ---", self._step)

                # 1. Screenshot
                try:
                    image_b64 = screen.capture_to_base64()
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    logger.error("Screenshot error: %s", e)
                    if consecutive_errors >= 5:
                        logger.error("Too many consecutive screenshot errors. Stopping.")
                        break
                    time.sleep(self.interval)
                    continue

                # 2. Read memory parameters (non-fatal if fails)
                params: dict[str, int | float] = {}
                try:
                    params = memory.read_all()
                    if params:
                        param_str = " | ".join(f"{k}={v}" for k, v in params.items())
                        logger.info("Params: %s", param_str)
                except Exception as e:
                    logger.debug("Memory read error (non-fatal): %s", e)

                # 3. Analyze parameter trends
                trends = trend_analyzer.record(params) if params else {}
                trend_text = trend_analyzer.format_for_prompt(trends) if trends else ""
                params_changed = trend_analyzer.params_changed(trends) if trends else False

                if trends:
                    stagnant = trend_analyzer.get_stagnant_params(trends)
                    if stagnant:
                        logger.debug("Stagnant params: %s", ", ".join(stagnant))

                # 4. Update game state tracker
                action_had_effect = params_changed or (last_observations != "" and self._step > 1)
                game_state = state_tracker.update(
                    step=self._step,
                    observations=last_observations,
                    params_changed=params_changed,
                    action_had_effect=action_had_effect,
                )
                game_state_text = state_tracker.format_for_prompt()
                logger.info("Game state: %s (duration: %d)", game_state, state_tracker.state_duration)

                # 5. Adaptive strategy evaluation
                active_strategy = strategy_engine.evaluate(params, step=self._step)
                strategy_text = strategy_engine.format_for_prompt()
                if active_strategy != self.strategy:
                    logger.info("Active strategy: %s (base: %s)", active_strategy, self.strategy)

                # 6. GPT-4o Vision analysis with full context
                context = f"Step {self._step}, strategy={active_strategy}"
                result = analyzer.analyze_screen(
                    image_b64,
                    context=context,
                    strategy=active_strategy,
                    parameters=params,
                    detail=self.detail,
                    history=history,
                    game_state_text=game_state_text,
                    trend_text=trend_text,
                    strategy_text=strategy_text,
                    game_state=game_state,
                    lang_hint=getattr(self, "lang_hint", ""),
                )

                action = result.get("action", [])
                reasoning = result.get("reasoning", "")
                observations = result.get("observations", "")
                last_observations = observations

                # Track API cost
                input_tokens = result.pop("_input_tokens", 0)
                output_tokens = result.pop("_output_tokens", 0)
                step_cost = cost_tracker.record(self._step, input_tokens, output_tokens)

                logger.info("Action: %s", action)
                logger.info("Reason: %s", reasoning)
                logger.info(
                    "Cost: $%.4f (total: $%.4f, %d+%d tokens)",
                    step_cost, cost_tracker.total_cost,
                    cost_tracker.total_input_tokens, cost_tracker.total_output_tokens,
                )

                # 7. Execute actions (skip during loading state)
                if action and game_state != GAME_STATE_LOADING:
                    keyboard.press_sequence(action)
                elif game_state == GAME_STATE_LOADING:
                    logger.info("Loading state detected — skipping input.")

                # 8. Record to history
                history.add(ActionRecord(
                    step=self._step,
                    action=action,
                    reasoning=reasoning,
                    observations=observations,
                    parameters=dict(params),
                ))

                # 9. Log
                game_logger.log(self._step, action, reasoning, observations, params)

                time.sleep(self.interval)

        finally:
            memory.close()
            game_logger.close()

            # Save cost summary + session state
            cost_summary = cost_tracker.summary()
            state_summary = state_tracker.summary()
            strategy_summary = strategy_engine.summary()
            logger.info("Agent stopped after %d steps.", self._step)
            logger.info("Log saved to: %s", game_logger.log_path)
            logger.info(
                "API cost: $%.4f (%d calls, avg $%.6f/call)",
                cost_summary['total_cost_usd'],
                cost_summary['api_calls'],
                cost_summary['avg_cost_per_call'],
            )
            logger.info(
                "State transitions: %d | Strategy switches: %d",
                state_summary['transitions'],
                strategy_summary['switch_count'],
            )

            # Write session summary JSON next to the log
            session_data = {
                "cost": cost_summary,
                "game_state": state_summary,
                "strategy": strategy_summary,
                "total_steps": self._step,
            }
            cost_path = game_logger.log_path.with_suffix(".session.json")
            cost_path.write_text(json.dumps(session_data, indent=2))
            logger.info("Session summary: %s", cost_path)

            # Save action history for session resumption
            history_path = history.save(game_logger.log_path.with_suffix(".history.json"))
            logger.info("Action history: %s", history_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="PS1 AI Player Agent")
    parser.add_argument("--game", "-g", required=True, help="Game ID")
    parser.add_argument(
        "--strategy",
        "-s",
        default="balanced",
        choices=["expansion", "satisfaction", "cost_reduction", "exploration", "balanced"],
        help="Strategy mode (default: balanced)",
    )
    parser.add_argument(
        "--strategy-config",
        default=None,
        help="Path to strategy config JSON file, or built-in genre name (rpg, action, sports, puzzle, themepark)",
    )
    parser.add_argument(
        "--detail",
        "-d",
        default="low",
        choices=["low", "high"],
        help="GPT-4o Vision detail level (default: low)",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=float,
        default=5.0,
        help="Seconds between agent steps (default: 5.0)",
    )
    parser.add_argument(
        "--openai-key",
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--lang",
        default="",
        help="Language hint for the game (e.g. ja, en). Helps GPT-4o interpret on-screen text.",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=1,
        help="Monitor index for screen capture (default: 1)",
    )
    parser.add_argument(
        "--resume-history",
        default=None,
        type=Path,
        help="Path to a .history.json from a previous session to resume learning from.",
    )
    args = parser.parse_args()

    agent = AIAgent(
        game_id=args.game,
        strategy=args.strategy,
        detail=args.detail,
        interval=args.interval,
        api_key=args.openai_key,
        lang_hint=args.lang,
        resume_history_path=args.resume_history,
        strategy_config=args.strategy_config,
        monitor_index=args.monitor,
    )
    agent.run()


if __name__ == "__main__":
    main()
