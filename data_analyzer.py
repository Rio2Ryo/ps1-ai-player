#!/usr/bin/env python3
"""Causal chain extraction from gameplay CSV logs.

Computes correlations, lag correlations, builds causal graphs,
and uses GPT-4 for narrative inference of causal chains.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from log_config import get_logger

logger = get_logger(__name__)


class CausalChainExtractor:
    """Extract causal relationships from gameplay data logs."""

    def __init__(self) -> None:
        self.df: pd.DataFrame = pd.DataFrame()
        self.correlations: pd.DataFrame = pd.DataFrame()
        self.lag_correlations: dict[str, Any] = {}
        self.causal_chains: list[dict[str, Any]] = []

    def load_logs(self, log_files: list[Path]) -> pd.DataFrame:
        """Load and concatenate multiple CSV log files.

        Args:
            log_files: List of CSV file paths.

        Returns:
            Combined DataFrame.
        """
        frames: list[pd.DataFrame] = []
        for f in log_files:
            try:
                df = pd.read_csv(f)
                df["source_file"] = f.name
                frames.append(df)
                logger.info("Loaded: %s (%d rows)", f.name, len(df))
            except Exception as e:
                logger.warning("Could not load %s: %s", f, e)

        if not frames:
            logger.warning("No data loaded.")
            return pd.DataFrame()

        self.df = pd.concat(frames, ignore_index=True)

        # Drop non-numeric columns for analysis
        self._numeric_cols = [
            c
            for c in self.df.columns
            if c not in ("timestamp", "frame", "source_file", "action", "reasoning", "observations")
            and pd.api.types.is_numeric_dtype(self.df[c])
        ]

        logger.info("Total: %d rows, %d numeric parameters", len(self.df), len(self._numeric_cols))
        return self.df

    def compute_correlations(self) -> pd.DataFrame:
        """Compute Pearson correlation matrix between all numeric parameters.

        Returns:
            Correlation matrix as DataFrame.
        """
        if self.df.empty:
            return pd.DataFrame()

        self.correlations = self.df[self._numeric_cols].corr(method="pearson")
        logger.info("Correlation matrix computed.")
        return self.correlations

    def detect_lag_correlations(self, max_lag: int = 10) -> dict[str, Any]:
        """Compute time-lagged cross-correlations to detect delayed cause-effect.

        For each pair of parameters (A, B), computes correlation between
        A[t] and B[t+lag] for lag in [1, max_lag].

        Args:
            max_lag: Maximum number of time steps to test.

        Returns:
            Dict of significant lag correlations.
        """
        if self.df.empty:
            return {}

        results: dict[str, Any] = {}
        cols = self._numeric_cols

        for i, col_a in enumerate(cols):
            for col_b in cols[i + 1 :]:
                best_lag = 0
                best_corr = 0.0
                best_pval = 1.0

                for lag in range(1, max_lag + 1):
                    a = self.df[col_a].iloc[:-lag].values
                    b = self.df[col_b].iloc[lag:].values

                    if len(a) < 10:
                        continue

                    # Remove NaN
                    mask = ~(np.isnan(a) | np.isnan(b))
                    a, b = a[mask], b[mask]

                    if len(a) < 10:
                        continue

                    corr, pval = stats.pearsonr(a, b)

                    if abs(corr) > abs(best_corr):
                        best_corr = corr
                        best_lag = lag
                        best_pval = pval

                if abs(best_corr) > 0.3 and best_pval < 0.05:
                    key = f"{col_a} -> {col_b}"
                    results[key] = {
                        "source": col_a,
                        "target": col_b,
                        "lag": best_lag,
                        "correlation": round(best_corr, 4),
                        "p_value": round(best_pval, 6),
                    }
                    logger.info(
                        "  Lag correlation: %s -> %s (lag=%d, r=%.3f, p=%.4f)",
                        col_a, col_b, best_lag, best_corr, best_pval,
                    )

        self.lag_correlations = results
        logger.info("Found %d significant lag correlations.", len(results))
        return results

    def build_causal_graph(self) -> list[dict[str, Any]]:
        """Build causal chain hypotheses from correlation data.

        Combines simultaneous correlations and lag correlations to form
        directional causal chain hypotheses.

        Returns:
            List of causal chain dictionaries.
        """
        chains: list[dict[str, Any]] = []

        # Group lag correlations by source parameter
        source_effects: dict[str, list[dict[str, Any]]] = {}
        for _key, data in self.lag_correlations.items():
            src = data["source"]
            if src not in source_effects:
                source_effects[src] = []
            source_effects[src].append(data)

        # Build chains
        for source, effects in source_effects.items():
            # Sort effects by lag (earlier effects first)
            effects.sort(key=lambda x: x["lag"])

            # Estimate deltas from data
            chain_effects: list[dict[str, Any]] = []
            for effect in effects:
                target = effect["target"]
                lag = effect["lag"]
                corr = effect["correlation"]

                # Compute average delta per time step
                delta = 0.0
                if len(self.df) > lag:
                    target_diff = self.df[target].diff(lag)
                    delta = float(target_diff.mean())

                chain_effects.append(
                    {
                        "parameter": target,
                        "delta": f"{delta:+.2f}/step",
                        "lag_frames": lag,
                        "correlation": corr,
                    }
                )

            chain = {
                "trigger": f"{source} change",
                "effects": chain_effects,
                "confidence": round(
                    float(np.mean([abs(e["correlation"]) for e in chain_effects])),
                    4,
                ),
            }
            chains.append(chain)

        self.causal_chains = chains
        logger.info("Built %d causal chains.", len(chains))
        return chains

    def llm_inference(
        self,
        api_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Use GPT-4 to infer narrative causal chains from statistical data.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var).

        Returns:
            LLM-inferred causal chains.
        """
        import openai

        client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

        # Prepare summary
        summary_stats = self.df[self._numeric_cols].describe().to_string()
        corr_text = self.correlations.to_string() if not self.correlations.empty else "N/A"
        lag_text = json.dumps(self.lag_correlations, indent=2, ensure_ascii=False)

        sample_data = self.df[self._numeric_cols].head(20).to_string()

        prompt = (
            "You are analyzing gameplay data from a PS1 simulation/management game.\n\n"
            "## Statistical Summary\n"
            f"{summary_stats}\n\n"
            "## Correlation Matrix\n"
            f"{corr_text}\n\n"
            "## Lag Correlations (cause -> effect with time delay)\n"
            f"{lag_text}\n\n"
            "## Sample Data (first 20 rows)\n"
            f"{sample_data}\n\n"
            "Based on this data, infer the causal chains that explain how the game "
            "mechanics work. For each chain, describe:\n"
            "1. The trigger condition\n"
            "2. The cascade of effects with approximate magnitudes and delays\n"
            "3. Your confidence level\n\n"
            'Respond in JSON: {"chains": [{"trigger": "...", "effects": [...], '
            '"narrative": "...", "confidence": 0.0-1.0}]}'
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.2,
        )

        raw = response.choices[0].message.content or "{}"

        import re

        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1)

        try:
            result = json.loads(raw)
            llm_chains = result.get("chains", [])
        except json.JSONDecodeError:
            llm_chains = [{"trigger": "parse_error", "narrative": raw, "confidence": 0}]

        # Merge with statistical chains
        self.causal_chains.extend(llm_chains)
        logger.info("LLM added %d causal chain inferences.", len(llm_chains))
        return llm_chains

    def save_results(
        self, output_dir: Path | None = None
    ) -> Path:
        """Save causal chains to JSON file.

        Args:
            output_dir: Output directory (default: ~/ps1-ai-player/reports/).

        Returns:
            Path to the saved JSON file.
        """
        if output_dir is None:
            output_dir = Path.home() / "ps1-ai-player" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"causal_chains_{timestamp}.json"

        data = {
            "generated_at": datetime.now().isoformat(),
            "total_samples": len(self.df),
            "parameters": self._numeric_cols if hasattr(self, "_numeric_cols") else [],
            "chains": self.causal_chains,
            "lag_correlations": self.lag_correlations,
            "descriptive_statistics": (
                self.df[self._numeric_cols].describe().to_dict()
                if hasattr(self, "_numeric_cols") and self._numeric_cols
                else {}
            ),
            "correlation_matrix": (
                self.correlations.to_dict()
                if not self.correlations.empty
                else {}
            ),
        }

        output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Results saved to: %s", output_path)
        return output_path


