#!/usr/bin/env python3
"""Session benchmark criteria management for PS1 AI Player.

Defines per-game benchmark criteria (target score, step count, parameter
thresholds) and evaluates sessions against them.  Results are pass / fail /
partial.  Benchmarks are persisted in ``session_benchmarks.json``.

Usage:
    python session_benchmark.py create <game_id> [--min-steps N] [--min-score F] [--param "hp >= 50"] [--log-dir logs/]
    python session_benchmark.py delete <game_id> [--log-dir logs/]
    python session_benchmark.py list [--log-dir logs/]
    python session_benchmark.py show <game_id> [--log-dir logs/]
    python session_benchmark.py evaluate <csv_path> [--log-dir logs/] [--format markdown|json]
    python session_benchmark.py evaluate-all [--log-dir logs/] [--game GAME_ID] [--format markdown|json]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from log_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# ParamThreshold — single parameter criterion
# ---------------------------------------------------------------------------

@dataclass
class ParamThreshold:
    """A single parameter benchmark criterion.

    Examples: ``hp >= 50``, ``gold > 1000``, ``score >= 100``
    Supported operators: >=, >, <=, <, ==, !=
    The *aggregator* determines which value to test: last (default), first,
    mean, min, max.
    """

    parameter: str
    operator: str
    value: float
    aggregator: str = "last"

    _OPS = {
        ">=": lambda a, b: a >= b,
        ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: abs(a - b) < 1e-9,
        "!=": lambda a, b: abs(a - b) >= 1e-9,
    }

    def evaluate(self, session) -> bool:
        """Return True if the session meets this criterion."""
        import pandas as pd

        if self.parameter not in session.df.columns:
            return False
        if not pd.api.types.is_numeric_dtype(session.df[self.parameter]):
            return False

        col = session.df[self.parameter]
        if len(col) == 0:
            return False

        agg_map = {
            "last": lambda c: float(c.iloc[-1]),
            "first": lambda c: float(c.iloc[0]),
            "mean": lambda c: float(c.mean()),
            "min": lambda c: float(c.min()),
            "max": lambda c: float(c.max()),
        }
        agg_fn = agg_map.get(self.aggregator, agg_map["last"])
        actual = agg_fn(col)

        op_fn = self._OPS.get(self.operator)
        if op_fn is None:
            return False
        return op_fn(actual, self.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "operator": self.operator,
            "value": self.value,
            "aggregator": self.aggregator,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParamThreshold:
        return cls(
            parameter=data["parameter"],
            operator=data["operator"],
            value=float(data["value"]),
            aggregator=data.get("aggregator", "last"),
        )

    @classmethod
    def parse(cls, text: str) -> ParamThreshold:
        """Parse a string like ``'hp >= 50'`` or ``'gold mean > 1000'``.

        Format: ``<param> [aggregator] <operator> <value>``
        """
        parts = text.strip().split()
        if len(parts) < 3:
            raise ValueError(f"Cannot parse threshold: {text!r}")

        param = parts[0]
        aggregators = {"last", "first", "mean", "min", "max"}

        if parts[1] in aggregators:
            if len(parts) < 4:
                raise ValueError(f"Cannot parse threshold: {text!r}")
            aggregator = parts[1]
            operator = parts[2]
            value = float(parts[3])
        else:
            aggregator = "last"
            operator = parts[1]
            value = float(parts[2])

        if operator not in cls._OPS:
            raise ValueError(f"Unknown operator: {operator}")

        return cls(parameter=param, operator=operator, value=value,
                   aggregator=aggregator)

    def __str__(self) -> str:
        agg = f" {self.aggregator}" if self.aggregator != "last" else ""
        return f"{self.parameter}{agg} {self.operator} {self.value}"


# ---------------------------------------------------------------------------
# BenchmarkCriteria — full criteria set for a game
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkCriteria:
    """Benchmark criteria for a specific game ID."""

    game_id: str
    min_steps: int | None = None
    min_score: float | None = None
    param_thresholds: list[ParamThreshold] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "min_steps": self.min_steps,
            "min_score": self.min_score,
            "param_thresholds": [t.to_dict() for t in self.param_thresholds],
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkCriteria:
        return cls(
            game_id=data["game_id"],
            min_steps=data.get("min_steps"),
            min_score=data.get("min_score"),
            param_thresholds=[
                ParamThreshold.from_dict(t)
                for t in data.get("param_thresholds", [])
            ],
            description=data.get("description", ""),
        )

    @property
    def criteria_count(self) -> int:
        """Total number of individual criteria."""
        count = len(self.param_thresholds)
        if self.min_steps is not None:
            count += 1
        if self.min_score is not None:
            count += 1
        return count


# ---------------------------------------------------------------------------
# BenchmarkResult — evaluation result
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkResult:
    """Result of evaluating a session against benchmark criteria."""

    game_id: str
    csv_filename: str
    status: str  # "pass", "fail", "partial"
    total_criteria: int
    passed_criteria: int
    details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_criteria == 0:
            return 1.0
        return self.passed_criteria / self.total_criteria

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "csv_filename": self.csv_filename,
            "status": self.status,
            "total_criteria": self.total_criteria,
            "passed_criteria": self.passed_criteria,
            "pass_rate": round(self.pass_rate, 4),
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# SessionBenchmarkManager — CRUD + evaluation
# ---------------------------------------------------------------------------

class SessionBenchmarkManager:
    """Manage session benchmarks persisted in JSON."""

    def __init__(self, log_dir: str | Path = "logs") -> None:
        self.log_dir = Path(log_dir)

    @property
    def _benchmarks_path(self) -> Path:
        return self.log_dir / "session_benchmarks.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        """Load benchmarks JSON.  Returns empty dict if file is missing."""
        if not self._benchmarks_path.exists():
            return {}
        try:
            data = json.loads(self._benchmarks_path.read_text())
            if not isinstance(data, dict):
                return {}
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        """Write benchmarks JSON."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._benchmarks_path.write_text(json.dumps(data, indent=2) + "\n")

    # -- CRUD ---------------------------------------------------------------

    def create_benchmark(
        self,
        game_id: str,
        min_steps: int | None = None,
        min_score: float | None = None,
        param_thresholds: list[ParamThreshold] | None = None,
        description: str = "",
    ) -> BenchmarkCriteria:
        """Create or replace a benchmark for a game ID."""
        game_id = game_id.strip()
        if not game_id:
            raise ValueError("Game ID must not be empty")
        criteria = BenchmarkCriteria(
            game_id=game_id,
            min_steps=min_steps,
            min_score=min_score,
            param_thresholds=list(param_thresholds or []),
            description=description.strip(),
        )
        data = self._load()
        data[game_id] = criteria.to_dict()
        self._save(data)
        logger.debug("Created benchmark for: %s", game_id)
        return criteria

    def delete_benchmark(self, game_id: str) -> None:
        """Delete a benchmark.  Raises KeyError if not found."""
        data = self._load()
        if game_id not in data:
            raise KeyError(f"Benchmark not found: {game_id}")
        del data[game_id]
        self._save(data)
        logger.debug("Deleted benchmark for: %s", game_id)

    def get_benchmark(self, game_id: str) -> BenchmarkCriteria:
        """Return benchmark for a game.  Raises KeyError if not found."""
        data = self._load()
        if game_id not in data:
            raise KeyError(f"Benchmark not found: {game_id}")
        return BenchmarkCriteria.from_dict(data[game_id])

    def list_benchmarks(self) -> list[BenchmarkCriteria]:
        """Return all benchmarks sorted by game_id."""
        data = self._load()
        benchmarks = [BenchmarkCriteria.from_dict(v) for v in data.values()]
        benchmarks.sort(key=lambda b: b.game_id)
        return benchmarks

    # -- Evaluation ---------------------------------------------------------

    def evaluate(self, session) -> BenchmarkResult:
        """Evaluate a session against its game's benchmark.

        Returns a BenchmarkResult with status:
          - "pass"    — all criteria met
          - "partial" — some criteria met (at least 1 pass, at least 1 fail)
          - "fail"    — no criteria met (or all fail)

        If no benchmark exists for the game, returns "pass" with 0 criteria.
        """
        from session_scorer import SessionScorer

        game_id = session.game_id
        data = self._load()

        if game_id not in data:
            return BenchmarkResult(
                game_id=game_id,
                csv_filename=session.csv_path.name,
                status="pass",
                total_criteria=0,
                passed_criteria=0,
                details=[],
            )

        criteria = BenchmarkCriteria.from_dict(data[game_id])
        details: list[dict[str, Any]] = []
        passed = 0
        total = 0

        # Check min_steps
        if criteria.min_steps is not None:
            total += 1
            met = session.total_steps >= criteria.min_steps
            if met:
                passed += 1
            details.append({
                "criterion": f"min_steps >= {criteria.min_steps}",
                "actual": session.total_steps,
                "passed": met,
            })

        # Check min_score
        if criteria.min_score is not None:
            total += 1
            scorer = SessionScorer()
            score = scorer.score(session).total
            met = score >= criteria.min_score
            if met:
                passed += 1
            details.append({
                "criterion": f"min_score >= {criteria.min_score}",
                "actual": round(score, 2),
                "passed": met,
            })

        # Check param thresholds
        for threshold in criteria.param_thresholds:
            total += 1
            met = threshold.evaluate(session)
            if met:
                passed += 1

            # Get actual value for reporting
            actual_val = None
            if threshold.parameter in session.df.columns:
                import pandas as pd
                if pd.api.types.is_numeric_dtype(session.df[threshold.parameter]):
                    col = session.df[threshold.parameter]
                    agg_map = {
                        "last": lambda c: float(c.iloc[-1]),
                        "first": lambda c: float(c.iloc[0]),
                        "mean": lambda c: float(c.mean()),
                        "min": lambda c: float(c.min()),
                        "max": lambda c: float(c.max()),
                    }
                    actual_val = agg_map.get(threshold.aggregator, agg_map["last"])(col)

            details.append({
                "criterion": str(threshold),
                "actual": round(actual_val, 2) if actual_val is not None else None,
                "passed": met,
            })

        # Determine status
        if total == 0:
            status = "pass"
        elif passed == total:
            status = "pass"
        elif passed == 0:
            status = "fail"
        else:
            status = "partial"

        return BenchmarkResult(
            game_id=game_id,
            csv_filename=session.csv_path.name,
            status=status,
            total_criteria=total,
            passed_criteria=passed,
            details=details,
        )

    def evaluate_all(
        self, game_id: str | None = None,
    ) -> list[BenchmarkResult]:
        """Evaluate all sessions in log_dir against their benchmarks.

        Optionally filter by game_id.
        """
        from session_replay import SessionData

        sessions = SessionData.discover_sessions(self.log_dir, game_id=game_id)
        results = []
        for s in sessions:
            results.append(self.evaluate(s))
        return results

    # -- Output helpers -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return all benchmarks as a JSON-serialisable dict."""
        benchmarks = self.list_benchmarks()
        return {
            "benchmarks": [b.to_dict() for b in benchmarks],
            "total_benchmarks": len(benchmarks),
        }

    def to_markdown(self, game_id: str | None = None) -> str:
        """Generate a markdown report.

        If *game_id* given, show that benchmark's details.  Otherwise list all.
        """
        if game_id:
            return self._benchmark_detail_markdown(game_id)
        return self._list_markdown()

    def _list_markdown(self) -> str:
        lines: list[str] = ["# Session Benchmarks", ""]
        benchmarks = self.list_benchmarks()
        if not benchmarks:
            lines.append("No benchmarks defined.")
            return "\n".join(lines)

        lines.append("| Game ID | Min Steps | Min Score | Param Criteria | Description |")
        lines.append("|---------|-----------|-----------|----------------|-------------|")
        for b in benchmarks:
            steps = str(b.min_steps) if b.min_steps is not None else "-"
            score = str(b.min_score) if b.min_score is not None else "-"
            params = len(b.param_thresholds)
            lines.append(f"| {b.game_id} | {steps} | {score} | {params} | {b.description} |")
        lines.append("")
        return "\n".join(lines)

    def _benchmark_detail_markdown(self, game_id: str) -> str:
        criteria = self.get_benchmark(game_id)
        lines: list[str] = [
            f"# Benchmark: {criteria.game_id}",
            "",
            f"**Description:** {criteria.description or '(none)'}",
            "",
        ]

        if criteria.min_steps is not None:
            lines.append(f"- **Min Steps:** {criteria.min_steps}")
        if criteria.min_score is not None:
            lines.append(f"- **Min Score:** {criteria.min_score}")

        if criteria.param_thresholds:
            lines.append("")
            lines.append("## Parameter Thresholds")
            lines.append("")
            lines.append("| Parameter | Aggregator | Operator | Value |")
            lines.append("|-----------|------------|----------|-------|")
            for t in criteria.param_thresholds:
                lines.append(f"| {t.parameter} | {t.aggregator} | {t.operator} | {t.value} |")

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def results_to_markdown(results: list[BenchmarkResult]) -> str:
        """Format a list of evaluation results as markdown."""
        lines: list[str] = ["# Benchmark Results", ""]
        if not results:
            lines.append("No results.")
            return "\n".join(lines)

        lines.append("| Session | Game | Status | Passed | Total | Rate |")
        lines.append("|---------|------|--------|--------|-------|------|")
        for r in results:
            rate_pct = f"{r.pass_rate * 100:.0f}%"
            status_icon = {"pass": "PASS", "partial": "PARTIAL", "fail": "FAIL"}[r.status]
            lines.append(
                f"| {r.csv_filename} | {r.game_id} | {status_icon} "
                f"| {r.passed_criteria} | {r.total_criteria} | {rate_pct} |"
            )
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Session Benchmark Management")
    parser.add_argument("--log-dir", default="logs", help="Log directory (default: logs/)")
    sub = parser.add_subparsers(dest="command")

    # create
    sp_create = sub.add_parser("create", help="Create/update a benchmark")
    sp_create.add_argument("game_id", help="Game ID")
    sp_create.add_argument("--min-steps", type=int, default=None)
    sp_create.add_argument("--min-score", type=float, default=None)
    sp_create.add_argument("--param", action="append", default=[],
                           help="Parameter threshold (e.g. 'hp >= 50')")
    sp_create.add_argument("--description", default="")

    # delete
    sp_delete = sub.add_parser("delete", help="Delete a benchmark")
    sp_delete.add_argument("game_id", help="Game ID")

    # list
    sub.add_parser("list", help="List all benchmarks")

    # show
    sp_show = sub.add_parser("show", help="Show benchmark details")
    sp_show.add_argument("game_id", help="Game ID")

    # evaluate
    sp_eval = sub.add_parser("evaluate", help="Evaluate a session against its benchmark")
    sp_eval.add_argument("csv_path", help="Path to session CSV")
    sp_eval.add_argument("--format", choices=["markdown", "json"], default="markdown")

    # evaluate-all
    sp_eval_all = sub.add_parser("evaluate-all", help="Evaluate all sessions")
    sp_eval_all.add_argument("--game", default=None, help="Filter by game ID")
    sp_eval_all.add_argument("--format", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    mgr = SessionBenchmarkManager(log_dir=args.log_dir)

    if args.command == "create":
        thresholds = [ParamThreshold.parse(p) for p in args.param]
        criteria = mgr.create_benchmark(
            args.game_id,
            min_steps=args.min_steps,
            min_score=args.min_score,
            param_thresholds=thresholds,
            description=args.description,
        )
        print(f"Created benchmark for {criteria.game_id} ({criteria.criteria_count} criteria)")

    elif args.command == "delete":
        try:
            mgr.delete_benchmark(args.game_id)
            print(f"Deleted benchmark: {args.game_id}")
        except KeyError as e:
            print(str(e))
            raise SystemExit(1)

    elif args.command == "list":
        print(mgr.to_markdown())

    elif args.command == "show":
        try:
            print(mgr.to_markdown(args.game_id))
        except KeyError as e:
            print(str(e))
            raise SystemExit(1)

    elif args.command == "evaluate":
        from session_replay import SessionData
        session = SessionData.from_log_path(args.csv_path)
        result = mgr.evaluate(session)
        if args.format == "json":
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(mgr.results_to_markdown([result]))

    elif args.command == "evaluate-all":
        results = mgr.evaluate_all(game_id=args.game)
        if args.format == "json":
            print(json.dumps([r.to_dict() for r in results], indent=2))
        else:
            print(mgr.results_to_markdown(results))


if __name__ == "__main__":
    main()
