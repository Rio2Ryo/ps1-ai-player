"""Tests for memory_logger.py.

MemoryScanner is fully mocked — no /proc access or ptrace required.
AddressManager reads from a temporary JSON fixture on disk.
"""

from __future__ import annotations

import csv
import json
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memory_logger import MemoryLogger


# ====================================================================
# Fixtures
# ====================================================================

GAME_ID = "TEST-001"

ADDR_JSON = {
    "game_id": GAME_ID,
    "parameters": {
        "money": {"address": "0x001000", "type": "int32", "description": "Gold"},
        "hp": {"address": "0x001004", "type": "uint16", "description": "Health"},
    },
}


@pytest.fixture()
def addr_dir(tmp_path: Path) -> Path:
    """Create a temp addresses directory with a two-parameter game."""
    d = tmp_path / "addresses"
    d.mkdir()
    (d / f"{GAME_ID}.json").write_text(json.dumps(ADDR_JSON))
    return d


@pytest.fixture()
def mock_scanner() -> MagicMock:
    scanner = MagicMock()
    scanner.read_address.return_value = 42
    return scanner


def _make_logger(
    tmp_path: Path,
    addr_dir: Path,
    scanner: MagicMock,
    *,
    game_id: str = GAME_ID,
    interval: float = 0.0,
) -> MemoryLogger:
    """Build a MemoryLogger wired to the mock scanner and temp dirs."""
    log_dir = tmp_path / "logs"
    with patch("memory_logger.AddressManager") as MockAM:
        from address_manager import AddressManager

        real_am = AddressManager(addresses_dir=addr_dir)
        MockAM.return_value = real_am
        logger = MemoryLogger(
            game_id=game_id,
            scanner=scanner,
            log_dir=log_dir,
            interval=interval,
        )
    return logger


# ====================================================================
# Constructor
# ====================================================================