def generate_sample_data(
    output_path: Path,
    num_rows: int = 500,
    seed: int = 42,
) -> Path:
    """Generate synthetic sample CSV data for testing without a real game.

    Simulates a theme park with correlated parameters:
    - ride_intensity drives nausea (lagged)
    - nausea drives vomit events and satisfaction drops (lagged)
    - hunger increases over time and drives food purchases

    Args:
        output_path: Path to write the CSV file.
        num_rows: Number of rows to generate.
        seed: Random seed for reproducibility.

    Returns:
        Path to the generated CSV file.
    """
    rng = np.random.default_rng(seed)

    timestamps = pd.date_range("2025-01-01", periods=num_rows, freq="5s")
    frames = np.arange(num_rows)

    # Base signals
    ride_intensity = 50.0 + 30.0 * np.sin(frames * 0.02) + rng.normal(0, 5, num_rows)
    ride_intensity = np.clip(ride_intensity, 0, 100)

    # Nausea follows ride_intensity with a lag of ~5 steps
    nausea = np.zeros(num_rows)
    for i in range(num_rows):
        lag_idx = max(0, i - 5)
        nausea[i] = ride_intensity[lag_idx] * 0.6 + rng.normal(0, 3)
    nausea = np.clip(nausea, 0, 100)

    # Satisfaction inversely correlated with nausea (lag ~10 steps)
    satisfaction = np.zeros(num_rows)
    satisfaction[0] = 70.0
    for i in range(1, num_rows):
        lag_idx = max(0, i - 10)
        nausea_effect = -0.15 * max(0, nausea[lag_idx] - 40)
        satisfaction[i] = satisfaction[i - 1] + nausea_effect + rng.normal(0.1, 1)
    satisfaction = np.clip(satisfaction, 0, 100)

    # Hunger increases linearly with noise, resets periodically (eating)
    hunger = np.zeros(num_rows)
    for i in range(1, num_rows):
        hunger[i] = hunger[i - 1] + 0.5 + rng.normal(0, 0.3)
        if hunger[i] > 80:
            hunger[i] = 10 + rng.normal(0, 3)  # ate food
    hunger = np.clip(hunger, 0, 100)

    # Money decreases with purchases, gets periodic income
    money = np.zeros(num_rows)
    money[0] = 5000
    for i in range(1, num_rows):
        income = rng.uniform(5, 15)
        expense = 0
        if hunger[i] < hunger[i - 1]:  # food purchase
            expense += rng.uniform(8, 15)
        money[i] = money[i - 1] + income - expense - rng.uniform(0, 3)

    # Visitors fluctuate
    visitors = 50 + 20 * np.sin(frames * 0.01) + rng.normal(0, 5, num_rows)
    visitors = np.clip(visitors, 10, 100).astype(int)

    df = pd.DataFrame({
        "timestamp": timestamps.astype(str),
        "frame": frames,
        "money": np.round(money, 0).astype(int),
        "visitors": visitors,
        "satisfaction": np.round(satisfaction, 1),
        "nausea": np.round(nausea, 1),
        "hunger": np.round(hunger, 1),
        "ride_intensity": np.round(ride_intensity, 1),
    })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("Generated %d rows of sample data -> %s", num_rows, output_path)
    return output_path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Gameplay Data Causal Chain Analyzer")
    parser.add_argument(
        "--logs",
        nargs="*",
        type=Path,
        default=None,
        help="CSV log file paths",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: ~/ps1-ai-player/reports/)",
    )
    parser.add_argument(
        "--max-lag",
        type=int,
        default=10,
        help="Maximum lag steps for cross-correlation (default: 10)",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable LLM inference (requires OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--openai-key",
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--generate-sample",
        type=Path,
        default=None,
        metavar="PATH",
        help="Generate sample CSV data at the given path and exit",
    )

    args = parser.parse_args()

    # Sample data generation mode
    if args.generate_sample:
        generate_sample_data(args.generate_sample)
        return

    if not args.logs:
        parser.error("--logs is required (or use --generate-sample to create test data)")

    extractor = CausalChainExtractor()
    extractor.load_logs(args.logs)

    if extractor.df.empty:
        logger.warning("No data to analyze.")
        return

    extractor.compute_correlations()
    extractor.detect_lag_correlations(max_lag=args.max_lag)
    extractor.build_causal_graph()

    if args.llm:
        extractor.llm_inference(api_key=args.openai_key)

    extractor.save_results(output_dir=args.output)


if __name__ == "__main__":
    main()
