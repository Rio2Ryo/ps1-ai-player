#!/usr/bin/env python3
"""PS1 memory scanner that reads/writes DuckStation process memory via /proc/PID/mem.

Provides interactive memory scanning sessions for discovering game parameters.
PS1 RAM is 2MB: 0x00000000-0x001FFFFF.
"""

from __future__ import annotations

import csv
import os
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from log_config import get_logger

_log = get_logger(__name__)

# Data type definitions: (struct format, byte size)
DATA_TYPES: dict[str, tuple[str, int]] = {
    "int8": ("b", 1),
    "uint8": ("B", 1),
    "int16": ("<h", 2),
    "uint16": ("<H", 2),
    "int32": ("<i", 4),
    "uint32": ("<I", 4),
    "float32": ("<f", 4),
}

PS1_RAM_SIZE = 0x200000  # 2MB


@dataclass
class ScanResult:
    """A memory scan result entry."""

    address: int
    value: int | float
    data_type: str


@dataclass
class MemoryScanner:
    """Scans DuckStation process memory for PS1 game parameter values.

    Reads /proc/PID/mem directly with proper offset calculation.
    """

    pid: int | None = None
    base_offset: int = 0
    _mem_fd: int | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.pid is None:
            self.pid = self._find_duckstation_pid()
        if self.pid is not None:
            self.base_offset = self._find_ps1_ram_offset()

    @staticmethod
    def _find_duckstation_pid() -> int | None:
        """Auto-detect DuckStation PID from /proc."""
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_text()
                if "duckstation" in cmdline.lower():
                    pid = int(entry.name)
                    _log.info("Found DuckStation PID: %d", pid)
                    return pid
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
        _log.warning("DuckStation process not found.")
        return None

    def _find_ps1_ram_offset(self) -> int:
        """Parse /proc/PID/maps to find the PS1 RAM region base address.

        Uses a multi-pass strategy:
          1. Exact 2MB anonymous rw-p mapping (most reliable)
          2. Exact 2MB anonymous rwx mapping (some kernel configs)
          3. 2MB-aligned region within a larger anonymous rw mapping (8MB max)
          4. Any rw mapping whose size is a small multiple of 2MB
        """
        if self.pid is None:
            return 0

        maps_path = Path(f"/proc/{self.pid}/maps")
        try:
            maps_content = maps_path.read_text()
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            _log.warning("Cannot read %s. Try running with sudo.", maps_path)
            return 0

        # Parse all mappings once
        _MAP_RE = re.compile(
            r"^([0-9a-f]+)-([0-9a-f]+)\s+(r[w-][x-][ps-])\s+"
            r"([0-9a-f]+)\s+\S+\s+\d+\s*(.*)",
            re.IGNORECASE,
        )

        @dataclass
        class MapEntry:
            start: int
            end: int
            perms: str
            offset: int
            pathname: str

            @property
            def size(self) -> int:
                return self.end - self.start

            @property
            def is_anon(self) -> bool:
                return self.pathname == "" or self.pathname.startswith("[")

            @property
            def is_writable(self) -> bool:
                return len(self.perms) >= 2 and self.perms[1] == "w"

        entries: list[MapEntry] = []
        for line in maps_content.splitlines():
            m = _MAP_RE.match(line)
            if m:
                entries.append(MapEntry(
                    start=int(m.group(1), 16),
                    end=int(m.group(2), 16),
                    perms=m.group(3),
                    offset=int(m.group(4), 16),
                    pathname=m.group(5).strip(),
                ))

        # Pass 1: exact 2MB anonymous writable private mapping (offset 0)
        for e in entries:
            if e.size == PS1_RAM_SIZE and e.is_anon and e.is_writable and e.offset == 0:
                _log.info("Found PS1 RAM (exact 2MB anon rw): 0x%X", e.start)
                return e.start

        # Pass 2: exact 2MB anonymous writable (any offset)
        for e in entries:
            if e.size == PS1_RAM_SIZE and e.is_anon and e.is_writable:
                _log.info("Found PS1 RAM (exact 2MB anon): 0x%X", e.start)
                return e.start

        # Pass 3: larger anonymous rw region (up to 8MB) that could contain PS1 RAM
        for e in entries:
            if (
                e.is_anon
                and e.is_writable
                and PS1_RAM_SIZE < e.size <= PS1_RAM_SIZE * 4
                and e.offset == 0
            ):
                _log.info(
                    "Found candidate PS1 RAM region: 0x%X (size: 0x%X, using first 2MB)",
                    e.start, e.size,
                )
                return e.start

        # Pass 4: last resort - any writable mapping of plausible size
        for e in entries:
            if e.is_writable and e.size >= PS1_RAM_SIZE and e.size <= PS1_RAM_SIZE * 8:
                _log.warning(
                    "Using fallback mapping at 0x%X (size: 0x%X, perms: %s)",
                    e.start, e.size, e.perms,
                )
                return e.start

        _log.warning(
            "Could not locate PS1 RAM region in /proc/PID/maps. "
            "Scanned %d mappings for PID %s.", len(entries), self.pid,
        )
        return 0

    def _open_mem(self) -> int:
        """Open /proc/PID/mem for reading."""
        if self._mem_fd is not None:
            return self._mem_fd
        if self.pid is None:
            raise RuntimeError("No DuckStation PID available.")
        mem_path = f"/proc/{self.pid}/mem"
        self._mem_fd = os.open(mem_path, os.O_RDWR)
        return self._mem_fd

    def _close_mem(self) -> None:
        """Close the memory file descriptor."""
        if self._mem_fd is not None:
            os.close(self._mem_fd)
            self._mem_fd = None

    def _read_bytes(self, address: int, size: int) -> bytes:
        """Read raw bytes from PS1 memory at the given PS1 address."""
        fd = self._open_mem()
        real_addr = self.base_offset + address
        os.lseek(fd, real_addr, os.SEEK_SET)
        return os.read(fd, size)

    def _write_bytes(self, address: int, data: bytes) -> None:
        """Write raw bytes to PS1 memory at the given PS1 address."""
        fd = self._open_mem()
        real_addr = self.base_offset + address
        os.lseek(fd, real_addr, os.SEEK_SET)
        os.write(fd, data)

    def read_address(self, address: int, data_type: str = "int32") -> int | float:
        """Read a value from a PS1 memory address.

        Args:
            address: PS1 RAM address (0x000000 - 0x1FFFFF).
            data_type: One of int8, uint8, int16, uint16, int32, uint32, float32.

        Returns:
            The value at the given address.
        """
        fmt, size = DATA_TYPES[data_type]
        raw = self._read_bytes(address, size)
        return struct.unpack(fmt, raw)[0]

    def write_address(
        self, address: int, value: int | float, data_type: str = "int32"
    ) -> None:
        """Write a value to a PS1 memory address (for cheats/testing).

        Args:
            address: PS1 RAM address.
            value: Value to write.
            data_type: Data type format.
        """
        fmt, _size = DATA_TYPES[data_type]
        data = struct.pack(fmt, value)
        self._write_bytes(address, data)
        print(f"Wrote {value} to 0x{address:06X} ({data_type})")

    def scan_value(
        self,
        value: int | float,
        data_type: str = "int32",
        start: int = 0,
        end: int = PS1_RAM_SIZE,
        alignment: int | None = None,
        tolerance: float = 1e-4,
    ) -> list[ScanResult]:
        """Scan the entire PS1 RAM for addresses containing the given value.

        Args:
            value: The value to search for.
            data_type: Data type to scan as.
            start: Start address in PS1 RAM.
            end: End address in PS1 RAM.
            alignment: Address alignment (defaults to data size).
            tolerance: Relative error tolerance for float32 matching (ignored for int types).

        Returns:
            List of ScanResult with matching addresses.
        """
        fmt, size = DATA_TYPES[data_type]
        if alignment is None:
            alignment = size

        # Read entire PS1 RAM in one shot for speed
        raw_data = self._read_bytes(start, end - start)

        results: list[ScanResult] = []
        use_float_match = data_type == "float32"
        target_bytes = struct.pack(fmt, value)

        for offset in range(0, len(raw_data) - size + 1, alignment):
            chunk = raw_data[offset : offset + size]
            if use_float_match:
                actual = struct.unpack(fmt, chunk)[0]
                denom = max(abs(value), abs(actual), 1e-30)
                if abs(actual - value) / denom <= tolerance:
                    addr = start + offset
                    results.append(ScanResult(address=addr, value=actual, data_type=data_type))
            else:
                if chunk == target_bytes:
                    addr = start + offset
                    results.append(ScanResult(address=addr, value=value, data_type=data_type))

        print(f"Scan complete: {len(results)} addresses found with value {value}")
        return results

    def filter_changed(
        self,
        previous_results: list[ScanResult],
        new_value: int | float,
    ) -> list[ScanResult]:
        """Filter previous scan results to only addresses now holding new_value.

        Args:
            previous_results: Results from a previous scan.
            new_value: The expected new value.

        Returns:
            Filtered list of ScanResult.
        """
        filtered: list[ScanResult] = []
        for result in previous_results:
            current = self.read_address(result.address, result.data_type)
            if current == new_value:
                filtered.append(
                    ScanResult(
                        address=result.address,
                        value=new_value,
                        data_type=result.data_type,
                    )
                )
        print(
            f"Filter (changed to {new_value}): {len(filtered)}/{len(previous_results)} "
            f"addresses match"
        )
        return filtered

    def filter_unchanged(
        self, previous_results: list[ScanResult]
    ) -> list[ScanResult]:
        """Filter to only addresses whose value hasn't changed since last scan.

        Args:
            previous_results: Results from a previous scan.

        Returns:
            Filtered list of ScanResult where value is unchanged.
        """
        filtered: list[ScanResult] = []
        for result in previous_results:
            current = self.read_address(result.address, result.data_type)
            if current == result.value:
                filtered.append(result)
        print(
            f"Filter (unchanged): {len(filtered)}/{len(previous_results)} "
            f"addresses match"
        )
        return filtered

    def close(self) -> None:
        """Clean up resources."""
        self._close_mem()


