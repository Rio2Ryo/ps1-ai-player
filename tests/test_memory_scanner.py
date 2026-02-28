"""Tests for memory_scanner.py.

All /proc filesystem and os.open/read/write/lseek/close calls are mocked
so tests run without ptrace permissions or a real DuckStation process.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from memory_scanner import (
    DATA_TYPES,
    PS1_RAM_SIZE,
    MemoryScanner,
    ScanResult,
    export_scan_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_maps_content(*entries: tuple[int, int, str, int, str]) -> str:
    """Build /proc/PID/maps text from (start, end, perms, offset, pathname) tuples."""
    lines: list[str] = []
    for start, end, perms, offset, pathname in entries:
        # Mimic kernel format: start-end perms offset dev inode pathname
        lines.append(
            f"{start:012x}-{end:012x} {perms} {offset:08x} 00:00 0  {pathname}"
        )
    return "\n".join(lines)


def _build_fake_ram(size: int = PS1_RAM_SIZE) -> bytearray:
    """Return a zeroed bytearray representing PS1 RAM."""
    return bytearray(size)


def _scanner_with_base(pid: int = 1234, base_offset: int = 0x7F000000) -> MemoryScanner:
    """Create a MemoryScanner with predetermined pid and base_offset, skipping __post_init__."""
    scanner = MemoryScanner.__new__(MemoryScanner)
    scanner.pid = pid
    scanner.base_offset = base_offset
    scanner._mem_fd = None
    return scanner


# ---------------------------------------------------------------------------
# _find_ps1_ram_offset — 4-pass fallback logic
# ---------------------------------------------------------------------------


class TestFindPs1RamOffset:
    """Tests for the 4-pass fallback strategy in _find_ps1_ram_offset()."""

    def _make_scanner_and_find(self, maps_text: str) -> int:
        """Create a scanner with mocked maps file and invoke _find_ps1_ram_offset."""
        scanner = MemoryScanner.__new__(MemoryScanner)
        scanner.pid = 9999
        scanner.base_offset = 0
        scanner._mem_fd = None

        maps_path = Path(f"/proc/{scanner.pid}/maps")
        with patch.object(Path, "read_text", return_value=maps_text):
            return scanner._find_ps1_ram_offset()

    def test_pass1_exact_2mb_anon_rw_offset0(self) -> None:
        """Pass 1: exact 2 MB anonymous rw-p mapping with offset 0."""
        maps = _make_maps_content(
            # Decoy: file-backed
            (0x400000, 0x600000, "rw-p", 0, "/usr/lib/libfoo.so"),
            # Target: exact 2 MB anon rw-p offset=0
            (0x7F000000, 0x7F000000 + PS1_RAM_SIZE, "rw-p", 0, ""),
        )
        assert self._make_scanner_and_find(maps) == 0x7F000000

    def test_pass2_exact_2mb_anon_rw_nonzero_offset(self) -> None:
        """Pass 2: exact 2 MB anonymous writable mapping with non-zero offset."""
        maps = _make_maps_content(
            # No pass-1 match (offset != 0), but pass-2 matches
            (0x50000000, 0x50000000 + PS1_RAM_SIZE, "rw-p", 0x1000, ""),
        )
        assert self._make_scanner_and_find(maps) == 0x50000000

    def test_pass3_larger_anon_rw_up_to_8mb(self) -> None:
        """Pass 3: larger anon rw region (>2 MB, <=8 MB), offset 0."""
        big_size = PS1_RAM_SIZE * 3  # 6 MB — within 4× limit
        maps = _make_maps_content(
            (0x60000000, 0x60000000 + big_size, "rw-p", 0, ""),
        )
        assert self._make_scanner_and_find(maps) == 0x60000000

    def test_pass4_fallback_writable_plausible_size(self) -> None:
        """Pass 4: fallback to any writable mapping of plausible size."""
        # File-backed writable 4 MB — only pass 4 matches
        maps = _make_maps_content(
            (0x80000000, 0x80000000 + PS1_RAM_SIZE * 2, "rw-p", 0x1000, "/some/file"),
        )
        assert self._make_scanner_and_find(maps) == 0x80000000

    def test_priority_pass1_over_pass3(self) -> None:
        """Pass 1 candidate is preferred over pass 3 candidate."""
        maps = _make_maps_content(
            # Pass 3 candidate: 4 MB anon
            (0x60000000, 0x60000000 + PS1_RAM_SIZE * 2, "rw-p", 0, ""),
            # Pass 1 candidate: exact 2 MB anon offset=0
            (0x7F000000, 0x7F000000 + PS1_RAM_SIZE, "rw-p", 0, ""),
        )
        assert self._make_scanner_and_find(maps) == 0x7F000000

    def test_no_matching_region_returns_zero(self) -> None:
        """Returns 0 when no suitable region exists."""
        maps = _make_maps_content(
            # Too small
            (0x400000, 0x401000, "rw-p", 0, ""),
            # Read-only
            (0x500000, 0x500000 + PS1_RAM_SIZE, "r--p", 0, ""),
            # Way too large (> 8× PS1_RAM_SIZE)
            (0x600000, 0x600000 + PS1_RAM_SIZE * 20, "rw-p", 0, ""),
        )
        assert self._make_scanner_and_find(maps) == 0

    def test_pid_none_returns_zero(self) -> None:
        """Returns 0 when pid is None."""
        scanner = MemoryScanner.__new__(MemoryScanner)
        scanner.pid = None
        scanner.base_offset = 0
        scanner._mem_fd = None
        assert scanner._find_ps1_ram_offset() == 0

    def test_permission_error_returns_zero(self) -> None:
        """Returns 0 when /proc/PID/maps is unreadable."""
        scanner = MemoryScanner.__new__(MemoryScanner)
        scanner.pid = 9999
        scanner.base_offset = 0
        scanner._mem_fd = None
        with patch.object(Path, "read_text", side_effect=PermissionError):
            assert scanner._find_ps1_ram_offset() == 0

    def test_pass2_skips_non_writable(self) -> None:
        """Non-writable exact-2MB mapping is not matched by pass 2."""
        maps = _make_maps_content(
            (0x7F000000, 0x7F000000 + PS1_RAM_SIZE, "r--p", 0, ""),
        )
        assert self._make_scanner_and_find(maps) == 0

    def test_pass3_skips_nonzero_offset(self) -> None:
        """Pass 3 requires offset 0; non-zero offset falls through."""
        big_size = PS1_RAM_SIZE * 2
        maps = _make_maps_content(
            # offset != 0, so pass 3 skips; pass 4 picks it up
            (0x60000000, 0x60000000 + big_size, "rw-p", 0x1000, ""),
        )
        result = self._make_scanner_and_find(maps)
        # Should fall through to pass 4 (any writable plausible)
        assert result == 0x60000000

    def test_rwx_mapping_matched(self) -> None:
        """An rwx mapping is writable, so it matches pass 1."""
        maps = _make_maps_content(
            (0x7F000000, 0x7F000000 + PS1_RAM_SIZE, "rwxp", 0, ""),
        )
        assert self._make_scanner_and_find(maps) == 0x7F000000


# ---------------------------------------------------------------------------
# read_address / write_address
# ---------------------------------------------------------------------------


class TestReadWriteAddress:
    """Tests for read_address() and write_address() via mocked os calls."""

    FAKE_FD = 42
    BASE = 0x7F000000

    def _patch_os(self, ram: bytearray):
        """Return a context manager that patches os.open/lseek/read/write/close
        to operate on *ram* with offset = BASE."""
        pos = [0]

        def fake_open(path, flags):
            return self.FAKE_FD

        def fake_lseek(fd, offset, whence):
            assert fd == self.FAKE_FD
            pos[0] = offset - self.BASE
            return offset

        def fake_read(fd, size):
            assert fd == self.FAKE_FD
            data = bytes(ram[pos[0]: pos[0] + size])
            pos[0] += size
            return data

        def fake_write(fd, data):
            assert fd == self.FAKE_FD
            ram[pos[0]: pos[0] + len(data)] = data
            pos[0] += len(data)
            return len(data)

        def fake_close(fd):
            pass

        return patch.multiple(
            os,
            open=fake_open,
            lseek=fake_lseek,
            read=fake_read,
            write=fake_write,
            close=fake_close,
        )

    def test_read_int32(self) -> None:
        ram = _build_fake_ram()
        struct.pack_into("<i", ram, 0x1000, 99999)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            assert scanner.read_address(0x1000, "int32") == 99999

    def test_read_uint16(self) -> None:
        ram = _build_fake_ram()
        struct.pack_into("<H", ram, 0x2000, 65535)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            assert scanner.read_address(0x2000, "uint16") == 65535

    def test_read_int8(self) -> None:
        ram = _build_fake_ram()
        struct.pack_into("b", ram, 0x0010, -42)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            assert scanner.read_address(0x0010, "int8") == -42

    def test_read_float32(self) -> None:
        ram = _build_fake_ram()
        struct.pack_into("<f", ram, 0x3000, 3.14)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            val = scanner.read_address(0x3000, "float32")
            assert abs(val - 3.14) < 1e-5

    def test_write_int32_then_read_back(self) -> None:
        ram = _build_fake_ram()
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            scanner.write_address(0x1000, 12345, "int32")
            assert scanner.read_address(0x1000, "int32") == 12345

    def test_write_uint8(self) -> None:
        ram = _build_fake_ram()
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            scanner.write_address(0x0050, 200, "uint8")
            assert scanner.read_address(0x0050, "uint8") == 200

    def test_write_float32(self) -> None:
        ram = _build_fake_ram()
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            scanner.write_address(0x4000, 1.5, "float32")
            val = scanner.read_address(0x4000, "float32")
            assert abs(val - 1.5) < 1e-7


# ---------------------------------------------------------------------------
# scan_value
# ---------------------------------------------------------------------------


class TestScanValue:
    """Tests for scan_value() via mocked memory."""

    FAKE_FD = 42
    BASE = 0x7F000000

    def _patch_os(self, ram: bytearray):
        pos = [0]

        def fake_open(path, flags):
            return self.FAKE_FD

        def fake_lseek(fd, offset, whence):
            pos[0] = offset - self.BASE
            return offset

        def fake_read(fd, size):
            data = bytes(ram[pos[0]: pos[0] + size])
            pos[0] += size
            return data

        def fake_close(fd):
            pass

        return patch.multiple(
            os,
            open=fake_open,
            lseek=fake_lseek,
            read=fake_read,
            close=fake_close,
        )

    def test_scan_finds_single_match(self) -> None:
        ram = _build_fake_ram(0x1000)  # small region for speed
        struct.pack_into("<i", ram, 0x0100, 42)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            results = scanner.scan_value(42, "int32", start=0, end=0x1000)
        assert len(results) == 1
        assert results[0].address == 0x0100
        assert results[0].value == 42

    def test_scan_finds_multiple_matches(self) -> None:
        ram = _build_fake_ram(0x1000)
        for offset in (0x0100, 0x0200, 0x0400):
            struct.pack_into("<i", ram, offset, 77)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            results = scanner.scan_value(77, "int32", start=0, end=0x1000)
        assert len(results) == 3
        addrs = {r.address for r in results}
        assert addrs == {0x0100, 0x0200, 0x0400}

    def test_scan_no_match(self) -> None:
        ram = _build_fake_ram(0x0400)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            results = scanner.scan_value(999, "int32", start=0, end=0x0400)
        assert results == []

    def test_scan_uint16(self) -> None:
        ram = _build_fake_ram(0x0400)
        struct.pack_into("<H", ram, 0x0080, 1234)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            results = scanner.scan_value(1234, "uint16", start=0, end=0x0400)
        assert len(results) >= 1
        assert any(r.address == 0x0080 for r in results)

    def test_scan_respects_alignment(self) -> None:
        ram = _build_fake_ram(0x0100)
        # Place a uint16 value at an odd offset
        struct.pack_into("<H", ram, 0x0003, 5555)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            # Default alignment=2 should miss offset 0x0003
            results_aligned = scanner.scan_value(5555, "uint16", start=0, end=0x0100)
            # Explicit alignment=1 should find it
            results_unaligned = scanner.scan_value(
                5555, "uint16", start=0, end=0x0100, alignment=1
            )
        assert not any(r.address == 0x0003 for r in results_aligned)
        assert any(r.address == 0x0003 for r in results_unaligned)


# ---------------------------------------------------------------------------
# filter_changed / filter_unchanged
# ---------------------------------------------------------------------------


class TestFilterOperations:
    """Tests for filter_changed() and filter_unchanged()."""

    FAKE_FD = 42
    BASE = 0x7F000000

    def _patch_os(self, ram: bytearray):
        pos = [0]

        def fake_open(path, flags):
            return self.FAKE_FD

        def fake_lseek(fd, offset, whence):
            pos[0] = offset - self.BASE
            return offset

        def fake_read(fd, size):
            data = bytes(ram[pos[0]: pos[0] + size])
            pos[0] += size
            return data

        def fake_close(fd):
            pass

        return patch.multiple(
            os,
            open=fake_open,
            lseek=fake_lseek,
            read=fake_read,
            close=fake_close,
        )

    def test_filter_changed(self) -> None:
        ram = _build_fake_ram(0x1000)
        # Two addresses initially hold 10
        struct.pack_into("<i", ram, 0x0100, 10)
        struct.pack_into("<i", ram, 0x0200, 10)
        prev = [
            ScanResult(address=0x0100, value=10, data_type="int32"),
            ScanResult(address=0x0200, value=10, data_type="int32"),
        ]
        # Now change only 0x0100 to 20
        struct.pack_into("<i", ram, 0x0100, 20)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            filtered = scanner.filter_changed(prev, 20)
        assert len(filtered) == 1
        assert filtered[0].address == 0x0100
        assert filtered[0].value == 20

    def test_filter_unchanged(self) -> None:
        ram = _build_fake_ram(0x1000)
        struct.pack_into("<i", ram, 0x0100, 10)
        struct.pack_into("<i", ram, 0x0200, 10)
        prev = [
            ScanResult(address=0x0100, value=10, data_type="int32"),
            ScanResult(address=0x0200, value=10, data_type="int32"),
        ]
        # Change 0x0200 to something else
        struct.pack_into("<i", ram, 0x0200, 99)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            filtered = scanner.filter_unchanged(prev)
        assert len(filtered) == 1
        assert filtered[0].address == 0x0100


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_open_mem_raises_without_pid(self) -> None:
        scanner = _scanner_with_base()
        scanner.pid = None
        with pytest.raises(RuntimeError, match="No DuckStation PID"):
            scanner._open_mem()

    def test_close_mem_idempotent(self) -> None:
        scanner = _scanner_with_base()
        scanner._mem_fd = None
        # Should not raise
        scanner._close_mem()
        scanner._close_mem()

    def test_close_mem_calls_os_close(self) -> None:
        scanner = _scanner_with_base()
        scanner._mem_fd = 99
        with patch.object(os, "close") as mock_close:
            scanner._close_mem()
            mock_close.assert_called_once_with(99)
        assert scanner._mem_fd is None

    def test_data_types_coverage(self) -> None:
        """All documented data types are present and have valid struct formats."""
        expected = {"int8", "uint8", "int16", "uint16", "int32", "uint32", "float32"}
        assert set(DATA_TYPES.keys()) == expected
        for name, (fmt, size) in DATA_TYPES.items():
            # struct.calcsize should match declared size
            assert struct.calcsize(fmt) == size, f"Mismatch for {name}"

    def test_ps1_ram_size_constant(self) -> None:
        assert PS1_RAM_SIZE == 0x200000  # 2 MB


# ---------------------------------------------------------------------------
# scan_value — float32 tolerance
# ---------------------------------------------------------------------------


class TestScanValueFloat32:
    """Tests for float32 approximate matching in scan_value()."""

    FAKE_FD = 42
    BASE = 0x7F000000

    def _patch_os(self, ram: bytearray):
        pos = [0]

        def fake_open(path, flags):
            return self.FAKE_FD

        def fake_lseek(fd, offset, whence):
            pos[0] = offset - self.BASE
            return offset

        def fake_read(fd, size):
            data = bytes(ram[pos[0]: pos[0] + size])
            pos[0] += size
            return data

        def fake_close(fd):
            pass

        return patch.multiple(
            os,
            open=fake_open,
            lseek=fake_lseek,
            read=fake_read,
            close=fake_close,
        )

    def test_scan_value_float32_exact_match(self) -> None:
        """float32 exact value matches within default tolerance."""
        ram = _build_fake_ram(0x1000)
        struct.pack_into("<f", ram, 0x0100, 3.14)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            results = scanner.scan_value(3.14, "float32", start=0, end=0x1000)
        assert len(results) >= 1
        assert any(r.address == 0x0100 for r in results)

    def test_scan_value_float32_tolerance(self) -> None:
        """float32 value with small error within tolerance is matched."""
        ram = _build_fake_ram(0x1000)
        # Pack a value slightly different from target
        target = 100.0
        slightly_off = 100.005  # relative error = 0.005 / 100 = 5e-5 < 1e-4
        struct.pack_into("<f", ram, 0x0200, slightly_off)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            results = scanner.scan_value(target, "float32", start=0, end=0x1000)
        assert any(r.address == 0x0200 for r in results)

    def test_scan_value_float32_out_of_tolerance(self) -> None:
        """float32 value outside tolerance is not matched."""
        ram = _build_fake_ram(0x1000)
        target = 100.0
        far_off = 101.0  # relative error = 1.0 / 101.0 ~ 0.0099 >> 1e-4
        struct.pack_into("<f", ram, 0x0200, far_off)
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            results = scanner.scan_value(target, "float32", start=0, end=0x1000)
        assert not any(r.address == 0x0200 for r in results)

    def test_scan_value_int_ignores_tolerance(self) -> None:
        """int32 scan uses exact byte match and ignores tolerance parameter."""
        ram = _build_fake_ram(0x1000)
        struct.pack_into("<i", ram, 0x0100, 42)
        struct.pack_into("<i", ram, 0x0200, 43)  # off by 1
        scanner = _scanner_with_base(base_offset=self.BASE)
        with self._patch_os(ram):
            results = scanner.scan_value(42, "int32", start=0, end=0x1000, tolerance=0.5)
        # Only exact match at 0x0100, not 0x0200 despite large tolerance
        assert len(results) == 1
        assert results[0].address == 0x0100


# ---------------------------------------------------------------------------
# export_scan_results
# ---------------------------------------------------------------------------


class TestExportScanResults:
    """Tests for export_scan_results() CSV export."""

    def test_export_scan_results_csv(self, tmp_path: Path) -> None:
        """CSV contains header and correct rows."""
        results = [
            ScanResult(address=0x001000, value=42, data_type="int32"),
            ScanResult(address=0x002000, value=3.14, data_type="float32"),
        ]
        out = export_scan_results(results, tmp_path / "out.csv")
        assert out == tmp_path / "out.csv"
        lines = out.read_text().splitlines()
        assert lines[0] == "address,value,data_type"
        assert lines[1] == "0x001000,42,int32"
        assert lines[2] == "0x002000,3.14,float32"
        assert len(lines) == 3

    def test_export_scan_results_empty(self, tmp_path: Path) -> None:
        """Empty results list produces header-only CSV."""
        out = export_scan_results([], tmp_path / "empty.csv")
        lines = out.read_text().splitlines()
        assert len(lines) == 1
        assert lines[0] == "address,value,data_type"
