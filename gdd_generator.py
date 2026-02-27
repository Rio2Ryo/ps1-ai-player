#!/usr/bin/env python3
"""Auto-generate Game Design Documents from extracted causal chains.

Reads causal chain JSON files produced by data_analyzer.py and uses
GPT-4 to generate comprehensive GDD in Markdown format. Supports both
LLM-enhanced and local-only (statistical) generation modes.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from log_config import get_logger

logger = get_logger(__name__)


class GDDGenerator:
    """Generate Game Design Documents from causal chain analysis data."""

    def __init__(self) -> None:
        self.chains: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}

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
        logger.info("Loaded %d causal chains from %s", len(self.chains), json_path.name)

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

    def generate_full_gdd(
        self,
        game_id: str = "UNKNOWN",
        api_key: str | None = None,
    ) -> str:
        """Generate a complete GDD using GPT-4 for narrative generation.

        Args:
            game_id: Game identifier for the title.
            api_key: OpenAI API key.

        Returns:
            Complete GDD as Markdown string.
        """
        import openai

        client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

        chains_json = json.dumps(self.chains, indent=2, ensure_ascii=False)
        metadata_json = json.dumps(self.metadata, indent=2, ensure_ascii=False)

        prompt = (
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

    def save_gdd(
        self,
        gdd_content: str,
        game_id: str = "UNKNOWN",
        output_dir: Path | None = None,
    ) -> Path:
        """Save GDD to Markdown file.

        Args:
            gdd_content: GDD markdown content.
            game_id: Game identifier.
            output_dir: Output directory.

        Returns:
            Path to saved file.
        """
        if output_dir is None:
            output_dir = Path.home() / "ps1-ai-player" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"GDD_{game_id}_{timestamp}.md"
        output_path = output_dir / filename
        output_path.write_text(gdd_content)
        logger.info("GDD saved to: %s", output_path)
        return output_path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Auto-generate GDD from causal chains")
    parser.add_argument(
        "--chains",
        type=Path,
        required=True,
        help="Path to causal_chains JSON file",
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

    args = parser.parse_args()

    generator = GDDGenerator()
    generator.load_causal_chains(args.chains)
    gdd = generator.generate_full_gdd(game_id=args.game, api_key=args.openai_key)
    generator.save_gdd(gdd, game_id=args.game, output_dir=args.output)


if __name__ == "__main__":
    main()
