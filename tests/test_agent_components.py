"""Tests for ai_agent.py components (ActionHistory, CostTracker)."""

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

from ai_agent import ActionHistory, ActionRecord, CostTracker


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
