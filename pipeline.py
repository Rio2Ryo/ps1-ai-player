#!/usr/bin/env python3
"""End-to-end pipeline: CSV logs → causal analysis → GDD → simulation.

Orchestrates data_analyzer, gdd_generator, and game_prototype into a single
command. Supports both local-only (no API key) and LLM-enhanced modes.
"""

from __future__ import annotations

import argparse
import sys
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
    extractor: CausalChainExtractor | None = None,
    lang: str = "ja",
) -> tuple[str, Path]:
    """Step 2: Generate GDD from causal chains.

    Args:
        chains_path: Path to saved causal-chains JSON.
        game_id: Game identifier.
        api_key: Optional OpenAI API key.
        use_llm: Whether to use LLM-enhanced generation.
        extractor: If provided, the raw DataFrame is forwarded to the
            generator so that data-quality and event-analysis sections
            can inspect per-row data (missing values, outliers, action
            frequency).
        lang: Language for LLM-generated GDD (``"ja"`` or ``"en"``).

    Returns:
        Tuple of (GDD content, path to saved file).
    """
    logger.info("=" * 60)
    logger.info("STEP 2: GDD Generation")
    logger.info("=" * 60)

    generator = GDDGenerator()
    generator.load_causal_chains(chains_path)

    # Forward the raw DataFrame so sections that need row-level data
    # (data quality, event analysis) work inside the pipeline flow.
    if extractor is not None and not extractor.df.empty:
        generator.raw_df = extractor.df

    if use_llm and api_key:
        gdd_content = generator.generate_full_gdd(game_id=game_id, api_key=api_key, lang=lang)
    else:
        gdd_content = generator.generate_local_gdd(game_id=game_id)

    gdd_path = generator.save_gdd(gdd_content, game_id=game_id)
    logger.info("GDD generated: %s", gdd_path)
    return gdd_content, gdd_path


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
    from dotenv import load_dotenv

    load_dotenv()

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
    parser.add_argument(
        "--lang",
        choices=["ja", "en"],
        default="ja",
        help="Language for LLM-generated GDD (default: ja)",
    )

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
        extractor=extractor,
        lang=args.lang,
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
