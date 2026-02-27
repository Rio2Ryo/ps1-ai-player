#!/usr/bin/env python3
"""Auto-generate Game Design Documents from extracted causal chains.

Reads causal chain JSON files produced by data_analyzer.py and uses
GPT-4 to generate comprehensive GDD in Markdown format. Supports both
LLM-enhanced and local-only (statistical) generation modes.

Now also supports direct CSV input via ``from_csv()`` and structured
JSON export alongside the traditional Markdown output.
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

from log_config import get_logger

logger = get_logger(__name__)


class GDDGenerator:
    """Generate Game Design Documents from causal chain analysis data."""

    def __init__(self) -> None:
        self.chains: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}
        self.descriptive_statistics: dict[str, Any] = {}
        self.correlation_matrix: dict[str, Any] = {}
        self.raw_df: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------

    def load_causal_chains(self, json_path: Path) -> None:
        """Load causal chains from JSON file.

        Args:
            json_path: Path to causal_chains_*.json file.
        """
        data = json.loads(json_path.read_text())
        self.chains = data.get("chains", [])
        self.metadata = {
            "generated_at": data.get("generated_at", ""),
            "total_samples": data.get("total_samples", 0),
            "parameters": data.get("parameters", []),
            "lag_correlations": data.get("lag_correlations", {}),
        }
        self.descriptive_statistics = data.get("descriptive_statistics", {})
        self.correlation_matrix = data.get("correlation_matrix", {})
        logger.info("Loaded %d causal chains from %s", len(self.chains), json_path.name)

    @classmethod
    def from_csv(cls, csv_files: list[Path], max_lag: int = 10) -> GDDGenerator:
        """Create GDDGenerator directly from CSV log files.

        Internally runs CausalChainExtractor, stores raw stats and the
        DataFrame for event analysis.

        Args:
            csv_files: List of CSV file paths.
            max_lag: Maximum lag steps for cross-correlation.

        Returns:
            Fully-populated GDDGenerator instance.
        """
        from data_analyzer import CausalChainExtractor

        extractor = CausalChainExtractor()
        extractor.load_logs(csv_files)

        if extractor.df.empty:
            logger.warning("No data loaded from CSV files.")
            gen = cls()
            return gen

        extractor.compute_correlations()
        extractor.detect_lag_correlations(max_lag=max_lag)
        extractor.build_causal_graph()

        gen = cls()
        gen.chains = extractor.causal_chains
        gen.metadata = {
            "generated_at": datetime.now().isoformat(),
            "total_samples": len(extractor.df),
            "parameters": extractor._numeric_cols,
            "lag_correlations": extractor.lag_correlations,
        }
        gen.descriptive_statistics = (
            extractor.df[extractor._numeric_cols].describe().to_dict()
            if extractor._numeric_cols
            else {}
        )
        gen.correlation_matrix = (
            extractor.correlations.to_dict()
            if not extractor.correlations.empty
            else {}
        )
        gen.raw_df = extractor.df
        logger.info("GDDGenerator created from %d CSV files.", len(csv_files))
        return gen

    # ------------------------------------------------------------------
    # Existing GDD sections (unchanged)
    # ------------------------------------------------------------------

    def generate_mechanics_section(self) -> str:
        """Generate the game mechanics section from causal chains.

        Returns:
            Markdown text for the mechanics section.
        """
        lines = ["## Core Mechanics\n"]

        if not self.chains:
            lines.append("No causal chains available for mechanics extraction.\n")
            return "\n".join(lines)

        lines.append(
            "The following mechanics were extracted from gameplay data analysis:\n"
        )

        for i, chain in enumerate(self.chains, 1):
            trigger = chain.get("trigger", "Unknown")
            confidence = chain.get("confidence", 0)
            effects = chain.get("effects", [])
            narrative = chain.get("narrative", "")

            lines.append(f"### Mechanic {i}: {trigger}")
            lines.append(f"**Confidence:** {confidence:.0%}\n")

            if narrative:
                lines.append(f"{narrative}\n")

            if effects:
                lines.append("**Effects:**\n")
                for effect in effects:
                    param = effect.get("parameter", "unknown")
                    delta = effect.get("delta", "?")
                    lag = effect.get("lag_frames", 0)
                    lines.append(f"- **{param}**: {delta} (delay: {lag} frames)")
                lines.append("")

        return "\n".join(lines)

    def generate_balance_section(self) -> str:
        """Generate the balance design section.

        Returns:
            Markdown text for the balance section.
        """
        lines = ["## Balance Design\n"]

        params = self.metadata.get("parameters", [])
        lag_corrs = self.metadata.get("lag_correlations", {})

        if params:
            lines.append("### Parameter Interactions\n")
            lines.append("| Source | Target | Lag | Correlation |")
            lines.append("|--------|--------|-----|-------------|")
            for _key, data in lag_corrs.items():
                src = data.get("source", "?")
                tgt = data.get("target", "?")
                lag = data.get("lag", 0)
                corr = data.get("correlation", 0)
                lines.append(f"| {src} | {tgt} | {lag} | {corr:.3f} |")
            lines.append("")

        lines.append("### Tuning Guidelines\n")
        lines.append(
            "Parameters should be balanced to create meaningful trade-offs. "
            "Key relationships identified:\n"
        )

        for chain in self.chains:
            trigger = chain.get("trigger", "")
            confidence = chain.get("confidence", 0)
            if confidence > 0.5:
                lines.append(f"- **{trigger}** (confidence: {confidence:.0%})")

        lines.append("")
        return "\n".join(lines)

    def generate_feedback_loops_section(self) -> str:
        """Generate a section documenting positive/negative feedback loops.

        Analyzes causal chains for circular dependencies and reinforcing patterns.

        Returns:
            Markdown text for the feedback loops section.
        """
        lines = ["## Feedback Loops\n"]
        lag_corrs = self.metadata.get("lag_correlations", {})

        if not lag_corrs:
            lines.append("No feedback loops detected (insufficient lag correlation data).\n")
            return "\n".join(lines)

        # Build adjacency from lag correlations to find loops
        edges: dict[str, list[tuple[str, float]]] = {}
        for _key, data in lag_corrs.items():
            src = data.get("source", "")
            tgt = data.get("target", "")
            corr = data.get("correlation", 0)
            if src and tgt:
                edges.setdefault(src, []).append((tgt, corr))

        # Detect 2-node cycles (A→B and B→A)
        positive_loops: list[str] = []
        negative_loops: list[str] = []
        seen_pairs: set[tuple[str, str]] = set()

        for src, targets in edges.items():
            for tgt, corr_ab in targets:
                if (tgt, src) in seen_pairs:
                    continue
                if tgt in edges:
                    for back_tgt, corr_ba in edges[tgt]:
                        if back_tgt == src:
                            seen_pairs.add((src, tgt))
                            loop_type = "positive" if corr_ab * corr_ba > 0 else "negative"
                            desc = (
                                f"- **{src} ↔ {tgt}**: "
                                f"{src}→{tgt} (r={corr_ab:.3f}), "
                                f"{tgt}→{src} (r={corr_ba:.3f}) "
                                f"— {loop_type} feedback"
                            )
                            if loop_type == "positive":
                                positive_loops.append(desc)
                            else:
                                negative_loops.append(desc)

        if positive_loops:
            lines.append("### Positive (Reinforcing) Loops\n")
            lines.append("These loops amplify changes — can lead to runaway growth or collapse:\n")
            lines.extend(positive_loops)
            lines.append("")

        if negative_loops:
            lines.append("### Negative (Balancing) Loops\n")
            lines.append("These loops counteract changes — create stability and equilibrium:\n")
            lines.extend(negative_loops)
            lines.append("")

        if not positive_loops and not negative_loops:
            lines.append("No circular feedback loops detected between parameters.\n")
            lines.append("All causal relationships appear to be unidirectional.\n")

        return "\n".join(lines)

    def generate_state_analysis_section(self) -> str:
        """Generate a section about game state transitions and phases.

        Returns:
            Markdown text for the state analysis section.
        """
        lines = ["## Game State Analysis\n"]

        lines.append("### Expected Game States\n")
        lines.append("The AI agent should recognize and handle these game states:\n")
        lines.append("| State | Description | Recommended Action |")
        lines.append("|-------|-------------|--------------------|")
        lines.append("| Menu | Title/option selection screens | Navigate with D-pad, confirm with Circle |")
        lines.append("| Gameplay | Active game simulation | Execute strategy-based actions |")
        lines.append("| Dialog | NPC/event text boxes | Advance with Circle, read content |")
        lines.append("| Loading | Screen transitions | Wait, no input needed |")
        lines.append("| Pause | Game paused | Resume with Start or navigate pause menu |")
        lines.append("")

        lines.append("### State Transition Patterns\n")
        lines.append("Common transitions observed in PS1 management/simulation games:\n")
        lines.append("- Menu → Loading → Gameplay (game start)")
        lines.append("- Gameplay → Dialog → Gameplay (event trigger)")
        lines.append("- Gameplay → Pause → Gameplay (player pause)")
        lines.append("- Gameplay → Menu (game over / exit)")
        lines.append("")

        return "\n".join(lines)

    def generate_strategy_section(self) -> str:
        """Generate a section documenting adaptive strategy thresholds.

        Returns:
            Markdown text for the strategy section.
        """
        lines = ["## Adaptive Strategy Configuration\n"]

        lines.append("### Strategy Modes\n")
        lines.append("| Strategy | Trigger Condition | Focus |")
        lines.append("|----------|-------------------|-------|")
        lines.append("| expansion | money > 8000, visitors < 15 | Build new attractions, grow park |")
        lines.append("| satisfaction | satisfaction < 30, nausea > 70 | Improve visitor comfort |")
        lines.append("| cost_reduction | money < 1000 | Reduce expenses, optimize revenue |")
        lines.append("| exploration | No specific trigger | Discover new areas and actions |")
        lines.append("| balanced | Default / no threshold active | Adaptive switching |")
        lines.append("")

        lines.append("### Threshold Customization\n")
        lines.append("Strategy thresholds can be customized per game via JSON config:\n")
        lines.append("```json")
        lines.append(json.dumps({
            "thresholds": [
                {"parameter": "money", "operator": "lt", "value": 1000,
                 "target_strategy": "cost_reduction", "priority": 10},
                {"parameter": "satisfaction", "operator": "lt", "value": 30,
                 "target_strategy": "satisfaction", "priority": 9},
            ]
        }, indent=2))
        lines.append("```\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # NEW sections
    # ------------------------------------------------------------------

    def generate_statistics_section(self) -> str:
        """Generate descriptive statistics section with auto-classification.

        Returns:
            Markdown text for the statistics section.
        """
        lines = ["## Descriptive Statistics\n"]

        if not self.descriptive_statistics:
            lines.append("No descriptive statistics available.\n")
            return "\n".join(lines)

        # Build table
        lines.append("| Parameter | Min | Max | Mean | Std | Range |")
        lines.append("|-----------|-----|-----|------|-----|-------|")

        for param, stat in self.descriptive_statistics.items():
            mn = stat.get("min", 0)
            mx = stat.get("max", 0)
            mean = stat.get("mean", 0)
            std = stat.get("std", 0)
            rng = mx - mn
            lines.append(
                f"| {param} | {mn:.1f} | {mx:.1f} | {mean:.1f} | {std:.1f} | {rng:.1f} |"
            )

        lines.append("")

        # Auto-classification based on behavior
        lines.append("### Parameter Behavior Classification\n")

        for param, stat in self.descriptive_statistics.items():
            mean = stat.get("mean", 0)
            std = stat.get("std", 0)
            mn = stat.get("min", 0)
            mx = stat.get("max", 0)

            classification = self._classify_parameter(param, mean, std, mn, mx)
            lines.append(f"- **{param}**: {classification}")

        lines.append("")
        return "\n".join(lines)

    def _classify_parameter(
        self,
        param: str,
        mean: float,
        std: float,
        mn: float,
        mx: float,
    ) -> str:
        """Classify a parameter's behavior from its statistics.

        Args:
            param: Parameter name.
            mean: Mean value.
            std: Standard deviation.
            mn: Minimum value.
            mx: Maximum value.

        Returns:
            Human-readable classification string.
        """
        # Check coefficient of variation for volatility
        cv = std / abs(mean) if mean != 0 else 0

        # Heuristic: check if the raw data shows a monotonic trend
        is_monotonic = False
        if self.raw_df is not None and param in self.raw_df.columns:
            series = self.raw_df[param].dropna()
            if len(series) >= 10:
                # Check first vs last quartile means
                q1_mean = series.iloc[: len(series) // 4].mean()
                q4_mean = series.iloc[-len(series) // 4 :].mean()
                total_range = mx - mn if mx != mn else 1
                drift = (q4_mean - q1_mean) / total_range
                if drift > 0.5:
                    is_monotonic = True
                    return "Accumulating resource (monotonically rising)"
                if drift < -0.5:
                    is_monotonic = True
                    return "Depleting resource (monotonically falling)"

        if cv > 0.5:
            return "Volatile parameter (high std/mean ratio)"

        # Check for oscillation: std relative to range
        rng = mx - mn
        if rng > 0 and std / rng > 0.2:
            return "Cyclical status effect (oscillating)"

        return "Equilibrium metric (stable)"

    def generate_correlation_matrix_section(self) -> str:
        """Generate full correlation matrix section with strength interpretation.

        Returns:
            Markdown text for the correlation matrix section.
        """
        lines = ["## Correlation Matrix\n"]

        if not self.correlation_matrix:
            lines.append("No correlation data available.\n")
            return "\n".join(lines)

        # Build pair table from the correlation matrix dict
        params = list(self.correlation_matrix.keys())
        lines.append("| Pair | r | Strength | Direction |")
        lines.append("|------|---|----------|-----------|")

        seen: set[tuple[str, str]] = set()
        for i, p1 in enumerate(params):
            for p2 in params[i + 1 :]:
                if (p1, p2) in seen or (p2, p1) in seen:
                    continue
                seen.add((p1, p2))
                r = self.correlation_matrix.get(p1, {}).get(p2, 0)
                if r is None:
                    continue
                strength = self._correlation_strength(abs(r))
                direction = "Positive" if r > 0 else "Negative" if r < 0 else "None"
                lines.append(f"| {p1} ↔ {p2} | {r:.3f} | {strength} | {direction} |")

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _correlation_strength(abs_r: float) -> str:
        """Return a human-readable strength label for a correlation coefficient.

        Args:
            abs_r: Absolute value of r.

        Returns:
            Strength label.
        """
        if abs_r >= 0.9:
            return "Very strong"
        if abs_r >= 0.7:
            return "Strong"
        if abs_r >= 0.5:
            return "Moderate"
        if abs_r >= 0.3:
            return "Weak"
        return "Negligible"

    def generate_data_quality_section(self) -> str:
        """Generate data quality report section.

        Covers total samples, time coverage, missing values, and outlier counts.

        Returns:
            Markdown text for the data quality section.
        """
        lines = ["## Data Quality Report\n"]

        total_samples = self.metadata.get("total_samples", 0)
        lines.append(f"- **Total samples:** {total_samples}")

        # Time coverage from raw_df
        if self.raw_df is not None and "timestamp" in self.raw_df.columns:
            try:
                ts = pd.to_datetime(self.raw_df["timestamp"])
                lines.append(f"- **Time range:** {ts.min()} → {ts.max()}")
                duration = ts.max() - ts.min()
                lines.append(f"- **Duration:** {duration}")
            except Exception:
                lines.append("- **Time range:** N/A")
        else:
            lines.append("- **Time range:** N/A (raw data not available)")

        lines.append("")

        # Missing values
        lines.append("### Missing Values\n")
        if self.raw_df is not None:
            params = self.metadata.get("parameters", [])
            has_missing = False
            for p in params:
                if p in self.raw_df.columns:
                    missing = int(self.raw_df[p].isna().sum())
                    if missing > 0:
                        has_missing = True
                        pct = missing / len(self.raw_df) * 100
                        lines.append(f"- **{p}**: {missing} missing ({pct:.1f}%)")
            if not has_missing:
                lines.append("No missing values detected.\n")
        else:
            lines.append("Raw data not available for missing value analysis.\n")

        lines.append("")

        # Outlier detection (IQR method)
        lines.append("### Outliers (IQR Method)\n")
        if self.raw_df is not None:
            params = self.metadata.get("parameters", [])
            has_outliers = False
            for p in params:
                if p in self.raw_df.columns:
                    series = self.raw_df[p].dropna()
                    if len(series) < 4:
                        continue
                    q1 = series.quantile(0.25)
                    q3 = series.quantile(0.75)
                    iqr = q3 - q1
                    lower = q1 - 1.5 * iqr
                    upper = q3 + 1.5 * iqr
                    outlier_count = int(((series < lower) | (series > upper)).sum())
                    if outlier_count > 0:
                        has_outliers = True
                        lines.append(f"- **{p}**: {outlier_count} outliers")
            if not has_outliers:
                lines.append("No outliers detected.\n")
        else:
            lines.append("Raw data not available for outlier analysis.\n")

        lines.append("")
        return "\n".join(lines)

    def generate_event_analysis_section(self) -> str:
        """Generate action/event frequency analysis section.

        Looks for an ``action`` column in raw data and reports frequency
        distribution.

        Returns:
            Markdown text for the event analysis section.
        """
        lines = ["## Event / Action Analysis\n"]

        if self.raw_df is None or "action" not in self.raw_df.columns:
            lines.append("No action/event data available in the dataset.\n")
            return "\n".join(lines)

        action_counts = self.raw_df["action"].value_counts()
        total_actions = int(action_counts.sum())
        lines.append(f"Total recorded actions: **{total_actions}**\n")

        lines.append("### Top Actions\n")
        lines.append("| Rank | Action | Count | Frequency |")
        lines.append("|------|--------|-------|-----------|")

        for rank, (action, count) in enumerate(action_counts.head(10).items(), 1):
            freq = count / total_actions * 100
            lines.append(f"| {rank} | {action} | {count} | {freq:.1f}% |")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Local GDD generation (moved from pipeline.py)
    # ------------------------------------------------------------------

    def generate_local_gdd(self, game_id: str = "UNKNOWN") -> str:
        """Generate a complete GDD using only local data (no API key required).

        Produces a complete GDD from statistical analysis without LLM
        assistance. This was previously ``_generate_local_gdd()`` in
        pipeline.py.

        Args:
            game_id: Game identifier for the title.

        Returns:
            Complete GDD as Markdown string.
        """
        header = (
            f"# Game Design Document: {game_id}\n\n"
            f"Generated: {datetime.now().isoformat()}\n"
            f"Data samples: {self.metadata.get('total_samples', 'N/A')}\n"
            f"Causal chains: {len(self.chains)}\n"
            f"Mode: Local analysis (no LLM)\n\n"
            "---\n\n"
        )

        # Overview
        overview = "## Overview\n\n"
        params = self.metadata.get("parameters", [])
        overview += (
            f"This GDD was auto-generated from gameplay data analysis of a PS1 game.\n"
            f"The analysis tracked {len(params)} parameters: "
            f"{', '.join(params)}.\n\n"
        )

        # Parameter definitions — auto-detect roles from data
        param_section = "## Parameter Definitions\n\n"
        param_section += "| Parameter | Role |\n"
        param_section += "|-----------|------|\n"
        for p in params:
            role = self._infer_parameter_role(p)
            param_section += f"| {p} | {role} |\n"
        param_section += "\n"

        # Sections
        mechanics = self.generate_mechanics_section()
        balance = self.generate_balance_section()
        feedback_loops = self.generate_feedback_loops_section()
        statistics = self.generate_statistics_section()
        correlations = self.generate_correlation_matrix_section()
        data_quality = self.generate_data_quality_section()
        event_analysis = self.generate_event_analysis_section()
        state_analysis = self.generate_state_analysis_section()
        strategy_config = self.generate_strategy_section()

        # Implementation priority
        priority = "## Implementation Priority\n\n"
        priority += "Based on causal chain confidence scores:\n\n"
        sorted_chains = sorted(
            self.chains,
            key=lambda c: c.get("confidence", 0),
            reverse=True,
        )
        for i, chain in enumerate(sorted_chains, 1):
            trigger = chain.get("trigger", "Unknown")
            conf = chain.get("confidence", 0)
            n_effects = len(chain.get("effects", []))
            priority += (
                f"{i}. **{trigger}** — confidence {conf:.0%}, "
                f"{n_effects} downstream effects\n"
            )
        priority += "\n"

        return (
            header + overview + param_section
            + statistics + "\n"
            + correlations + "\n"
            + data_quality + "\n"
            + event_analysis + "\n"
            + mechanics + "\n"
            + balance + "\n"
            + feedback_loops + "\n"
            + state_analysis + "\n"
            + strategy_config + "\n"
            + priority
        )

    def _infer_parameter_role(self, param: str) -> str:
        """Infer a parameter's role from its name and statistics.

        Uses naming heuristics first, then falls back to statistical
        classification.

        Args:
            param: Parameter name.

        Returns:
            Human-readable role description.
        """
        # Keyword-based heuristics
        name = param.lower()
        if any(k in name for k in ("money", "gold", "cash", "coin", "fund")):
            return "Primary resource / economy indicator"
        if any(k in name for k in ("visitor", "population", "customer", "player")):
            return "Population / demand metric"
        if any(k in name for k in ("satisf", "happy", "morale", "approval")):
            return "Quality of experience indicator"
        if any(k in name for k in ("nausea", "sick", "disease", "poison")):
            return "Negative status effect"
        if any(k in name for k in ("hunger", "thirst", "fatigue", "energy")):
            return "Time-dependent need"
        if any(k in name for k in ("intensity", "speed", "power", "strength")):
            return "Intensity / risk factor"
        if any(k in name for k in ("health", "hp", "life")):
            return "Health / survivability metric"
        if any(k in name for k in ("score", "point", "xp", "exp")):
            return "Progression metric"

        # Fallback: classify from statistics
        if param in self.descriptive_statistics:
            stat = self.descriptive_statistics[param]
            mean = stat.get("mean", 0)
            std = stat.get("std", 0)
            mn = stat.get("min", 0)
            mx = stat.get("max", 0)
            return self._classify_parameter(param, mean, std, mn, mx)

        return "Game parameter"

    # ------------------------------------------------------------------
    # LLM-based full GDD
    # ------------------------------------------------------------------

    @staticmethod
    def _build_llm_prompt(
        chains_json: str,
        metadata_json: str,
        lang: str = "ja",
    ) -> str:
        """Build the LLM prompt for GDD generation.

        Args:
            chains_json: JSON string of causal chains.
            metadata_json: JSON string of metadata.
            lang: Output language (``"ja"`` or ``"en"``).

        Returns:
            Prompt string.
        """
        if lang == "en":
            return (
                "Below is causal relationship data extracted from PS1 gameplay data.\n"
                "Based on this, generate a Game Design Document (GDD) for a game "
                "with similar mechanics.\n\n"
                "Sections:\n"
                "1. Overview\n"
                "2. Core Mechanics\n"
                "3. Parameter Definitions\n"
                "4. Causal Relationships\n"
                "5. Balance Design\n"
                "6. Feedback Loops\n"
                "7. Game State Transitions\n"
                "8. AI Strategy Configuration\n"
                "9. Implementation Priority\n\n"
                f"## Causal Chain Data\n```json\n{chains_json}\n```\n\n"
                f"## Metadata\n```json\n{metadata_json}\n```\n\n"
                "Generate a complete GDD in Markdown format. Write in English."
            )

        # Default: Japanese
        return (
            "以下はPS1ゲームのプレイデータから抽出した因果関係データです。\n"
            "これをもとに、同様のゲームメカニクスを持つゲームのGDD"
            "（ゲームデザインドキュメント）を生成してください。\n\n"
            "セクション:\n"
            "1. 概要 (Overview)\n"
            "2. コアメカニクス (Core Mechanics)\n"
            "3. パラメーター定義 (Parameter Definitions)\n"
            "4. 因果関係 (Causal Relationships)\n"
            "5. バランス設計 (Balance Design)\n"
            "6. フィードバックループ (Feedback Loops)\n"
            "7. ゲーム状態遷移 (Game State Transitions)\n"
            "8. AI戦略設定 (AI Strategy Configuration)\n"
            "9. 実装優先度 (Implementation Priority)\n\n"
            f"## 因果チェーンデータ\n```json\n{chains_json}\n```\n\n"
            f"## メタデータ\n```json\n{metadata_json}\n```\n\n"
            "Markdown形式で完全なGDDを生成してください。日本語で記述してください。"
        )

    def generate_full_gdd(
        self,
        game_id: str = "UNKNOWN",
        api_key: str | None = None,
        lang: str = "ja",
    ) -> str:
        """Generate a complete GDD using GPT-4 for narrative generation.

        Args:
            game_id: Game identifier for the title.
            api_key: OpenAI API key.
            lang: Output language — ``"ja"`` for Japanese (default),
                ``"en"`` for English.

        Returns:
            Complete GDD as Markdown string.
        """
        import openai

        client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

        chains_json = json.dumps(self.chains, indent=2, ensure_ascii=False)
        metadata_json = json.dumps(self.metadata, indent=2, ensure_ascii=False)

        prompt = self._build_llm_prompt(chains_json, metadata_json, lang)

        logger.info("Requesting LLM-generated GDD for %s...", game_id)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.3,
        )

        llm_gdd = response.choices[0].message.content or ""
        logger.info("LLM GDD received (%d chars).", len(llm_gdd))

        # Combine locally generated sections with LLM output
        header = (
            f"# Game Design Document: {game_id}\n\n"
            f"Generated: {datetime.now().isoformat()}\n"
            f"Data samples: {self.metadata.get('total_samples', 'N/A')}\n"
            f"Causal chains: {len(self.chains)}\n\n"
            "---\n\n"
        )

        local_sections = (
            self.generate_mechanics_section() + "\n"
            + self.generate_balance_section() + "\n"
            + self.generate_feedback_loops_section() + "\n"
            + self.generate_statistics_section() + "\n"
            + self.generate_correlation_matrix_section() + "\n"
            + self.generate_data_quality_section() + "\n"
            + self.generate_event_analysis_section() + "\n"
            + self.generate_state_analysis_section() + "\n"
            + self.generate_strategy_section() + "\n"
        )

        gdd = (
            header
            + "# Part 1: Data-Driven Analysis\n\n"
            + local_sections
            + "---\n\n"
            + "# Part 2: LLM-Generated GDD\n\n"
            + llm_gdd
        )

        return gdd

    # ------------------------------------------------------------------
    # Structured export
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the GDD as a structured dictionary.

        Returns:
            Dict with all GDD data suitable for JSON serialization.
        """
        return {
            "metadata": self.metadata,
            "descriptive_statistics": self.descriptive_statistics,
            "correlation_matrix": self.correlation_matrix,
            "causal_chains": self.chains,
            "sections": {
                "mechanics": self.generate_mechanics_section(),
                "balance": self.generate_balance_section(),
                "feedback_loops": self.generate_feedback_loops_section(),
                "statistics": self.generate_statistics_section(),
                "correlation_analysis": self.generate_correlation_matrix_section(),
                "data_quality": self.generate_data_quality_section(),
                "event_analysis": self.generate_event_analysis_section(),
                "state_analysis": self.generate_state_analysis_section(),
                "strategy": self.generate_strategy_section(),
            },
        }

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_gdd(
        self,
        gdd_content: str,
        game_id: str = "UNKNOWN",
        output_dir: Path | None = None,
        fmt: str = "markdown",
    ) -> Path:
        """Save GDD to file.

        Args:
            gdd_content: GDD markdown content.
            game_id: Game identifier.
            output_dir: Output directory.
            fmt: Output format — ``"markdown"``, ``"json"``, or ``"both"``.

        Returns:
            Path to the primary saved file (markdown path when format
            is ``"both"``).
        """
        if output_dir is None:
            output_dir = Path.home() / "ps1-ai-player" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = output_dir / f"GDD_{game_id}_{timestamp}.md"
        json_path = output_dir / f"GDD_{game_id}_{timestamp}.json"

        if fmt in ("markdown", "both"):
            md_path.write_text(gdd_content)
            logger.info("GDD (markdown) saved to: %s", md_path)

        if fmt in ("json", "both"):
            json_path.write_text(
                json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
            )
            logger.info("GDD (JSON) saved to: %s", json_path)

        if fmt == "json":
            return json_path
        return md_path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Auto-generate GDD from causal chains or CSV")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--chains",
        type=Path,
        help="Path to causal_chains JSON file",
    )
    group.add_argument(
        "--csv",
        nargs="+",
        type=Path,
        help="CSV log file(s) for direct CSV → GDD generation",
    )
    parser.add_argument(
        "--game",
        "-g",
        default="UNKNOWN",
        help="Game ID",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory",
    )
    parser.add_argument(
        "--openai-key",
        default=None,
        help="OpenAI API key",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Generate GDD locally without LLM (no API key required)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "both"],
        default="markdown",
        dest="fmt",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--max-lag",
        type=int,
        default=10,
        help="Maximum lag steps for cross-correlation when using --csv (default: 10)",
    )
    parser.add_argument(
        "--lang",
        choices=["ja", "en"],
        default="ja",
        help="Language for LLM-generated GDD (default: ja)",
    )

    args = parser.parse_args()

    # Build generator
    if args.csv:
        generator = GDDGenerator.from_csv(args.csv, max_lag=args.max_lag)
    else:
        generator = GDDGenerator()
        generator.load_causal_chains(args.chains)

    # Generate GDD content
    if args.local:
        gdd = generator.generate_local_gdd(game_id=args.game)
    else:
        api_key = args.openai_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("No API key — falling back to local generation.")
            gdd = generator.generate_local_gdd(game_id=args.game)
        else:
            gdd = generator.generate_full_gdd(game_id=args.game, api_key=api_key, lang=args.lang)

    generator.save_gdd(gdd, game_id=args.game, output_dir=args.output, fmt=args.fmt)


if __name__ == "__main__":
    main()
