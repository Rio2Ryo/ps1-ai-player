#!/usr/bin/env python3
"""Periodically poll PS1 memory addresses and log values to CSV.

Reads address definitions from address_manager and uses memory_scanner
to read values at a configurable interval.
"""

from __future__ import annotations

import csv
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TextIO

from address_manager import AddressManager
from memory_scanner import MemoryScanner

DEFAULT_LOG_DIR = Path.home() / "ps1-ai-player" / "logs"
DEFAULT_INTERVAL = 5.0  # seconds


class MemoryLogger:
    """Polls memory addresses and writes CSV logs."""

    def __init__(
        self,
        game_id: str,
        scanner: MemoryScanner | None = None,
        log_dir: Path = DEFAULT_LOG_DIR,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.game_id = game_id
        self.interval = interval
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.scanner = scanner or MemoryScanner()
        self.address_manager = AddressManager()
        self.parameters = self.address_manager.get_parameter_addresses(game_id)

        if not self.parameters:
            print(f"Warning: No parameters defined for game {game_id}")
            print("Use address_manager.py to add parameters first.")

        self._running = False
        self._csv_file: TextIO | None = None
        self._csv_writer: csv.writer | None = None
        self._frame_count = 0

    def _create_log_file(self) -> tuple[TextIO, csv.writer]:
        """Create a new CSV log file with header."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{self.game_id}.csv"
        filepath = self.log_dir / filename
        print(f"Logging to: {filepath}")

        f = open(filepath, "w", newline="")
        writer = csv.writer(f)

        # Write header
        header = ["timestamp", "frame"] + list(self.parameters.keys())
        writer.writerow(header)
        f.flush()

        return f, writer

    def _read_all_parameters(self) -> dict[str, int | float]:
        """Read all registered parameters from memory."""
        values: dict[str, int | float] = {}
        for name, (address, data_type) in self.parameters.items():
            try:
                values[name] = self.scanner.read_address(address, data_type)
            except Exception as e:
                values[name] = -1  # Error sentinel
                print(f"Warning: Could not read {name} at 0x{address:06X}: {e}")
        return values

    def _log_row(self, values: dict[str, int | float]) -> None:
        """Write one row to the CSV."""
        if self._csv_writer is None:
            return

        timestamp = datetime.now().isoformat()
        row = [timestamp, self._frame_count]
        for name in self.parameters:
            row.append(values.get(name, -1))
        self._csv_writer.writerow(row)

        if self._csv_file is not None:
            self._csv_file.flush()

    def start(self) -> None:
        """Start the logging loop. Blocks until Ctrl+C."""
        if not self.parameters:
            print("No parameters to log. Exiting.")
            return

        self._csv_file, self._csv_writer = self._create_log_file()
        self._running = True

        # Handle Ctrl+C gracefully
        def signal_handler(sig: int, frame: object) -> None:
            print("\nStopping logger...")
            self._running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print(
            f"Logging {len(self.parameters)} parameters every {self.interval}s. "
            f"Press Ctrl+C to stop."
        )
        print(f"Parameters: {', '.join(self.parameters.keys())}")

        try:
            while self._running:
                values = self._read_all_parameters()
                self._log_row(values)
                self._frame_count += 1

                # Print current values
                parts = [f"{k}={v}" for k, v in values.items()]
                print(f"[{self._frame_count}] {' | '.join(parts)}", end="\r")

                time.sleep(self.interval)
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop logging and close the file."""
        self._running = False
        if self._csv_file is not None:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None
        self.scanner.close()
        print(f"\nLogged {self._frame_count} samples.")


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="PS1 Memory Logger")
    parser.add_argument("--game", "-g", required=True, help="Game ID")
    parser.add_argument(
        "--interval",
        "-i",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"Polling interval in seconds (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="Log output directory",
    )
    parser.add_argument("--pid", type=int, default=None, help="DuckStation PID")

    args = parser.parse_args()

    scanner = MemoryScanner(pid=args.pid) if args.pid else MemoryScanner()
    logger = MemoryLogger(
        game_id=args.game,
        scanner=scanner,
        log_dir=args.log_dir,
        interval=args.interval,
    )
    logger.start()


if __name__ == "__main__":
    main()