class TestInit:
    def test_parameters_loaded(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """Constructor loads parameters from address_manager fixture."""
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        assert "money" in logger.parameters
        assert "hp" in logger.parameters
        assert logger.parameters["money"] == (0x001000, "int32")

    def test_log_dir_created(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        assert logger.log_dir.is_dir()

    def test_initial_state(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        assert logger._running is False
        assert logger._frame_count == 0
        assert logger._csv_file is None

    def test_no_parameters_warns(
        self, tmp_path: Path, mock_scanner: MagicMock
    ) -> None:
        """Game with no registered addresses prints a warning."""
        empty_dir = tmp_path / "empty_addr"
        empty_dir.mkdir()
        logger = _make_logger(
            tmp_path, empty_dir, mock_scanner, game_id="NONEXISTENT"
        )
        assert logger.parameters == {}


# ====================================================================
# _create_log_file
# ====================================================================


class TestCreateLogFile:
    def test_csv_header(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """CSV file starts with correct header row."""
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        f, writer = logger._create_log_file()
        f.close()

        csv_files = list(logger.log_dir.glob("*.csv"))
        assert len(csv_files) == 1

        with open(csv_files[0]) as fh:
            reader = csv.reader(fh)
            header = next(reader)
        assert header[0] == "timestamp"
        assert header[1] == "frame"
        assert "money" in header
        assert "hp" in header

    def test_filename_contains_game_id(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        f, _ = logger._create_log_file()
        f.close()
        csv_files = list(logger.log_dir.glob("*.csv"))
        assert any(GAME_ID in p.name for p in csv_files)


# ====================================================================
# _read_all_parameters
# ====================================================================


class TestReadAllParameters:
    def test_calls_scanner_per_param(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        values = logger._read_all_parameters()
        assert mock_scanner.read_address.call_count == 2
        assert values["money"] == 42
        assert values["hp"] == 42

    def test_returns_different_values(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        mock_scanner.read_address.side_effect = [1000, 255]
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        values = logger._read_all_parameters()
        assert values["money"] == 1000
        assert values["hp"] == 255

    def test_exception_returns_sentinel(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """Scanner exception for one param → -1, other param still read."""
        mock_scanner.read_address.side_effect = [OSError("read fail"), 99]
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        values = logger._read_all_parameters()
        assert values["money"] == -1
        assert values["hp"] == 99


# ====================================================================
# _log_row
# ====================================================================


class TestLogRow:
    def test_writes_row_to_csv(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        logger._csv_file, logger._csv_writer = logger._create_log_file()
        logger._frame_count = 7
        logger._log_row({"money": 5000, "hp": 200})
        logger._csv_file.close()

        csv_path = list(logger.log_dir.glob("*.csv"))[0]
        with open(csv_path) as fh:
            rows = list(csv.reader(fh))
        # header + 1 data row
        assert len(rows) == 2
        data = rows[1]
        assert data[1] == "7"  # frame
        # money and hp values present (column order matches header)
        header = rows[0]
        money_idx = header.index("money")
        hp_idx = header.index("hp")
        assert data[money_idx] == "5000"
        assert data[hp_idx] == "200"

    def test_noop_without_writer(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """_log_row does nothing if _csv_writer is None."""
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        # Should not raise
        logger._log_row({"money": 100, "hp": 50})

    def test_missing_param_uses_sentinel(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """Missing key in values dict → -1 in CSV."""
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        logger._csv_file, logger._csv_writer = logger._create_log_file()
        logger._log_row({"money": 5000})  # hp missing
        logger._csv_file.close()

        csv_path = list(logger.log_dir.glob("*.csv"))[0]
        with open(csv_path) as fh:
            rows = list(csv.reader(fh))
        header = rows[0]
        hp_idx = header.index("hp")
        assert rows[1][hp_idx] == "-1"


# ====================================================================
# start / stop — polling loop
# ====================================================================


class TestStartStop:
    def _run_n_ticks(
        self,
        logger: MemoryLogger,
        n: int,
    ) -> None:
        """Patch time.sleep to stop the loop after *n* iterations."""
        call_count = 0

        def fake_sleep(_interval: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= n:
                logger._running = False

        with patch("memory_logger.time.sleep", side_effect=fake_sleep):
            logger.start()

    def test_basic_loop(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """start() polls scanner, writes CSV, increments frame_count."""
        mock_scanner.read_address.return_value = 100
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        self._run_n_ticks(logger, 3)

        assert logger._frame_count == 3
        csv_path = list(logger.log_dir.glob("*.csv"))[0]
        with open(csv_path) as fh:
            rows = list(csv.reader(fh))
        # header + 3 data rows
        assert len(rows) == 4

    def test_varying_values(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """Each tick reads new values from the scanner."""
        mock_scanner.read_address.side_effect = [
            1000, 200,  # tick 1
            1100, 190,  # tick 2
        ]
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        self._run_n_ticks(logger, 2)

        csv_path = list(logger.log_dir.glob("*.csv"))[0]
        with open(csv_path) as fh:
            rows = list(csv.reader(fh))
        header = rows[0]
        money_idx = header.index("money")
        assert rows[1][money_idx] == "1000"
        assert rows[2][money_idx] == "1100"

    def test_no_params_returns_early(
        self, tmp_path: Path, mock_scanner: MagicMock
    ) -> None:
        """start() returns immediately when no parameters are registered."""
        empty_dir = tmp_path / "empty_addr"
        empty_dir.mkdir()
        logger = _make_logger(
            tmp_path, empty_dir, mock_scanner, game_id="EMPTY"
        )
        # Should return without blocking
        logger.start()
        assert logger._frame_count == 0

    def test_stop_closes_file_and_scanner(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        self._run_n_ticks(logger, 1)
        # After start() finishes it calls stop() in finally
        assert logger._csv_file is None
        assert logger._csv_writer is None
        mock_scanner.close.assert_called()

    def test_stop_idempotent(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """Calling stop() multiple times does not raise."""
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        self._run_n_ticks(logger, 1)
        # Already stopped; call again
        logger.stop()
        logger.stop()

    def test_scanner_error_mid_loop(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """Scanner error writes -1 but loop continues."""
        mock_scanner.read_address.side_effect = [
            42, 99,                    # tick 1: ok
            OSError("fail"), 50,       # tick 2: money fails, hp ok
            77, 88,                    # tick 3: ok
        ]
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)
        self._run_n_ticks(logger, 3)

        csv_path = list(logger.log_dir.glob("*.csv"))[0]
        with open(csv_path) as fh:
            rows = list(csv.reader(fh))
        header = rows[0]
        money_idx = header.index("money")
        assert rows[2][money_idx] == "-1"  # tick 2
        assert rows[3][money_idx] == "77"  # tick 3 recovered


# ====================================================================
# Signal handling
# ====================================================================


class TestSignalHandling:
    def test_signal_handler_stops_loop(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """SIGINT/SIGTERM handler sets _running = False."""
        mock_scanner.read_address.return_value = 1
        logger = _make_logger(tmp_path, addr_dir, mock_scanner)

        original_sigint = signal.getsignal(signal.SIGINT)

        def fake_sleep(_interval: float) -> None:
            # Simulate the signal being delivered during sleep
            handler = signal.getsignal(signal.SIGINT)
            if callable(handler):
                handler(signal.SIGINT, None)

        with patch("memory_logger.time.sleep", side_effect=fake_sleep):
            logger.start()

        # Loop should have stopped after 1 tick (signal fires during sleep)
        assert logger._frame_count == 1

        # Restore to avoid polluting other tests
        signal.signal(signal.SIGINT, original_sigint)


# ====================================================================
# Integration: full cycle
# ====================================================================


class TestIntegration:
    def test_full_cycle_csv_content(
        self, tmp_path: Path, addr_dir: Path, mock_scanner: MagicMock
    ) -> None:
        """End-to-end: init → start(5 ticks) → verify CSV rows & values."""
        values_sequence = [
            (1000, 200),
            (1010, 195),
            (1020, 190),
            (1030, 185),
            (1040, 180),
        ]
        flat = [v for pair in values_sequence for v in pair]
        mock_scanner.read_address.side_effect = flat

        logger = _make_logger(tmp_path, addr_dir, mock_scanner)

        call_count = 0

        def fake_sleep(_: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 5:
                logger._running = False

        with patch("memory_logger.time.sleep", side_effect=fake_sleep):
            logger.start()

        # Verify CSV
        csv_path = list(logger.log_dir.glob("*.csv"))[0]
        with open(csv_path) as fh:
            rows = list(csv.reader(fh))

        header = rows[0]
        assert header[:2] == ["timestamp", "frame"]
        assert len(rows) == 6  # header + 5 data

        money_idx = header.index("money")
        hp_idx = header.index("hp")
        for i, (m, h) in enumerate(values_sequence):
            assert rows[i + 1][money_idx] == str(m)
            assert rows[i + 1][hp_idx] == str(h)
            assert rows[i + 1][1] == str(i)  # frame counter

    def test_multiple_games_separate_files(
        self, tmp_path: Path, mock_scanner: MagicMock
    ) -> None:
        """Different game_ids produce different CSV files."""
        addr_dir = tmp_path / "addrs"
        addr_dir.mkdir()
        for gid in ("GAME-A", "GAME-B"):
            data = {
                "game_id": gid,
                "parameters": {
                    "score": {
                        "address": "0x002000",
                        "type": "int32",
                        "description": "",
                    }
                },
            }
            (addr_dir / f"{gid}.json").write_text(json.dumps(data))

        mock_scanner.read_address.return_value = 1

        for gid in ("GAME-A", "GAME-B"):
            logger = _make_logger(
                tmp_path, addr_dir, mock_scanner, game_id=gid
            )
            call_count = 0

            def fake_sleep(_, _lc=[0]) -> None:  # noqa: B006
                _lc[0] += 1
                if _lc[0] >= 1:
                    logger._running = False
                    _lc[0] = 0

            with patch("memory_logger.time.sleep", side_effect=fake_sleep):
                logger.start()

        log_dir = tmp_path / "logs"
        csv_files = list(log_dir.glob("*.csv"))
        names = [p.name for p in csv_files]
        assert any("GAME-A" in n for n in names)
        assert any("GAME-B" in n for n in names)
