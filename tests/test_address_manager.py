"""Tests for address_manager.py."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

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


# ---------- export / import tests ----------


def test_export_json(tmp_addresses_dir: Path, tmp_path: Path) -> None:
    """JSON export contains the expected structure."""
    mgr = AddressManager(tmp_addresses_dir)
    out = mgr.export_addresses("TEST-001", tmp_path / "out.json", fmt="json")
    data = json.loads(out.read_text())
    assert data["game_id"] == "TEST-001"
    assert "money" in data["parameters"]
    assert data["parameters"]["money"]["address"] == "0x001000"
    assert data["parameters"]["hp"]["type"] == "uint16"


def test_export_csv(tmp_addresses_dir: Path, tmp_path: Path) -> None:
    """CSV export has correct header and data rows."""
    mgr = AddressManager(tmp_addresses_dir)
    out = mgr.export_addresses("TEST-001", tmp_path / "out.csv", fmt="csv")
    with open(out, newline="") as f:
        reader = list(csv.reader(f))
    assert reader[0] == ["name", "address", "type", "description"]
    names = {row[0] for row in reader[1:]}
    assert names == {"money", "hp"}


def test_import_json(tmp_addresses_dir: Path, tmp_path: Path) -> None:
    """JSON import populates parameters correctly."""
    mgr = AddressManager(tmp_addresses_dir)
    # export then re-import into a new game
    mgr.export_addresses("TEST-001", tmp_path / "exp.json", fmt="json")
    count = mgr.import_addresses("IMPORT-J", tmp_path / "exp.json", fmt="json")
    assert count == 2
    ga = mgr.load("IMPORT-J")
    assert ga.parameters["money"].address == "0x001000"
    assert ga.parameters["hp"].type == "uint16"


def test_import_csv(tmp_addresses_dir: Path, tmp_path: Path) -> None:
    """CSV import populates parameters correctly."""
    mgr = AddressManager(tmp_addresses_dir)
    mgr.export_addresses("TEST-001", tmp_path / "exp.csv", fmt="csv")
    count = mgr.import_addresses("IMPORT-C", tmp_path / "exp.csv", fmt="csv")
    assert count == 2
    ga = mgr.load("IMPORT-C")
    assert ga.parameters["money"].address == "0x001000"
    assert ga.parameters["hp"].description == "Health"


def test_import_merge_true(tmp_addresses_dir: Path, tmp_path: Path) -> None:
    """merge=True keeps existing params and adds/overwrites imported ones."""
    mgr = AddressManager(tmp_addresses_dir)
    # Add an extra param only in target game
    mgr.add_parameter("TEST-001", "mp", "0x002000", "uint16", "Mana")
    # Create a small JSON with just money (different description)
    import_data = {
        "game_id": "TEST-001",
        "parameters": {
            "money": {"address": "0x001000", "type": "int32", "description": "Coins"},
        },
    }
    imp_file = tmp_path / "merge.json"
    imp_file.write_text(json.dumps(import_data))
    count = mgr.import_addresses("TEST-001", imp_file, fmt="json", merge=True)
    assert count == 1
    ga = mgr.load("TEST-001")
    # mp should still exist
    assert "mp" in ga.parameters
    # money description overwritten
    assert ga.parameters["money"].description == "Coins"


def test_import_merge_false(tmp_addresses_dir: Path, tmp_path: Path) -> None:
    """merge=False clears existing params before importing."""
    mgr = AddressManager(tmp_addresses_dir)
    import_data = {
        "game_id": "TEST-001",
        "parameters": {
            "sp": {"address": "0x003000", "type": "int16", "description": "Stamina"},
        },
    }
    imp_file = tmp_path / "replace.json"
    imp_file.write_text(json.dumps(import_data))
    count = mgr.import_addresses("TEST-001", imp_file, fmt="json", merge=False)
    assert count == 1
    ga = mgr.load("TEST-001")
    # only sp should remain
    assert list(ga.parameters.keys()) == ["sp"]


def test_import_auto_format_json(tmp_addresses_dir: Path, tmp_path: Path) -> None:
    """fmt=None auto-detects JSON from .json extension."""
    mgr = AddressManager(tmp_addresses_dir)
    mgr.export_addresses("TEST-001", tmp_path / "auto.json", fmt="json")
    count = mgr.import_addresses("AUTO-J", tmp_path / "auto.json")
    assert count == 2


def test_import_auto_format_csv(tmp_addresses_dir: Path, tmp_path: Path) -> None:
    """fmt=None auto-detects CSV from .csv extension."""
    mgr = AddressManager(tmp_addresses_dir)
    mgr.export_addresses("TEST-001", tmp_path / "auto.csv", fmt="csv")
    count = mgr.import_addresses("AUTO-C", tmp_path / "auto.csv")
    assert count == 2


def test_export_empty_game(tmp_path: Path) -> None:
    """Exporting a game with no parameters produces valid but empty output."""
    mgr = AddressManager(tmp_path / "addresses")
    out_json = mgr.export_addresses("EMPTY", tmp_path / "empty.json", fmt="json")
    data = json.loads(out_json.read_text())
    assert data["parameters"] == {}

    out_csv = mgr.export_addresses("EMPTY", tmp_path / "empty.csv", fmt="csv")
    with open(out_csv, newline="") as f:
        rows = list(csv.reader(f))
    # header only, no data rows
    assert len(rows) == 1
    assert rows[0] == ["name", "address", "type", "description"]


def test_import_nonexistent_file(tmp_path: Path) -> None:
    """Importing from a nonexistent file raises FileNotFoundError."""
    mgr = AddressManager(tmp_path / "addresses")
    with pytest.raises(FileNotFoundError):
        mgr.import_addresses("X", tmp_path / "no_such_file.json")
