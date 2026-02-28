#!/usr/bin/env python3
"""Manage discovered memory addresses per game, stored as JSON files.

Each game has its own JSON file in ~/ps1-ai-player/addresses/{game_id}.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_ADDRESSES_DIR = Path.home() / "ps1-ai-player" / "addresses"


@dataclass
class ParameterInfo:
    """A discovered memory parameter."""

    address: str  # hex string e.g. "0x1F800000"
    type: str  # data type e.g. "int32"
    description: str = ""


@dataclass
class GameAddresses:
    """Collection of discovered addresses for a specific game."""

    game_id: str
    parameters: dict[str, ParameterInfo] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "game_id": self.game_id,
            "parameters": {
                name: asdict(info) for name, info in self.parameters.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameAddresses:
        """Deserialize from dictionary."""
        params = {}
        for name, info in data.get("parameters", {}).items():
            params[name] = ParameterInfo(
                address=info["address"],
                type=info["type"],
                description=info.get("description", ""),
            )
        return cls(game_id=data["game_id"], parameters=params)


class AddressManager:
    """Load, save, and manipulate per-game address files."""

    def __init__(self, addresses_dir: Path = DEFAULT_ADDRESSES_DIR) -> None:
        self.addresses_dir = addresses_dir
        self.addresses_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_game(self, game_id: str) -> Path:
        """Get the JSON file path for a game ID."""
        safe_id = game_id.replace("/", "_").replace("\\", "_")
        return self.addresses_dir / f"{safe_id}.json"

    def load(self, game_id: str) -> GameAddresses:
        """Load addresses for a game. Returns empty if file doesn't exist."""
        path = self._path_for_game(game_id)
        if path.exists():
            data = json.loads(path.read_text())
            return GameAddresses.from_dict(data)
        return GameAddresses(game_id=game_id)

    def save(self, addresses: GameAddresses) -> Path:
        """Save addresses to JSON file."""
        path = self._path_for_game(addresses.game_id)
        path.write_text(json.dumps(addresses.to_dict(), indent=2, ensure_ascii=False))
        return path

    def add_parameter(
        self,
        game_id: str,
        name: str,
        address: str,
        data_type: str,
        description: str = "",
    ) -> None:
        """Add or update a parameter for a game."""
        ga = self.load(game_id)
        ga.parameters[name] = ParameterInfo(
            address=address, type=data_type, description=description
        )
        path = self.save(ga)
        print(f"Added '{name}' (0x{int(address, 16):06X}, {data_type}) to {game_id}")
        print(f"Saved to: {path}")

    def remove_parameter(self, game_id: str, name: str) -> None:
        """Remove a parameter from a game."""
        ga = self.load(game_id)
        if name in ga.parameters:
            del ga.parameters[name]
            self.save(ga)
            print(f"Removed '{name}' from {game_id}")
        else:
            print(f"Parameter '{name}' not found in {game_id}")

    def list_parameters(self, game_id: str) -> None:
        """Print all parameters for a game."""
        ga = self.load(game_id)
        if not ga.parameters:
            print(f"No parameters registered for {game_id}")
            return

        print(f"Game: {game_id}")
        print(f"{'Name':<20} {'Address':<14} {'Type':<10} Description")
        print("-" * 70)
        for name, info in ga.parameters.items():
            print(f"{name:<20} {info.address:<14} {info.type:<10} {info.description}")

    def list_games(self) -> list[str]:
        """List all game IDs with saved addresses."""
        games: list[str] = []
        for path in self.addresses_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                games.append(data.get("game_id", path.stem))
            except (json.JSONDecodeError, KeyError):
                continue
        return games

    def get_parameter_addresses(self, game_id: str) -> dict[str, tuple[int, str]]:
        """Get parameter name -> (address_int, data_type) mapping.

        Useful for memory_logger and ai_agent integration.
        """
        ga = self.load(game_id)
        result: dict[str, tuple[int, str]] = {}
        for name, info in ga.parameters.items():
            addr = int(info.address, 16)
            result[name] = (addr, info.type)
        return result

    def export_addresses(self, game_id: str, path: Path, fmt: str = "json") -> Path:
        """Export addresses to a JSON or CSV file.

        Args:
            game_id: Game ID to export.
            path: Destination file path.
            fmt: ``"json"`` or ``"csv"``.

        Returns:
            The path the data was written to.
        """
        ga = self.load(game_id)
        path = Path(path)
        if fmt == "json":
            path.write_text(json.dumps(ga.to_dict(), indent=2, ensure_ascii=False))
        elif fmt == "csv":
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["name", "address", "type", "description"])
                for name, info in ga.parameters.items():
                    writer.writerow([name, info.address, info.type, info.description])
        else:
            raise ValueError(f"Unsupported format: {fmt!r} (expected 'json' or 'csv')")
        return path

    def import_addresses(
        self, game_id: str, path: Path, fmt: str | None = None, merge: bool = True
    ) -> int:
        """Import addresses from a JSON or CSV file.

        Args:
            game_id: Target game ID.
            path: Source file path.
            fmt: ``"json"``, ``"csv"``, or ``None`` (auto-detect from extension).
            merge: If ``True``, merge with existing parameters (overwrite on name
                collision). If ``False``, clear existing parameters first.

        Returns:
            The number of parameters imported.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Import file not found: {path}")

        if fmt is None:
            ext = path.suffix.lower()
            if ext == ".json":
                fmt = "json"
            elif ext == ".csv":
                fmt = "csv"
            else:
                raise ValueError(
                    f"Cannot auto-detect format from extension {ext!r}. "
                    "Specify fmt='json' or fmt='csv'."
                )

        imported_params: dict[str, ParameterInfo] = {}
        if fmt == "json":
            data = json.loads(path.read_text())
            ga_imported = GameAddresses.from_dict(data)
            imported_params = ga_imported.parameters
        elif fmt == "csv":
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    imported_params[row["name"]] = ParameterInfo(
                        address=row["address"],
                        type=row["type"],
                        description=row.get("description", ""),
                    )
        else:
            raise ValueError(f"Unsupported format: {fmt!r} (expected 'json' or 'csv')")

        ga = self.load(game_id)
        if not merge:
            ga.parameters.clear()
        ga.parameters.update(imported_params)
        self.save(ga)
        return len(imported_params)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="PS1 Memory Address Manager")
    parser.add_argument("--game", "-g", required=True, help="Game ID (e.g., SLPM-86023)")
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_ADDRESSES_DIR,
        help="Addresses directory",
    )

    subparsers = parser.add_subparsers(dest="action")

    # list
    subparsers.add_parser("list", aliases=["--list", "-l"], help="List parameters")

    # add
    add_parser = subparsers.add_parser("add", aliases=["--add"], help="Add a parameter")
    add_parser.add_argument("name", help="Parameter name")
    add_parser.add_argument("address", help="Hex address (e.g., 0x1F800000)")
    add_parser.add_argument("type", help="Data type (e.g., int32)")
    add_parser.add_argument("description", nargs="?", default="", help="Description")

    # remove
    rm_parser = subparsers.add_parser(
        "remove", aliases=["--remove"], help="Remove a parameter"
    )
    rm_parser.add_argument("name", help="Parameter name to remove")

    # games
    subparsers.add_parser("games", help="List all games with saved addresses")

    # export
    export_parser = subparsers.add_parser("export", help="Export addresses to file")
    export_parser.add_argument("path", type=Path, help="Output file path")
    export_parser.add_argument(
        "--format",
        "-f",
        dest="fmt",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)",
    )

    # import
    import_parser = subparsers.add_parser("import", help="Import addresses from file")
    import_parser.add_argument("path", type=Path, help="Input file path")
    import_parser.add_argument(
        "--format",
        "-f",
        dest="fmt",
        choices=["json", "csv"],
        default=None,
        help="Input format (default: auto-detect from extension)",
    )
    import_parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Clear existing parameters before importing",
    )

    args = parser.parse_args()
    manager = AddressManager(args.dir)

    if args.action in ("list", "--list", "-l", None):
        manager.list_parameters(args.game)
    elif args.action in ("add", "--add"):
        manager.add_parameter(
            args.game, args.name, args.address, args.type, args.description
        )
    elif args.action in ("remove", "--remove"):
        manager.remove_parameter(args.game, args.name)
    elif args.action == "games":
        games = manager.list_games()
        if games:
            print("Games with saved addresses:")
            for g in games:
                print(f"  {g}")
        else:
            print("No games found.")
    elif args.action == "export":
        out = manager.export_addresses(args.game, args.path, fmt=args.fmt)
        print(f"Exported {args.game} to {out} (format: {args.fmt})")
    elif args.action == "import":
        count = manager.import_addresses(
            args.game, args.path, fmt=args.fmt, merge=not args.no_merge
        )
        mode = "merge" if not args.no_merge else "replace"
        print(f"Imported {count} parameters into {args.game} (mode: {mode})")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
