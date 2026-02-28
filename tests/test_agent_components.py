"""Tests for ai_agent.py components (ActionHistory, CostTracker, GameStateTracker,
ParameterTrendAnalyzer, AdaptiveStrategyEngine)."""

from __future__ import annotations

import sys
from pathlib import Path

# These classes don't require X11/pynput, so we mock the imports
# before importing ai_agent
import unittest.mock as mock

# Mock pynput and mss to avoid X11 dependency in tests
sys.modules["pynput"] = mock.MagicMock()
sys.modules["pynput.keyboard"] = mock.MagicMock()
sys.modules["mss"] = mock.MagicMock()
sys.modules["mss.tools"] = mock.MagicMock()
sys.modules["PIL"] = mock.MagicMock()
sys.modules["PIL.Image"] = mock.MagicMock()

from ai_agent import (
    ActionHistory,
    ActionRecord,
    AdaptiveStrategyEngine,
    AIAgent,
    CostTracker,
    GameStateTracker,
    GPT4VAnalyzer,
    ParameterTrendAnalyzer,
    StrategyThreshold,
    VALID_KEYS,
    _MAX_ACTIONS_PER_STEP,
    _parse_and_validate_response,
    GAME_STATE_GAMEPLAY,
    GAME_STATE_LOADING,
    GAME_STATE_MENU,
    GAME_STATE_DIALOG,
    GAME_STATE_PAUSE,
    GAME_STATE_UNKNOWN,
)


class TestActionHistory:
    def test_empty_history(self) -> None:
        h = ActionHistory(max_size=5)
        assert h.format_for_prompt() == ""
        assert len(h.records) == 0

    def test_add_records(self) -> None:
        h = ActionHistory(max_size=3)
        for i in range(3):
            h.add(ActionRecord(step=i, action=["up"], reasoning=f"reason {i}", observations=""))
        assert len(h.records) == 3

    def test_sliding_window(self) -> None:
        h = ActionHistory(max_size=3)
        for i in range(5):
            h.add(ActionRecord(step=i, action=["up"], reasoning=f"r{i}", observations=""))
        # Should only keep last 3
        assert len(h.records) == 3
        assert h.records[0].step == 2
        assert h.records[-1].step == 4

    def test_format_includes_steps(self) -> None:
        h = ActionHistory(max_size=5)
        h.add(ActionRecord(step=1, action=["up", "z"], reasoning="Navigate menu", observations="menu visible"))
        h.add(ActionRecord(step=2, action=["down"], reasoning="Select option", observations="cursor moved",
                           parameters={"money": 5000}))
        text = h.format_for_prompt()
        assert "Step 1" in text
        assert "Step 2" in text
        assert "up, z" in text
        assert "money=5000" in text


class TestCostTracker:
    def test_initial_state(self) -> None:
        ct = CostTracker()
        assert ct.total_input_tokens == 0
        assert ct.total_output_tokens == 0
        assert ct.total_cost == 0.0

    def test_record_tokens(self) -> None:
        ct = CostTracker()
        cost = ct.record(step=1, input_tokens=1000, output_tokens=200)
        assert cost > 0
        assert ct.total_input_tokens == 1000
        assert ct.total_output_tokens == 200

    def test_cumulative_tracking(self) -> None:
        ct = CostTracker()
        ct.record(step=1, input_tokens=500, output_tokens=100)
        ct.record(step=2, input_tokens=600, output_tokens=150)
        assert ct.total_input_tokens == 1100
        assert ct.total_output_tokens == 250

    def test_summary(self) -> None:
        ct = CostTracker()
        ct.record(step=1, input_tokens=1000, output_tokens=200)
        ct.record(step=2, input_tokens=1000, output_tokens=200)
        summary = ct.summary()
        assert summary["api_calls"] == 2
        assert summary["total_input_tokens"] == 2000
        assert summary["total_output_tokens"] == 400
        assert summary["total_cost_usd"] > 0
        assert summary["avg_cost_per_call"] > 0


