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
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import mss
import mss.tools
from PIL import Image
from pynput.keyboard import Controller as KbdController
from pynput.keyboard import Key

from address_manager import AddressManager
from memory_scanner import MemoryScanner

# ---------------------------------------------------------------------------
# Screen Capture
# ---------------------------------------------------------------------------

class ScreenCapture:
    """Capture the DuckStation window using mss (X11/Wayland compatible)."""

    def __init__(self) -> None:
        self._sct = mss.mss()
        self._is_wayland = "WAYLAND_DISPLAY" in os.environ

    def capture(self, monitor_index: int = 1) -> Image.Image:
        """Capture the screen (or specific monitor) as a PIL Image.

        Args:
            monitor_index: Monitor index (1 = primary).

        Returns:
            PIL Image of the captured screen.
        """
        monitor = self._sct.monitors[monitor_index]
        screenshot = self._sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img

    def capture_to_base64(
        self, monitor_index: int = 1, max_size: tuple[int, int] = (1024, 768)
    ) -> str:
        """Capture screen and return as base64-encoded JPEG.

        Args:
            monitor_index: Monitor index.
            max_size: Max dimensions to resize to (for API cost savings).

        Returns:
            Base64-encoded JPEG string.
        """
        img = self.capture(monitor_index)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def save_screenshot(self, path: Path, monitor_index: int = 1) -> Path:
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
    ) -> dict[str, Any]:
        """Send screenshot to GPT-4o Vision and get action instructions.

        Args:
            image_b64: Base64-encoded JPEG of the game screen.
            context: Additional context about the current game state.
            strategy: Current strategy mode.
            parameters: Current memory parameter values.
            detail: "low" or "high" for Vision API detail level.

        Returns:
            Dict with 'action' (key sequence), 'reasoning', and 'observations'.
        """
        param_text = ""
        if parameters:
            param_lines = [f"  {k}: {v}" for k, v in parameters.items()]
            param_text = "\nCurrent parameters:\n" + "\n".join(param_lines)

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
            "Respond in JSON format:\n"
            '{\n  "action": ["key1", "key2", ...],\n'
            '  "reasoning": "why this action",\n'
            '  "observations": "what I see on screen"\n}'
        )

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
                "text": f"Context: {context}\n{param_text}\n\n"
                "What action should I take? Respond in JSON.",
            },
        ]

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=500,
            temperature=0.3,
        )

        raw = response.choices[0].message.content or "{}"

        # Parse JSON from response (handle markdown code blocks)
        import json
        import re

        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {
                "action": [],
                "reasoning": "Could not parse response",
                "observations": raw,
            }

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
            print(f"Warning: Unknown key '{key_name}'")
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
            header = [
                "timestamp",
                "step",
                "action",
                "reasoning",
                "observations",
            ] + list(parameters.keys())
            self._writer.writerow(header)
            self._header_written = True

        row = [
            datetime.now().isoformat(),
            step,
            ";".join(action),
            reasoning,
            observations,
        ] + [parameters.get(k, -1) for k in parameters]
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

    _running: bool = field(default=False, init=False, repr=False)
    _step: int = field(default=0, init=False, repr=False)

    def run(self) -> None:
        """Start the agent loop. Blocks until Ctrl+C."""
        screen = ScreenCapture()
        analyzer = GPT4VAnalyzer(api_key=self.api_key)
        keyboard = KeyboardController()
        memory = MemoryReader(self.game_id)
        logger = GameLogger(self.game_id)

        self._running = True

        def stop(sig: int, frame: object) -> None:
            print("\nStopping agent...")
            self._running = False

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

        print(f"=== AI Agent Started ===")
        print(f"Game: {self.game_id}")
        print(f"Strategy: {self.strategy}")
        print(f"Detail: {self.detail}")
        print(f"Interval: {self.interval}s")
        print(f"Log: {logger.log_path}")
        print("Press Ctrl+C to stop.\n")

        try:
            while self._running:
                self._step += 1
                print(f"--- Step {self._step} ---")

                # 1. Screenshot
                try:
                    image_b64 = screen.capture_to_base64()
                except Exception as e:
                    print(f"Screenshot error: {e}")
                    time.sleep(self.interval)
                    continue

                # 2. Read memory parameters
                params = memory.read_all()
                if params:
                    param_str = " | ".join(f"{k}={v}" for k, v in params.items())
                    print(f"Params: {param_str}")

                # 3. GPT-4o Vision analysis
                try:
                    context = f"Step {self._step}, strategy={self.strategy}"
                    result = analyzer.analyze_screen(
                        image_b64,
                        context=context,
                        strategy=self.strategy,
                        parameters=params,
                        detail=self.detail,
                    )
                except Exception as e:
                    print(f"API error: {e}")
                    time.sleep(self.interval)
                    continue

                action = result.get("action", [])
                reasoning = result.get("reasoning", "")
                observations = result.get("observations", "")

                print(f"Action: {action}")
                print(f"Reason: {reasoning}")

                # 4. Execute actions
                if action:
                    keyboard.press_sequence(action)

                # 5. Log
                logger.log(self._step, action, reasoning, observations, params)

                time.sleep(self.interval)

        finally:
            memory.close()
            logger.close()
            print(f"\nAgent stopped after {self._step} steps.")
            print(f"Log saved to: {logger.log_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
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
    args = parser.parse_args()

    agent = AIAgent(
        game_id=args.game,
        strategy=args.strategy,
        detail=args.detail,
        interval=args.interval,
        api_key=args.openai_key,
    )
    agent.run()


if __name__ == "__main__":
    main()
