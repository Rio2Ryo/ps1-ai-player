#!/usr/bin/env python3
"""Auto-generate Game Design Documents from extracted causal chains.

Reads causal chain JSON files produced by data_analyzer.py and uses
GPT-4 to generate comprehensive GDD in Markdown format.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


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
        print(f"Loaded {len(self.chains)} causal chains from {json_path.name}")

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
            "6. 実装優先度 (Implementation Priority)\n\n"
            f"## 因果チェーンデータ\n```json\n{chains_json}\n```\n\n"
            f"## メタデータ\n```json\n{metadata_json}\n```\n\n"
            "Markdown形式で完全なGDDを生成してください。日本語で記述してください。"
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.3,
        )

        llm_gdd = response.choices[0].message.content or ""

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
        print(f"GDD saved to: {output_path}")
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
