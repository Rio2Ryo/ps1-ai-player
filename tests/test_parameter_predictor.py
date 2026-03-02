"""Tests for parameter_predictor.py — ParameterPredictor + CLI."""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parameter_predictor import ParameterPredictor, main as cli_main, plot_prediction
from session_replay import SessionData


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_session(tmp_path: Path, *, rows: int = 30,
                    hp_start: float = 100.0, hp_delta: float = -2.0,
                    gold_start: float = 500.0, gold_delta: float = 50.0,
                    flat_param: bool = False) -> SessionData:
    """Create a synthetic session with predictable linear trends."""
    stem = "20250101_120000_DEMO_agent"
    csv_path = tmp_path / f"{stem}.csv"
    session_path = tmp_path / f"{stem}.session.json"
    history_path = tmp_path / f"{stem}.history.json"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning", "observations",
                         "hp", "gold", "score"])
        for i in range(rows):
            hp = hp_start + hp_delta * i
            gold = gold_start + gold_delta * i
            score = 10.0 if flat_param else float(i * 5)
            writer.writerow([
                f"2025-01-01T12:00:{i:02d}", i, "observe", "testing", "ok",
                hp, gold, score,
            ])

    session_path.write_text(json.dumps({
        "cost": {"total_cost_usd": 0.05},
        "strategy": {"mode": "balanced"},
    }))
    history_path.write_text(json.dumps([]))
    return SessionData.from_log_path(csv_path)


@pytest.fixture
def session(tmp_path):
    return _create_session(tmp_path)


@pytest.fixture
def flat_session(tmp_path):
    return _create_session(tmp_path, flat_param=True)


@pytest.fixture
def session_csv_path(tmp_path):
    """Return path to a session CSV for CLI tests."""
    s = _create_session(tmp_path)
    return s.csv_path


# ---------------------------------------------------------------------------
# TestParameterPredictor
# ---------------------------------------------------------------------------

class TestParameterPredictor:
    def test_linear_regression(self, session):
        """Correct slope/intercept/r_squared for known linear data."""
        pred = ParameterPredictor(session)
        reg = pred.linear_regression("hp")
        # hp = 100 - 2*step  →  slope ≈ -2, intercept ≈ 100
        assert abs(reg["slope"] - (-2.0)) < 0.01
        assert abs(reg["intercept"] - 100.0) < 0.5
        assert reg["r_squared"] > 0.99

    def test_linear_regression_flat(self, tmp_path):
        """Zero slope for constant parameter."""
        s = _create_session(tmp_path, flat_param=True)
        pred = ParameterPredictor(s)
        reg = pred.linear_regression("score")
        assert abs(reg["slope"]) < 0.01

    def test_moving_average(self, session):
        """Rolling mean has correct length."""
        pred = ParameterPredictor(session)
        ma = pred.moving_average("hp")
        assert len(ma) == len(session.df)
        # First value should equal first actual (min_periods=1)
        assert abs(ma.iloc[0] - session.df["hp"].iloc[0]) < 0.01

    def test_moving_average_window(self, session):
        """Custom window size is respected."""
        pred_small = ParameterPredictor(session, window=3)
        pred_large = ParameterPredictor(session, window=20)
        ma_small = pred_small.moving_average("hp")
        ma_large = pred_large.moving_average("hp")
        # Both should have same length
        assert len(ma_small) == len(ma_large)
        # With smaller window, the MA tracks actual values more closely
        # At step 15, the means should differ
        assert ma_small.iloc[15] != ma_large.iloc[15]

    def test_predict_value(self, session):
        """Future step prediction matches linear regression."""
        pred = ParameterPredictor(session)
        # hp = 100 - 2*step  →  at step 50: 100 - 100 = 0
        val = pred.predict_value("hp", 50)
        assert abs(val - 0.0) < 1.0

    def test_predict_threshold_below(self, session):
        """HP=0 arrival step for falling parameter."""
        pred = ParameterPredictor(session)
        # hp = 100 - 2*step → crosses 0 at step 50
        step = pred.predict_threshold("hp", 0.0, "below")
        assert step is not None
        assert step == 50

    def test_predict_threshold_above(self, session):
        """Gold > 10000 arrival step for rising parameter."""
        pred = ParameterPredictor(session)
        # gold = 500 + 50*step → crosses 10000 at step ≈ 190 (ceil rounding)
        step = pred.predict_threshold("gold", 10000.0, "above")
        assert step is not None
        assert 189 <= step <= 191

    def test_predict_threshold_wrong_dir(self, session):
        """Returns None when trend opposes the direction."""
        pred = ParameterPredictor(session)
        # hp is falling, asking for above threshold
        step = pred.predict_threshold("hp", 200.0, "above")
        assert step is None

    def test_predict_threshold_already_past(self, session):
        """Returns None when crossing is in the past."""
        pred = ParameterPredictor(session)
        # hp = 100 - 2*step, threshold=90 below: crosses at step 5 which is < max step (29)
        step = pred.predict_threshold("hp", 90.0, "below")
        assert step is None

    def test_predict_all_thresholds(self, session):
        """Batch prediction with auto defaults returns results for all params."""
        pred = ParameterPredictor(session)
        results = pred.predict_all_thresholds()
        assert len(results) > 0
        params = {r["parameter"] for r in results}
        assert "hp" in params
        assert "gold" in params
        for r in results:
            assert "threshold" in r
            assert "direction" in r
            assert "estimated_step" in r
            assert "current_value" in r
            assert "slope" in r

    def test_forecast_series(self, session):
        """DataFrame shape and columns are correct."""
        pred = ParameterPredictor(session)
        forecast = pred.forecast_series("hp", extra_steps=10)
        assert list(forecast.columns) == ["step", "actual", "predicted", "moving_avg"]
        assert len(forecast) == len(session.df) + 10

    def test_forecast_series_future_nan(self, session):
        """Actual values are NaN for future steps."""
        pred = ParameterPredictor(session)
        forecast = pred.forecast_series("hp", extra_steps=10)
        # Last 10 rows should have NaN actual
        for val in forecast["actual"].iloc[-10:]:
            assert math.isnan(val)
        # First rows should have real values
        assert not math.isnan(forecast["actual"].iloc[0])

    def test_to_dict(self, session):
        """JSON-serialisable output with expected keys."""
        pred = ParameterPredictor(session)
        d = pred.to_dict()
        assert "session" in d
        assert "parameters" in d
        assert "thresholds" in d
        assert "hp" in d["parameters"]
        assert "regression" in d["parameters"]["hp"]
        assert "forecast" in d["parameters"]["hp"]
        # Should be JSON-serialisable
        json.dumps(d)

    def test_to_markdown(self, session):
        """Markdown report contains key information."""
        pred = ParameterPredictor(session)
        md = pred.to_markdown()
        assert "# Parameter Trend Prediction" in md
        assert "Regression Summary" in md
        assert "Threshold Predictions" in md
        assert "hp" in md
        assert "gold" in md
        assert "slope" in md.lower() or "Slope" in md