class TestGameStateTracker:
    def test_initial_state(self) -> None:
        gst = GameStateTracker()
        assert gst.current_state == GAME_STATE_UNKNOWN
        assert gst.state_duration == 0

    def test_classify_loading(self) -> None:
        gst = GameStateTracker()
        state = gst.classify_state("Now loading...", params_changed=False, action_had_effect=False)
        assert state == GAME_STATE_LOADING

    def test_classify_menu(self) -> None:
        gst = GameStateTracker()
        state = gst.classify_state("I see a menu with options", params_changed=False, action_had_effect=True)
        assert state == GAME_STATE_MENU

    def test_classify_dialog(self) -> None:
        gst = GameStateTracker()
        state = gst.classify_state("NPC is speaking in a dialog box", params_changed=False, action_had_effect=True)
        assert state == GAME_STATE_DIALOG

    def test_classify_pause(self) -> None:
        gst = GameStateTracker()
        state = gst.classify_state("Game is paused", params_changed=False, action_had_effect=False)
        assert state == GAME_STATE_PAUSE

    def test_classify_gameplay_from_params(self) -> None:
        gst = GameStateTracker()
        state = gst.classify_state("Visitors walking around", params_changed=True, action_had_effect=True)
        assert state == GAME_STATE_GAMEPLAY

    def test_state_transition_tracking(self) -> None:
        gst = GameStateTracker()
        gst.update(1, "Title screen menu", params_changed=False, action_had_effect=True)
        assert gst.current_state == GAME_STATE_MENU
        gst.update(2, "Now loading", params_changed=False, action_had_effect=False)
        assert gst.current_state == GAME_STATE_LOADING
        gst.update(3, "Park view with visitors", params_changed=True, action_had_effect=True)
        assert gst.current_state == GAME_STATE_GAMEPLAY

    def test_state_duration(self) -> None:
        gst = GameStateTracker()
        gst.update(1, "visitors walking", params_changed=True, action_had_effect=True)
        gst.update(2, "visitors riding", params_changed=True, action_had_effect=True)
        gst.update(3, "park overview", params_changed=True, action_had_effect=True)
        # All gameplay, duration should increment
        assert gst.state_duration == 2  # 2 ticks after initial classification

    def test_format_for_prompt(self) -> None:
        gst = GameStateTracker()
        gst.update(1, "menu screen", params_changed=False, action_had_effect=True)
        text = gst.format_for_prompt()
        assert "menu" in text
        assert "D-pad" in text  # Menu hint

    def test_summary(self) -> None:
        gst = GameStateTracker()
        gst.update(1, "menu", params_changed=False, action_had_effect=True)
        gst.update(2, "loading", params_changed=False, action_had_effect=False)
        summary = gst.summary()
        assert summary["current_state"] == GAME_STATE_LOADING
        assert summary["transitions"] == 2  # unknown->menu, menu->loading