def export_scan_results(results: list[ScanResult], path: Path) -> Path:
    """Export scan results to a CSV file.

    Args:
        results: List of ScanResult to export.
        path: Output file path.

    Returns:
        The path the CSV was written to.
    """
    path = Path(path)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "value", "data_type"])
        for r in results:
            writer.writerow([f"0x{r.address:06X}", r.value, r.data_type])
    _log.info("Exported %d scan results to %s", len(results), path)
    return path


def interactive_session() -> None:
    """Run an interactive memory scanning session."""
    print("=== PS1 Memory Scanner - Interactive Session ===")
    print("Commands:")
    print("  scan <value> [type]    - Scan for value (type: int8/uint8/.../int32)")
    print("  filter <value>         - Filter results to addresses with new value")
    print("  unchanged              - Filter to addresses with unchanged value")
    print("  read <hex_addr> [type] - Read a specific address")
    print("  write <hex_addr> <val> [type] - Write value to address")
    print("  results                - Show current result set")
    print("  export [path]          - Export results to CSV (default: ./scan_results.csv)")
    print("  pid <pid>              - Set DuckStation PID manually")
    print("  quit                   - Exit")
    print()

    scanner = MemoryScanner()
    current_results: list[ScanResult] = []

    while True:
        try:
            cmd = input("scanner> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not cmd:
            continue

        parts = cmd.split()
        command = parts[0].lower()

        try:
            if command == "quit" or command == "exit":
                break

            elif command == "pid":
                if len(parts) < 2:
                    print("Usage: pid <pid>")
                    continue
                scanner.close()
                scanner = MemoryScanner(pid=int(parts[1]))

            elif command == "scan":
                if len(parts) < 2:
                    print("Usage: scan <value> [type]")
                    continue
                value_str = parts[1]
                data_type = parts[2] if len(parts) > 2 else "int32"

                if data_type == "float32":
                    value: int | float = float(value_str)
                else:
                    value = int(value_str)

                current_results = scanner.scan_value(value, data_type)
                if len(current_results) <= 20:
                    for r in current_results:
                        print(f"  0x{r.address:06X} = {r.value}")

            elif command == "filter":
                if len(parts) < 2:
                    print("Usage: filter <new_value>")
                    continue
                if not current_results:
                    print("No previous scan results. Run 'scan' first.")
                    continue
                dtype = current_results[0].data_type
                if dtype == "float32":
                    new_val: int | float = float(parts[1])
                else:
                    new_val = int(parts[1])
                current_results = scanner.filter_changed(current_results, new_val)
                for r in current_results:
                    print(f"  0x{r.address:06X} = {r.value}")

            elif command == "unchanged":
                if not current_results:
                    print("No previous scan results. Run 'scan' first.")
                    continue
                current_results = scanner.filter_unchanged(current_results)
                for r in current_results:
                    print(f"  0x{r.address:06X} = {r.value}")

            elif command == "read":
                if len(parts) < 2:
                    print("Usage: read <hex_address> [type]")
                    continue
                addr = int(parts[1], 16)
                dtype = parts[2] if len(parts) > 2 else "int32"
                val = scanner.read_address(addr, dtype)
                print(f"  0x{addr:06X} = {val}")

            elif command == "write":
                if len(parts) < 3:
                    print("Usage: write <hex_address> <value> [type]")
                    continue
                addr = int(parts[1], 16)
                dtype = parts[3] if len(parts) > 3 else "int32"
                if dtype == "float32":
                    wval: int | float = float(parts[2])
                else:
                    wval = int(parts[2])
                scanner.write_address(addr, wval, dtype)

            elif command == "results":
                if not current_results:
                    print("No results.")
                else:
                    print(f"{len(current_results)} results:")
                    for r in current_results[:50]:
                        print(f"  0x{r.address:06X} = {r.value}")
                    if len(current_results) > 50:
                        print(f"  ... and {len(current_results) - 50} more")

            elif command == "export":
                if not current_results:
                    print("No results to export.")
                    continue
                export_path = Path(parts[1]) if len(parts) > 1 else Path("./scan_results.csv")
                out = export_scan_results(current_results, export_path)
                print(f"Exported {len(current_results)} results to {out}")

            else:
                print(f"Unknown command: {command}")

        except Exception as e:
            print(f"Error: {e}")

    scanner.close()


if __name__ == "__main__":
    interactive_session()