# ---------------------------------------------------------------------------
# TestPlotPrediction
# ---------------------------------------------------------------------------

class TestPlotPrediction:
    def test_plot_creates_file(self, session, tmp_path):
        """plot_prediction generates a PNG file."""
        pred = ParameterPredictor(session)
        out = tmp_path / "pred.png"
        result = plot_prediction(pred, "hp", output_path=out)
        assert result.exists()
        assert result.stat().st_size > 0
        # PNG magic bytes
        assert result.read_bytes()[:4] == b"\x89PNG"

    def test_plot_with_thresholds(self, session, tmp_path):
        """plot_prediction with threshold markers generates valid PNG."""
        pred = ParameterPredictor(session)
        out = tmp_path / "pred_thresh.png"
        result = plot_prediction(pred, "hp", output_path=out, thresholds=[0.0, 50.0])
        assert result.exists()
        assert result.stat().st_size > 0


# ---------------------------------------------------------------------------
# TestParameterPredictorCLI
# ---------------------------------------------------------------------------

class TestParameterPredictorCLI:
    def test_cli_predict(self, session_csv_path, capsys):
        """predict subcommand runs and produces markdown output."""
        cli_main(["predict", str(session_csv_path)])
        captured = capsys.readouterr()
        assert "Parameter Trend Prediction" in captured.out
        assert "hp" in captured.out

    def test_cli_predict_json(self, session_csv_path, capsys):
        """--format json output is valid JSON."""
        cli_main(["predict", str(session_csv_path), "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "parameters" in data
        assert "thresholds" in data

    def test_cli_forecast(self, session_csv_path, capsys):
        """forecast subcommand runs and shows forecast data."""
        cli_main(["forecast", str(session_csv_path), "--param", "hp"])
        captured = capsys.readouterr()
        assert "step" in captured.out
        assert "actual" in captured.out
        assert "predicted" in captured.out

    def test_cli_no_command(self):
        """No subcommand raises SystemExit."""
        with pytest.raises(SystemExit):
            cli_main([])