class TestParameterTrendAnalyzer:
    def test_initial_record(self) -> None:
        pta = ParameterTrendAnalyzer(window_size=5)
        trends = pta.record({"money": 5000, "satisfaction": 70})
        assert "money" in trends
        assert trends["money"]["value"] == 5000.0
        assert trends["money"]["delta"] == 0.0  # First record has no previous

    def test_rising_trend(self) -> None:
        pta = ParameterTrendAnalyzer(window_size=5)
        for i in range(5):
            trends = pta.record({"money": 5000 + i * 100})
        assert trends["money"]["direction"] == "rising"
        assert trends["money"]["velocity"] > 0

    def test_falling_trend(self) -> None:
        pta = ParameterTrendAnalyzer(window_size=5)
        for i in range(5):
            trends = pta.record({"satisfaction": 80 - i * 10})
        assert trends["satisfaction"]["direction"] == "falling"
        assert trends["satisfaction"]["velocity"] < 0

    def test_stable_trend(self) -> None:
        pta = ParameterTrendAnalyzer(window_size=5)
        for _ in range(5):
            trends = pta.record({"hp": 100})
        assert trends["hp"]["direction"] == "stable"

    def test_significant_change(self) -> None:
        pta = ParameterTrendAnalyzer(window_size=10)
        for _ in range(3):
            pta.record({"money": 5000})
        trends = pta.record({"money": 6000})  # Big jump
        assert trends["money"]["significant_change"] is True

    def test_params_changed(self) -> None:
        pta = ParameterTrendAnalyzer()
        pta.record({"money": 100})
        trends = pta.record({"money": 200})
        assert pta.params_changed(trends) is True

    def test_params_not_changed(self) -> None:
        pta = ParameterTrendAnalyzer()
        pta.record({"money": 100})
        trends = pta.record({"money": 100})
        assert pta.params_changed(trends) is False

    def test_stagnant_params(self) -> None:
        pta = ParameterTrendAnalyzer(window_size=3)
        for _ in range(4):
            trends = pta.record({"money": 5000, "visitors": 50})
        stagnant = pta.get_stagnant_params(trends)
        assert "money" in stagnant
        assert "visitors" in stagnant

    def test_format_for_prompt(self) -> None:
        pta = ParameterTrendAnalyzer(window_size=5)
        for i in range(3):
            pta.record({"money": 5000 + i * 100})
        trends = pta.record({"money": 5300})
        text = pta.format_for_prompt(trends)
        assert "money" in text
        assert "Parameter trends" in text


class TestStrategyThreshold:
    def test_lt_operator(self) -> None:
        t = StrategyThreshold(parameter="money", operator="lt", value=1000, target_strategy="cost_reduction")
        assert t.evaluate({"money": 500}) is True
        assert t.evaluate({"money": 1500}) is False

    def test_gt_operator(self) -> None:
        t = StrategyThreshold(parameter="money", operator="gt", value=8000, target_strategy="expansion")
        assert t.evaluate({"money": 9000}) is True
        assert t.evaluate({"money": 5000}) is False

    def test_missing_parameter(self) -> None:
        t = StrategyThreshold(parameter="money", operator="lt", value=1000, target_strategy="cost_reduction")
        assert t.evaluate({"visitors": 50}) is False


class TestAdaptiveStrategyEngine:
    def test_default_strategy(self) -> None:
        engine = AdaptiveStrategyEngine(default_strategy="balanced")
        assert engine.current_strategy == "balanced"

    def test_low_money_triggers_cost_reduction(self) -> None:
        engine = AdaptiveStrategyEngine(default_strategy="balanced")
        result = engine.evaluate({"money": 500, "satisfaction": 60, "visitors": 30}, step=1)
        assert result == "cost_reduction"

    def test_low_satisfaction_triggers_satisfaction(self) -> None:
        engine = AdaptiveStrategyEngine(default_strategy="balanced")
        result = engine.evaluate({"money": 5000, "satisfaction": 20, "visitors": 30}, step=1)
        assert result == "satisfaction"

    def test_high_money_triggers_expansion(self) -> None:
        engine = AdaptiveStrategyEngine(default_strategy="balanced")
        result = engine.evaluate({"money": 10000, "satisfaction": 60, "visitors": 30}, step=1)
        assert result == "expansion"

    def test_no_threshold_reverts_to_default(self) -> None:
        engine = AdaptiveStrategyEngine(default_strategy="balanced")
        # First trigger a switch
        engine.evaluate({"money": 500}, step=1)
        assert engine.current_strategy == "cost_reduction"
        # Then all params normal — should revert
        engine.evaluate({"money": 5000, "satisfaction": 60, "visitors": 30}, step=2)
        assert engine.current_strategy == "balanced"

    def test_switch_count(self) -> None:
        engine = AdaptiveStrategyEngine(default_strategy="balanced")
        engine.evaluate({"money": 500}, step=1)  # switch to cost_reduction
        engine.evaluate({"money": 5000, "satisfaction": 60, "visitors": 30}, step=2)  # revert
        engine.evaluate({"money": 500}, step=3)  # switch again
        summary = engine.summary()
        assert summary["switch_count"] == 3

    def test_custom_thresholds(self) -> None:
        custom = [
            {"parameter": "hp", "operator": "lt", "value": 10, "target_strategy": "exploration", "priority": 10},
        ]
        engine = AdaptiveStrategyEngine(default_strategy="balanced", thresholds=custom)
        result = engine.evaluate({"hp": 5}, step=1)
        assert result == "exploration"

    def test_format_for_prompt(self) -> None:
        engine = AdaptiveStrategyEngine(default_strategy="balanced")
        engine.evaluate({"money": 500}, step=1)
        text = engine.format_for_prompt()
        assert "cost_reduction" in text

    def test_priority_ordering(self) -> None:
        """Higher priority thresholds should be evaluated first."""
        engine = AdaptiveStrategyEngine(default_strategy="balanced")
        # Both money<1000 (priority 10) and satisfaction<30 (priority 9) fire
        result = engine.evaluate({"money": 500, "satisfaction": 20}, step=1)
        # money has higher priority, so cost_reduction wins
        assert result == "cost_reduction"


