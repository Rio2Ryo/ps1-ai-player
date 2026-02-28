"""Tests for ScreenCapture, KeyboardController, and AIAgent.run().

All external dependencies (mss, pynput, PIL, OpenAI) are mocked so tests
run without X11, a display server, or API keys.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure pynput / mss / PIL are mocked before ai_agent is imported.
# test_agent_components.py does the same; these are idempotent.
for _mod in ("pynput", "pynput.keyboard", "mss", "mss.tools"):
    sys.modules.setdefault(_mod, MagicMock())
_pil = sys.modules.get("PIL")
if _pil is None or not hasattr(_pil, "__path__"):
    sys.modules["PIL"] = MagicMock()
    sys.modules["PIL.Image"] = MagicMock()

import pytest

from ai_agent import (
    AIAgent,
    GAME_STATE_LOADING,
    KEY_MAP,
    KeyboardController,
    ScreenCapture,
)


# ===================================================================
# ScreenCapture
# ===================================================================


class TestScreenCapture:
    """Tests for ScreenCapture (mss + PIL mocked)."""

    def test_init_with_display(self, monkeypatch) -> None:
        """Succeeds when DISPLAY is set."""
        monkeypatch.setenv("DISPLAY", ":99")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        sc = ScreenCapture()
        assert sc._sct is not None
        assert sc._is_wayland is False

    def test_init_with_wayland(self, monkeypatch) -> None:
        """Succeeds with WAYLAND_DISPLAY."""
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        sc = ScreenCapture()
        assert sc._is_wayland is True

    def test_init_raises_without_display(self, monkeypatch) -> None:
        """Raises RuntimeError when no display server is available."""
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        with pytest.raises(RuntimeError, match="No display server"):
            ScreenCapture()

    def test_capture_calls_grab(self, monkeypatch) -> None:
        """capture() invokes _sct.grab with the requested monitor."""
        monkeypatch.setenv("DISPLAY", ":99")
        sc = ScreenCapture()
        sc._sct.reset_mock()

        sc.capture(monitor_index=1)

        sc._sct.grab.assert_called_once_with(sc._sct.monitors[1])

    def test_capture_to_base64_returns_string(self, monkeypatch) -> None:
        """capture_to_base64() runs without error and returns a string."""
        monkeypatch.setenv("DISPLAY", ":99")
        sc = ScreenCapture()
        result = sc.capture_to_base64()
        assert isinstance(result, str)

    def test_save_screenshot_returns_path(self, monkeypatch, tmp_path) -> None:
        """save_screenshot() returns the output path."""
        monkeypatch.setenv("DISPLAY", ":99")
        sc = ScreenCapture()
        out = tmp_path / "shot.png"
        result = sc.save_screenshot(out)
        assert result == out

    def test_capture_custom_monitor_index(self, monkeypatch) -> None:
        """Different monitor_index is forwarded to _sct.monitors."""
        monkeypatch.setenv("DISPLAY", ":99")
        sc = ScreenCapture()
        sc._sct.reset_mock()

        sc.capture(monitor_index=2)

        sc._sct.grab.assert_called_once_with(sc._sct.monitors[2])


# ===================================================================
# KeyboardController
# ===================================================================


class TestKeyboardController:
    """Tests for KeyboardController (pynput mocked)."""

    @staticmethod
    def _make_kc() -> KeyboardController:
        """Create a KeyboardController and reset its shared mock."""
        kc = KeyboardController()
        kc._kbd.reset_mock()
        return kc

    def test_press_key_char(self) -> None:
        """Character key 'z' presses and releases the string."""
        kc = self._make_kc()
        with patch("ai_agent.time"):
            kc.press_key("z", duration=0.0)
        kc._kbd.press.assert_called_once_with("z")
        kc._kbd.release.assert_called_once_with("z")

    def test_press_key_arrow(self) -> None:
        """Arrow key presses and releases the same Key object."""
        kc = self._make_kc()
        with patch("ai_agent.time"):
            kc.press_key("up", duration=0.0)
        kc._kbd.press.assert_called_once()
        kc._kbd.release.assert_called_once()
        pressed = kc._kbd.press.call_args[0][0]
        released = kc._kbd.release.call_args[0][0]
        assert pressed is released
        assert pressed is KEY_MAP["up"]

    def test_press_key_unknown_ignored(self) -> None:
        """Unknown key names log a warning and do nothing."""
        kc = self._make_kc()
        kc.press_key("banana")
        kc._kbd.press.assert_not_called()
        kc._kbd.release.assert_not_called()

    def test_press_key_case_insensitive(self) -> None:
        """Key names are lowered internally."""
        kc = self._make_kc()
        with patch("ai_agent.time"):
            kc.press_key("Z", duration=0.0)
        kc._kbd.press.assert_called_once_with("z")

    def test_press_sequence_order(self) -> None:
        """press_sequence presses each key in order."""
        kc = self._make_kc()
        with patch("ai_agent.time"):
            kc.press_sequence(["up", "z", "down"], delay=0, duration=0)
        assert kc._kbd.press.call_count == 3
        assert kc._kbd.release.call_count == 3

    def test_press_sequence_empty(self) -> None:
        """Empty key list is a no-op."""
        kc = self._make_kc()
        with patch("ai_agent.time"):
            kc.press_sequence([], delay=0, duration=0)
        kc._kbd.press.assert_not_called()

    def test_navigate_menu_count(self) -> None:
        """navigate_menu presses the direction key *count* times."""
        kc = self._make_kc()
        with patch("ai_agent.time"):
            kc.navigate_menu("down", count=4)
        assert kc._kbd.press.call_count == 4
        assert kc._kbd.release.call_count == 4

    def test_press_key_calls_sleep(self) -> None:
        """press_key sleeps for the given duration between press and release."""
        kc = self._make_kc()
        with patch("ai_agent.time") as mock_time:
            kc.press_key("z", duration=0.15)
        mock_time.sleep.assert_called_with(0.15)


# ===================================================================
# AIAgent.run()
# ===================================================================


def _mock_gpt_response(**overrides):
    """Build a standard GPT-4o-style response dict."""
    base = {
        "action": ["up", "z"],
        "reasoning": "Navigate menu",
        "observations": "Menu screen visible",
        "_input_tokens": 100,
        "_output_tokens": 50,
    }
    base.update(overrides)
    return base


def _run_agent_patched(
    monkeypatch,
    tmp_path,
    *,
    max_steps: int = 2,
    response: dict | None = None,
    responses: list[dict] | None = None,
    screen_side_effect=None,
    api_key: str = "test-key",
):
    """Create an AIAgent, patch all deps, run for *max_steps*, return mock dict.

    Parameters
    ----------
    responses:
        Per-step response list (overrides *response*). Cycled if shorter
        than *max_steps*.
    """
    monkeypatch.setenv("OPENAI_API_KEY", api_key)

    mocks: dict = {}
    with (
        patch("ai_agent.ScreenCapture") as MockScreen,
        patch("ai_agent.GPT4VAnalyzer") as MockAnalyzer,
        patch("ai_agent.KeyboardController") as MockKbd,
        patch("ai_agent.MemoryReader") as MockMemory,
        patch("ai_agent.GameLogger") as MockLogger,
        patch("ai_agent.time") as mock_time,
        patch("ai_agent.signal"),
    ):
        # --- Screen ---
        mock_screen = MockScreen.return_value
        if screen_side_effect:
            mock_screen.capture_to_base64.side_effect = screen_side_effect
        else:
            mock_screen.capture_to_base64.return_value = "base64img"

        # --- Analyzer ---
        mock_analyzer = MockAnalyzer.return_value
        if responses is not None:
            mock_analyzer.analyze_screen.side_effect = list(responses)
        else:
            mock_analyzer.analyze_screen.return_value = (
                response or _mock_gpt_response()
            )

        # --- Memory ---
        mock_memory = MockMemory.return_value
        mock_memory.read_all.return_value = {"money": 5000, "satisfaction": 70}

        # --- Logger (needs a real Path for .with_suffix) ---
        mock_logger = MockLogger.return_value
        log_path = tmp_path / "agent.csv"
        log_path.touch()
        mock_logger.log_path = log_path

        # --- Agent ---
        agent = AIAgent(game_id="TEST", api_key=api_key, interval=0)

        # Stop the loop after *max_steps* end-of-iteration sleeps.
        sleep_count = [0]

        def _limited_sleep(_seconds):
            sleep_count[0] += 1
            if sleep_count[0] >= max_steps:
                agent._running = False

        mock_time.sleep.side_effect = _limited_sleep

        with patch.object(agent, "_wait_for_duckstation", return_value=True):
            agent.run()

        mocks.update(
            agent=agent,
            screen=mock_screen,
            analyzer=mock_analyzer,
            kbd=MockKbd.return_value,
            memory=mock_memory,
            logger=mock_logger,
            time=mock_time,
        )

    return mocks


class TestAIAgentRun:
    """Tests for the AIAgent.run() main loop."""

    # ----- basic loop -------------------------------------------------

    def test_run_basic_loop(self, monkeypatch, tmp_path) -> None:
        """Agent runs 2 steps: captures, analyses, presses keys, logs."""
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=2)
        assert m["agent"]._step == 2
        assert m["screen"].capture_to_base64.call_count == 2
        assert m["analyzer"].analyze_screen.call_count == 2
        assert m["kbd"].press_sequence.call_count == 2
        assert m["logger"].log.call_count == 2

    def test_run_single_step(self, monkeypatch, tmp_path) -> None:
        """Single-step smoke test."""
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=1)
        assert m["agent"]._step == 1

    # ----- loading state skips input ----------------------------------

    def test_run_skips_input_during_loading(self, monkeypatch, tmp_path) -> None:
        """keyboard.press_sequence is NOT called when game state is loading.

        Step 1: GPT returns 'loading' in observations → keys still pressed
                (state tracker sees *last_observations*="" on step 1).
        Step 2: state tracker classifies from step 1's "loading" observations
                → game_state = LOADING → keyboard skipped.
        """
        resp = _mock_gpt_response(observations="Now loading please wait")
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=2, response=resp)
        # Step 1: state ≠ loading → press  |  Step 2: state = loading → skip
        assert m["kbd"].press_sequence.call_count == 1

    # ----- empty action list ------------------------------------------

    def test_run_empty_action_no_keypress(self, monkeypatch, tmp_path) -> None:
        """press_sequence is not called when action list is empty."""
        resp = _mock_gpt_response(action=[])
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=2, response=resp)
        m["kbd"].press_sequence.assert_not_called()

    # ----- consecutive screenshot errors ------------------------------

    def test_run_stops_on_consecutive_screenshot_errors(
        self, monkeypatch, tmp_path
    ) -> None:
        """Agent breaks out of the loop after 5 consecutive screenshot errors."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        with (
            patch("ai_agent.ScreenCapture") as MockScreen,
            patch("ai_agent.GPT4VAnalyzer"),
            patch("ai_agent.KeyboardController"),
            patch("ai_agent.MemoryReader") as MockMemory,
            patch("ai_agent.GameLogger") as MockLogger,
            patch("ai_agent.time"),
            patch("ai_agent.signal"),
        ):
            MockScreen.return_value.capture_to_base64.side_effect = RuntimeError(
                "no display"
            )
            MockMemory.return_value.read_all.return_value = {}
            log_path = tmp_path / "err.csv"
            log_path.touch()
            MockLogger.return_value.log_path = log_path

            agent = AIAgent(game_id="TEST", api_key="test-key")
            with patch.object(agent, "_wait_for_duckstation", return_value=True):
                agent.run()

            assert agent._step == 5
            assert MockScreen.return_value.capture_to_base64.call_count == 5

    # ----- no API key → sys.exit(1) -----------------------------------

    def test_run_exits_without_api_key(self, monkeypatch) -> None:
        """Agent calls sys.exit(1) when no API key is available."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        agent = AIAgent(game_id="TEST", api_key=None)
        with pytest.raises(SystemExit) as exc_info:
            agent.run()
        assert exc_info.value.code == 1

    # ----- cleanup / session persistence ------------------------------

    def test_run_saves_session_json(self, monkeypatch, tmp_path) -> None:
        """Session JSON is written on agent stop."""
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=1)
        session_path = m["logger"].log_path.with_suffix(".session.json")
        assert session_path.exists()
        data = json.loads(session_path.read_text())
        assert "cost" in data
        assert "game_state" in data
        assert "strategy" in data
        assert data["total_steps"] == 1

    def test_run_session_json_has_cost_summary(self, monkeypatch, tmp_path) -> None:
        """cost section contains expected fields."""
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=2)
        data = json.loads(
            m["logger"].log_path.with_suffix(".session.json").read_text()
        )
        cost = data["cost"]
        assert "total_input_tokens" in cost
        assert "total_output_tokens" in cost
        assert "total_cost_usd" in cost
        assert "api_calls" in cost
        assert cost["api_calls"] == 2

    def test_run_memory_close_called(self, monkeypatch, tmp_path) -> None:
        """MemoryReader.close() is called even after normal exit."""
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=1)
        m["memory"].close.assert_called_once()

    def test_run_logger_close_called(self, monkeypatch, tmp_path) -> None:
        """GameLogger.close() is called on exit."""
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=1)
        m["logger"].close.assert_called_once()

    # ----- strategy / params pass-through -----------------------------

    def test_run_passes_params_to_analyzer(self, monkeypatch, tmp_path) -> None:
        """analyze_screen receives the memory parameters dict."""
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=1)
        call_kwargs = m["analyzer"].analyze_screen.call_args
        # parameters kwarg should contain the mock memory values
        assert call_kwargs.kwargs["parameters"] == {
            "money": 5000,
            "satisfaction": 70,
        }

    def test_run_passes_strategy_to_analyzer(self, monkeypatch, tmp_path) -> None:
        """analyze_screen receives the active strategy string."""
        m = _run_agent_patched(monkeypatch, tmp_path, max_steps=1)
        call_kwargs = m["analyzer"].analyze_screen.call_args
        assert "strategy" in call_kwargs.kwargs

    # ----- per-step response variation --------------------------------

    def test_run_per_step_responses(self, monkeypatch, tmp_path) -> None:
        """Different GPT responses on each step are honoured."""
        r1 = _mock_gpt_response(action=["left"], reasoning="step1")
        r2 = _mock_gpt_response(action=["right"], reasoning="step2")
        m = _run_agent_patched(
            monkeypatch, tmp_path, max_steps=2, responses=[r1, r2]
        )
        calls = m["kbd"].press_sequence.call_args_list
        assert calls[0][0][0] == ["left"]
        assert calls[1][0][0] == ["right"]

    # ----- memory read failure is non-fatal ---------------------------

    def test_run_continues_on_memory_error(self, monkeypatch, tmp_path) -> None:
        """Agent keeps running when MemoryReader.read_all raises."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        with (
            patch("ai_agent.ScreenCapture") as MockScreen,
            patch("ai_agent.GPT4VAnalyzer") as MockAnalyzer,
            patch("ai_agent.KeyboardController"),
            patch("ai_agent.MemoryReader") as MockMemory,
            patch("ai_agent.GameLogger") as MockLogger,
            patch("ai_agent.time") as mock_time,
            patch("ai_agent.signal"),
        ):
            MockScreen.return_value.capture_to_base64.return_value = "img"
            MockAnalyzer.return_value.analyze_screen.return_value = (
                _mock_gpt_response()
            )
            MockMemory.return_value.read_all.side_effect = RuntimeError("no proc")
            log_path = tmp_path / "memfail.csv"
            log_path.touch()
            MockLogger.return_value.log_path = log_path

            agent = AIAgent(game_id="TEST", api_key="test-key")

            calls = [0]

            def _stop(_s):
                calls[0] += 1
                if calls[0] >= 1:
                    agent._running = False

            mock_time.sleep.side_effect = _stop

            with patch.object(agent, "_wait_for_duckstation", return_value=True):
                agent.run()

            # Agent completed 1 step despite memory failure
            assert agent._step == 1
            MockAnalyzer.return_value.analyze_screen.assert_called_once()
