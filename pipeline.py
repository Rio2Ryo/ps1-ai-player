#!/usr/bin/env python3
"""End-to-end pipeline: CSV logs → causal analysis → GDD → simulation.

Orchestrates data_analyzer, gdd_generator, and game_prototype into a single
command. Supports both local-only (no API key) and LLM-enhanced modes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from log_config import get_logger

logger = get_logger(__name__)

from data_analyzer import CausalChainExtractor
from gdd_generator import GDDGenerator
from game_prototype import ParkSimulator, RideAttraction, VisitorAgent


def run_analysis(
    log_files: list[Path],
    max_lag: int = 10,
    use_llm: bool = False,
    api_key: str | None = None,
) -> tuple[CausalChainExtractor, Path]:
    """Step 1: Analyze CSV logs and extract causal chains.

    Returns:
        Tuple of (extractor, path to saved JSON).
    """
    logger.info("=" * 60)
    logger.info("STEP 1: Causal Chain Analysis")
    logger.info("=" * 60)

    extractor = CausalChainExtractor()
    extractor.load_logs(log_files)

    if extractor.df.empty:
        logger.error("No data loaded from log files.")
        sys.exit(1)

    extractor.compute_correlations()
    extractor.detect_lag_correlations(max_lag=max_lag)
    extractor.build_causal_graph()

    if use_llm:
        extractor.llm_inference(api_key=api_key)

    result_path = extractor.save_results()
    logger.info("Analysis complete: %d causal chains found.", len(extractor.causal_chains))
    return extractor, result_path


def generate_gdd(
    chains_path: Path,
    game_id: str,
    api_key: str | None = None,
    use_llm: bool = False,
) -> tuple[str, Path]:
    """Step 2: Generate GDD from causal chains.

    Returns:
        Tuple of (GDD content, path to saved file).
    """
    logger.info("=" * 60)
    logger.info("STEP 2: GDD Generation")
    logger.info("=" * 60)

    generator = GDDGenerator()
    generator.load_causal_chains(chains_path)

    if use_llm and api_key:
        gdd_content = generator.generate_full_gdd(game_id=game_id, api_key=api_key)
    else:
        gdd_content = _generate_local_gdd(generator, game_id)

    gdd_path = generator.save_gdd(gdd_content, game_id=game_id)
    logger.info("GDD generated: %s", gdd_path)
    return gdd_content, gdd_path


def _generate_local_gdd(generator: GDDGenerator, game_id: str) -> str:
    """Generate a GDD using only local data (no API key required).

    Produces a complete GDD from statistical analysis without LLM assistance.
    """
    header = (
        f"# Game Design Document: {game_id}\n\n"
        f"Generated: {datetime.now().isoformat()}\n"
        f"Data samples: {generator.metadata.get('total_samples', 'N/A')}\n"
        f"Causal chains: {len(generator.chains)}\n"
        f"Mode: Local analysis (no LLM)\n\n"
        "---\n\n"
    )

    # Overview
    overview = "## Overview\n\n"
    params = generator.metadata.get("parameters", [])
    overview += (
        f"This GDD was auto-generated from gameplay data analysis of a PS1 game.\n"
        f"The analysis tracked {len(params)} parameters: "
        f"{', '.join(params)}.\n\n"
    )

    # Parameter definitions
    param_section = "## Parameter Definitions\n\n"
    param_section += "| Parameter | Role |\n"
    param_section += "|-----------|------|\n"
    param_roles = {
        "money": "Primary resource / economy indicator",
        "visitors": "Population / demand metric",
        "satisfaction": "Quality of experience indicator",
        "nausea": "Negative status effect from high-intensity rides",
        "hunger": "Time-dependent need requiring food purchase",
        "ride_intensity": "Attraction excitement level / risk factor",
    }
    for p in params:
        role = param_roles.get(p, "Game parameter")
        param_section += f"| {p} | {role} |\n"
    param_section += "\n"

    # Mechanics, balance, feedback loops, state analysis, strategy from generator
    mechanics = generator.generate_mechanics_section()
    balance = generator.generate_balance_section()
    feedback_loops = generator.generate_feedback_loops_section()
    state_analysis = generator.generate_state_analysis_section()
    strategy_config = generator.generate_strategy_section()

    # Implementation priority
    priority = "## Implementation Priority\n\n"
    priority += "Based on causal chain confidence scores:\n\n"
    sorted_chains = sorted(
        generator.chains,
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
        + mechanics + "\n"
        + balance + "\n"
        + feedback_loops + "\n"
        + state_analysis + "\n"
        + strategy_config + "\n"
        + priority
    )


def run_simulation(
    gdd_path: Path | None = None,
    frames: int = 3600,
    verbose: bool = False,
) -> dict[str, Any]:
    """Step 3: Run the game prototype simulation.

    Returns:
        Final simulation state.
    """
    logger.info("=" * 60)
    logger.info("STEP 3: Prototype Simulation")
    logger.info("=" * 60)

    if gdd_path and gdd_path.exists():
        sim = ParkSimulator.from_gdd(gdd_path)
    else:
        sim = ParkSimulator(
            visitors=[VisitorAgent(visitor_id=i) for i in range(20)],
            attractions=[
                RideAttraction(name="Roller Coaster", intensity=80, satisfaction_boost=15),
                RideAttraction(name="Ferris Wheel", intensity=30, satisfaction_boost=10),
                RideAttraction(name="Haunted House", intensity=60, satisfaction_boost=12),
            ],
        )

    final_state = sim.run(frames=frames, verbose=verbose)

    logger.info("Simulation complete: %d frames", frames)
    return final_state


def main() -> None:
    """CLI entry point for the full pipeline."""
    parser = argparse.ArgumentParser(
        description="PS1 AI Player: End-to-end analysis pipeline"
    )
    parser.add_argument(
        "--logs",
        nargs="+",
        type=Path,
        required=True,
        help="CSV log file(s) to analyze",
    )
    parser.add_argument("--game", "-g", default="UNKNOWN", help="Game ID")
    parser.add_argument(
        "--max-lag",
        type=int,
        default=10,
        help="Max lag steps for cross-correlation (default: 10)",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable LLM-enhanced analysis and GDD generation (requires OPENAI_API_KEY)",
    )
    parser.add_argument("--openai-key", default=None, help="OpenAI API key")
    parser.add_argument(
        "--sim-frames",
        type=int,
        default=3600,
        help="Simulation frames (default: 3600)",
    )
    parser.add_argument(
        "--skip-sim",
        action="store_true",
        help="Skip the simulation step",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    import os

    api_key = args.openai_key or os.environ.get("OPENAI_API_KEY")

    # Step 1: Analysis
    extractor, chains_path = run_analysis(
        log_files=args.logs,
        max_lag=args.max_lag,
        use_llm=args.llm and bool(api_key),
        api_key=api_key,
    )

    # Step 2: GDD
    gdd_content, gdd_path = generate_gdd(
        chains_path=chains_path,
        game_id=args.game,
        api_key=api_key,
        use_llm=args.llm and bool(api_key),
    )

    # Step 3: Simulation
    if not args.skip_sim:
        final_state = run_simulation(
            gdd_path=gdd_path,
            frames=args.sim_frames,
            verbose=args.verbose,
        )

    # Summary
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info("Causal chains: %s", chains_path)
    logger.info("GDD:           %s", gdd_path)
    if not args.skip_sim:
        logger.info("Simulation:    %d frames completed", args.sim_frames)


if __name__ == "__main__":
    main()