class TestParseAndValidateResponse:
    """Tests for _parse_and_validate_response()."""

    def test_valid_json(self) -> None:
        import json
        raw = json.dumps({
            "action": ["up", "z"],
            "reasoning": "Navigate menu",
            "observations": "Title screen",
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == ["up", "z"]
        assert result["reasoning"] == "Navigate menu"
        assert result["observations"] == "Title screen"

    def test_invalid_json_returns_empty_action(self) -> None:
        result = _parse_and_validate_response("not json at all")
        assert result["action"] == []
        assert "Could not parse" in result["reasoning"]
        assert "not json" in result["observations"]

    def test_empty_string(self) -> None:
        result = _parse_and_validate_response("")
        assert result["action"] == []

    def test_json_array_instead_of_object(self) -> None:
        result = _parse_and_validate_response('[1, 2, 3]')
        assert result["action"] == []
        assert "not an object" in result["reasoning"]

    def test_invalid_key_names_stripped(self) -> None:
        import json
        raw = json.dumps({
            "action": ["up", "banana", "z", "fly_away", "down"],
            "reasoning": "test",
            "observations": "test",
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == ["up", "z", "down"]

    def test_action_as_single_string(self) -> None:
        import json
        raw = json.dumps({
            "action": "up",
            "reasoning": "go up",
            "observations": "screen",
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == ["up"]

    def test_action_as_single_invalid_string(self) -> None:
        import json
        raw = json.dumps({
            "action": "jump",
            "reasoning": "go up",
            "observations": "screen",
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == []

    def test_missing_fields_use_defaults(self) -> None:
        result = _parse_and_validate_response("{}")
        assert result["action"] == []
        assert result["reasoning"] == ""
        assert result["observations"] == ""

    def test_non_string_reasoning_coerced(self) -> None:
        import json
        raw = json.dumps({
            "action": ["z"],
            "reasoning": 42,
            "observations": None,
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == ["z"]
        assert result["reasoning"] == "42"
        assert result["observations"] == "None"

    def test_non_string_items_in_action_list_skipped(self) -> None:
        import json
        raw = json.dumps({
            "action": ["up", 123, None, "down"],
            "reasoning": "test",
            "observations": "test",
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == ["up", "down"]

    def test_action_is_integer_defaults_to_empty(self) -> None:
        import json
        raw = json.dumps({
            "action": 999,
            "reasoning": "test",
            "observations": "test",
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == []

    def test_truncation_of_long_action_list(self) -> None:
        import json
        long_actions = ["up"] * (_MAX_ACTIONS_PER_STEP + 5)
        raw = json.dumps({
            "action": long_actions,
            "reasoning": "spam",
            "observations": "test",
        })
        result = _parse_and_validate_response(raw)
        assert len(result["action"]) == _MAX_ACTIONS_PER_STEP

    def test_case_insensitive_key_matching(self) -> None:
        import json
        raw = json.dumps({
            "action": ["UP", "Down", "Z", "ENTER"],
            "reasoning": "test",
            "observations": "test",
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == ["up", "down", "z", "enter"]

    def test_whitespace_in_key_names_stripped(self) -> None:
        import json
        raw = json.dumps({
            "action": [" up ", "  z"],
            "reasoning": "test",
            "observations": "test",
        })
        result = _parse_and_validate_response(raw)
        assert result["action"] == ["up", "z"]

    def test_all_valid_keys_accepted(self) -> None:
        import json
        all_keys = sorted(VALID_KEYS)
        raw = json.dumps({
            "action": all_keys,
            "reasoning": "test all",
            "observations": "test",
        })
        result = _parse_and_validate_response(raw)
        # May be truncated to _MAX_ACTIONS_PER_STEP, but every returned
        # key must be valid and none should have been rejected.
        expected = all_keys[:_MAX_ACTIONS_PER_STEP]
        assert result["action"] == expected


# ------------------------------------------------------------------
# GPT4VAnalyzer multi-language prompt tests
# ------------------------------------------------------------------


class TestGPT4VAnalyzerMultiLang:
    """Tests for multi-language support in GPT4VAnalyzer.analyze_screen()."""

    def _make_analyzer(self):
        """Create a GPT4VAnalyzer with a mocked OpenAI client."""
        analyzer = GPT4VAnalyzer.__new__(GPT4VAnalyzer)
        # Create a mock client that records the messages sent
        mock_client = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.choices = [mock.MagicMock()]
        mock_response.choices[0].message.content = '{"action": ["z"], "reasoning": "test", "observations": "test"}'
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_client.chat.completions.create.return_value = mock_response
        analyzer.client = mock_client
        return analyzer, mock_client

    def _get_messages(self, mock_client):
        """Extract messages from the mock client call."""
        call_args = mock_client.chat.completions.create.call_args
        return call_args.kwargs["messages"]

    def test_system_prompt_always_has_multi_language_block(self) -> None:
        analyzer, mock_client = self._make_analyzer()
        analyzer.analyze_screen(image_b64="dGVzdA==", context="test")
        messages = self._get_messages(mock_client)
        system = messages[0]["content"]
        assert "Multi-language support:" in system
        assert "Japanese text (kanji, hiragana, katakana)" in system
        assert "brief translation or summary" in system

    def test_system_prompt_includes_lang_hint(self) -> None:
        analyzer, mock_client = self._make_analyzer()
        analyzer.analyze_screen(image_b64="dGVzdA==", context="test", lang_hint="ja")
        messages = self._get_messages(mock_client)
        system = messages[0]["content"]
        assert "Language hint for this game: ja" in system

    def test_system_prompt_no_lang_hint_when_empty(self) -> None:
        analyzer, mock_client = self._make_analyzer()
        analyzer.analyze_screen(image_b64="dGVzdA==", context="test")
        messages = self._get_messages(mock_client)
        system = messages[0]["content"]
        assert "Language hint for this game" not in system

    def test_user_prompt_includes_game_state(self) -> None:
        analyzer, mock_client = self._make_analyzer()
        analyzer.analyze_screen(image_b64="dGVzdA==", context="test", game_state="menu")
        messages = self._get_messages(mock_client)
        user_parts = messages[1]["content"]
        user_text = user_parts[1]["text"]
        assert "Current game state: menu" in user_text

    def test_user_prompt_includes_lang_hint(self) -> None:
        analyzer, mock_client = self._make_analyzer()
        analyzer.analyze_screen(image_b64="dGVzdA==", context="test", lang_hint="ja")
        messages = self._get_messages(mock_client)
        user_parts = messages[1]["content"]
        user_text = user_parts[1]["text"]
        assert "Game language: ja" in user_text

    def test_user_prompt_no_game_state_when_empty(self) -> None:
        analyzer, mock_client = self._make_analyzer()
        analyzer.analyze_screen(image_b64="dGVzdA==", context="test")
        messages = self._get_messages(mock_client)
        user_parts = messages[1]["content"]
        user_text = user_parts[1]["text"]
        assert "Current game state:" not in user_text

    def test_user_prompt_no_lang_when_empty(self) -> None:
        analyzer, mock_client = self._make_analyzer()
        analyzer.analyze_screen(image_b64="dGVzdA==", context="test")
        messages = self._get_messages(mock_client)
        user_parts = messages[1]["content"]
        user_text = user_parts[1]["text"]
        assert "Game language:" not in user_text


class TestAIAgentLangHint:
    """Tests for AIAgent lang_hint field."""

    def test_default_lang_hint_empty(self) -> None:
        agent = AIAgent(game_id="TEST")
        assert agent.lang_hint == ""

    def test_lang_hint_set(self) -> None:
        agent = AIAgent(game_id="TEST", lang_hint="ja")
        assert agent.lang_hint == "ja"


# ------------------------------------------------------------------
# ActionHistory export / load tests
# ------------------------------------------------------------------


class TestActionHistoryExport:
    """Tests for ActionHistory.to_dict(), save(), load(), from_session_json()."""

    @staticmethod
    def _sample_history(n: int = 3) -> ActionHistory:
        h = ActionHistory(max_size=10)
        for i in range(n):
            h.add(ActionRecord(
                step=i + 1,
                action=["up", "z"],
                reasoning=f"reason {i}",
                observations=f"obs {i}",
                parameters={"money": 1000 * (i + 1)},
            ))
        return h

    def test_action_history_to_dict(self) -> None:
        h = self._sample_history(2)
        result = h.to_dict()
        assert isinstance(result, list)
        assert len(result) == 2
        for entry in result:
            assert set(entry.keys()) == {"step", "action", "reasoning", "observations", "parameters"}
            assert isinstance(entry["step"], int)
            assert isinstance(entry["action"], list)
            assert isinstance(entry["reasoning"], str)
            assert isinstance(entry["observations"], str)
            assert isinstance(entry["parameters"], dict)
        assert result[0]["step"] == 1
        assert result[1]["parameters"] == {"money": 2000}

    def test_action_history_save_load_roundtrip(self, tmp_path: Path) -> None:
        h = self._sample_history(3)
        save_path = tmp_path / "history.json"
        returned = h.save(save_path)
        assert returned == save_path

        loaded = ActionHistory.load(save_path)
        assert len(loaded.records) == 3
        for orig, restored in zip(h.records, loaded.records):
            assert orig.step == restored.step
            assert orig.action == restored.action
            assert orig.reasoning == restored.reasoning
            assert orig.observations == restored.observations
            assert orig.parameters == restored.parameters

    def test_action_history_load_nonexistent(self, tmp_path: Path) -> None:
        loaded = ActionHistory.load(tmp_path / "does_not_exist.json")
        assert len(loaded.records) == 0

    def test_action_history_load_truncates(self, tmp_path: Path) -> None:
        h = self._sample_history(5)
        save_path = tmp_path / "history.json"
        h.save(save_path)

        loaded = ActionHistory.load(save_path, max_size=3)
        assert len(loaded.records) == 3
        # Should keep the last 3 (steps 3, 4, 5)
        assert loaded.records[0].step == 3
        assert loaded.records[-1].step == 5

    def test_action_history_save_creates_file(self, tmp_path: Path) -> None:
        h = self._sample_history(1)
        save_path = tmp_path / "sub" / "history.json"
        save_path.parent.mkdir(parents=True)
        h.save(save_path)
        assert save_path.exists()
        assert save_path.stat().st_size > 0

    def test_from_session_json_raises(self, tmp_path: Path) -> None:
        import pytest
        with pytest.raises(NotImplementedError):
            ActionHistory.from_session_json(tmp_path / "session.json")
