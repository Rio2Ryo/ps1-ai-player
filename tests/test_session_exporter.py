"""Tests for session_exporter.py — SessionExporter + CLI."""
from __future__ import annotations

import csv
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from session_exporter import SessionExporter, main as cli_main
from session_replay import SessionData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_session_files(
    directory: Path,
    game_id: str = "DEMO",
    timestamp: str = "20250101_120000",
    num_steps: int = 20,
    *,
    session_info: dict | None = None,
) -> Path:
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = directory / f"{stem}.csv"
    session_path = directory / f"{stem}.session.json"
    history_path = directory / f"{stem}.history.json"

    directory.mkdir(parents=True, exist_ok=True)
    base_time = datetime(2025, 1, 1, 12, 0, 0)
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning",
                         "observations", "hp", "mp", "gold"])
        for i in range(num_steps):
            ts = base_time + timedelta(seconds=i * 5)
            writer.writerow([
                ts.isoformat(), i, f"action_{i % 3}",
                f"reason_{i}", f"obs_{i}",
                100 - i, 50 + i * 2, 200 + i * 10,
            ])

    if session_info is None:
        session_info = {
            "cost": {"total_cost_usd": 0.1234},
            "strategy": {"current": "balanced"},
        }
    session_path.write_text(json.dumps(session_info))
    history_path.write_text(json.dumps([
        {"step": i, "action": [f"action_{i % 3}"]}
        for i in range(min(10, num_steps))
    ]))

    return csv_path


# ---------------------------------------------------------------------------
# TestSessionExporter
# ---------------------------------------------------------------------------

class TestSessionExporter:
    def test_export_zip_creates_file(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        out = tmp_path / "export.zip"
        result = exporter.export_zip(out)
        assert result.exists()
        assert result.suffix == ".zip"

    def test_export_zip_contains_session_files(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        out = tmp_path / "export.zip"
        exporter.export_zip(out)

        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert any(n.endswith(".csv") for n in names)
            assert any(n.endswith(".session.json") for n in names)
            assert any(n.endswith(".history.json") for n in names)

    def test_export_zip_contains_action_report(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        out = tmp_path / "export.zip"
        exporter.export_zip(out)

        with zipfile.ZipFile(out) as zf:
            assert "analysis/action_report.md" in zf.namelist()
            content = zf.read("analysis/action_report.md").decode()
            assert "Action Analysis Report" in content

    def test_export_zip_cross_session_when_multiple(self, tmp_path: Path) -> None:
        _write_session_files(tmp_path, timestamp="20250101_120000")
        csv2 = _write_session_files(tmp_path, timestamp="20250102_120000")
        session = SessionData.from_log_path(csv2)
        exporter = SessionExporter(session)
        out = tmp_path / "export.zip"
        exporter.export_zip(out)

        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "analysis/cross_session.md" in names
            assert "analysis/cross_session.json" in names

    def test_export_zip_no_cross_session_when_single(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        out = tmp_path / "export.zip"
        exporter.export_zip(out)

        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "analysis/cross_session.md" not in names

    def test_export_bytes(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        data = exporter.export_bytes()
        assert isinstance(data, bytes)
        assert len(data) > 0
        # Should be a valid ZIP
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert any(n.endswith(".csv") for n in zf.namelist())

    def test_list_zip_contents(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        out = tmp_path / "export.zip"
        exporter.export_zip(out)

        contents = SessionExporter.list_zip_contents(out)
        assert isinstance(contents, list)
        assert len(contents) >= 4  # csv + session.json + history.json + action_report

    def test_import_zip(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path / "source")
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        zip_path = tmp_path / "export.zip"
        exporter.export_zip(zip_path)

        target = tmp_path / "imported"
        extracted = SessionExporter.import_zip(zip_path, target)
        assert len(extracted) == 3  # csv + session.json + history.json
        assert any(f.suffix == ".csv" for f in extracted)
        # Should be loadable
        csv_file = [f for f in extracted if f.suffix == ".csv"][0]
        s = SessionData.from_log_path(csv_file)
        assert s.game_id == "DEMO"

    def test_import_zip_skips_analysis(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path / "source")
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        zip_path = tmp_path / "export.zip"
        exporter.export_zip(zip_path)

        target = tmp_path / "imported"
        extracted = SessionExporter.import_zip(zip_path, target)
        # No analysis/ files should be extracted
        for f in extracted:
            assert "analysis" not in f.name

    def test_import_zip_creates_target_dir(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path / "source")
        session = SessionData.from_log_path(csv_path)
        exporter = SessionExporter(session)
        zip_path = tmp_path / "export.zip"
        exporter.export_zip(zip_path)

        target = tmp_path / "new" / "deep" / "dir"
        assert not target.exists()
        SessionExporter.import_zip(zip_path, target)
        assert target.exists()


# ---------------------------------------------------------------------------
# TestSessionExporterCLI
# ---------------------------------------------------------------------------

class TestSessionExporterCLI:
    def test_cli_export(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path)
        out = tmp_path / "test_export.zip"
        cli_main(["export", str(csv_path), "--output", str(out)])
        assert out.exists()
        captured = capsys.readouterr().out
        assert "Exported to" in captured

    def test_cli_export_default_output(self, tmp_path: Path) -> None:
        csv_path = _write_session_files(tmp_path)
        cli_main(["export", str(csv_path)])
        expected = csv_path.with_suffix(".zip")
        assert expected.exists()

    def test_cli_import(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path / "source")
        session = SessionData.from_log_path(csv_path)
        zip_path = tmp_path / "export.zip"
        SessionExporter(session).export_zip(zip_path)

        target = tmp_path / "imported"
        cli_main(["import", str(zip_path), "--target-dir", str(target)])
        captured = capsys.readouterr().out
        assert "Imported" in captured

    def test_cli_list(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        csv_path = _write_session_files(tmp_path)
        zip_path = tmp_path / "export.zip"
        SessionExporter(SessionData.from_log_path(csv_path)).export_zip(zip_path)

        cli_main(["list", str(zip_path)])
        captured = capsys.readouterr().out
        assert ".csv" in captured

    def test_cli_no_command(self) -> None:
        with pytest.raises(SystemExit):
            cli_main([])
