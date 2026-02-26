"""Tests for address_manager.py."""

from __future__ import annotations

from pathlib import Path

from address_manager import AddressManager


def test_load_nonexistent_game(tmp_path: Path) -> None:
    """Loading a nonexistent game returns empty parameters."""
    mgr = AddressManager(tmp_path / "addresses")
    ga = mgr.load("NONEXISTENT")
    assert ga.game_id == "NONEXISTENT"
    assert len(ga.parameters) == 0


def test_add_and_load_parameter(tmp_path: Path) -> None:
    """Add a parameter and verify it persists."""
    addr_dir = tmp_path / "addresses"
    mgr = AddressManager(addr_dir)
    mgr.add_parameter("TEST-001", "money", "0x1000", "int32", "Gold count")

    ga = mgr.load("TEST-001")
    assert "money" in ga.parameters
    assert ga.parameters["money"].address == "0x1000"
    assert ga.parameters["money"].type == "int32"


def test_remove_parameter(tmp_path: Path) -> None:
    """Remove a parameter and verify it's gone."""
    mgr = AddressManager(tmp_path / "addresses")
    mgr.add_parameter("TEST-001", "money", "0x1000", "int32")
    mgr.add_parameter("TEST-001", "hp", "0x1004", "uint16")
    mgr.remove_parameter("TEST-001", "money")

    ga = mgr.load("TEST-001")
    assert "money" not in ga.parameters
    assert "hp" in ga.parameters


def test_get_parameter_addresses(tmp_addresses_dir: Path) -> None:
    """get_parameter_addresses returns correct int/type tuples."""
    mgr = AddressManager(tmp_addresses_dir)
    addrs = mgr.get_parameter_addresses("TEST-001")
    assert "money" in addrs
    assert addrs["money"] == (0x001000, "int32")
    assert addrs["hp"] == (0x001004, "uint16")


def test_list_games(tmp_path: Path) -> None:
    """list_games returns all game IDs."""
    mgr = AddressManager(tmp_path / "addresses")
    mgr.add_parameter("GAME-A", "x", "0x0", "int32")
    mgr.add_parameter("GAME-B", "y", "0x0", "int32")
    games = mgr.list_games()
    assert "GAME-A" in games
    assert "GAME-B" in games
