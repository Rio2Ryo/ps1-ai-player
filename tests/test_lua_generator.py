"""Tests for lua_generator.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from lua_generator import generate_lua_script


def test_generate_lua_script(tmp_addresses_dir: Path) -> None:
    """Generate Lua script from test addresses."""
    script = generate_lua_script("TEST-001", addresses_dir=tmp_addresses_dir)
    assert 'GAME_ID = "TEST-001"' in script
    assert "Memory.ReadDWord" in script  # int32
    assert "Memory.ReadWord" in script   # uint16
    assert "money" in script
    assert "hp" in script


def test_generate_lua_no_addresses(tmp_path: Path) -> None:
    """Raises ValueError when no addresses exist for game."""
    addr_dir = tmp_path / "addresses"
    addr_dir.mkdir()
    with pytest.raises(ValueError, match="No addresses found"):
        generate_lua_script("NONEXISTENT", addresses_dir=addr_dir)


def test_lua_script_has_callbacks(tmp_addresses_dir: Path) -> None:
    """Generated script includes DuckStation callbacks."""
    script = generate_lua_script("TEST-001", addresses_dir=tmp_addresses_dir)
    assert "function OnScriptLoaded()" in script
    assert "function UpdatePerFrame()" in script
    assert "function OnScriptUnloaded()" in script
