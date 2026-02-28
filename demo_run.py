#!/usr/bin/env python3
"""End-to-end demo: sample data → causal analysis → GDD → charts → simulation.

Demonstrates the full PS1 AI Player analysis pipeline without requiring
DuckStation, PS1 ISO, BIOS, or an OpenAI API key.  Uses the synthetic
theme-park data in sample_data/sample_log.csv (auto-generated if missing).

Usage:
    python demo_run.py
    python demo_run.py --frames 1200 --output-dir reports/custom
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SAMPLE_CSV = PROJECT_ROOT / "sample_data" / "sample_log.csv"
GAME_ID = "DEMO"


def _ensure_sample_data(csv_path: Path) -> Path:
    """Generate sample CSV if it does not exist."""
    if csv_path.exists():
        print(f"[sample] Found existing data: {csv_path}")
        return csv_path

    print("[sample] sample_log.csv not found — generating …")
    sys.path.insert(0, str(csv_path.parent))
    from generate_sample import generate

    generate(output_path=csv_path)
    sys.path.pop(0)
    return csv_path


def run_demo(
    frames: int = 600,
    output_dir: Path | None = None,
) -> list[Path]:
    """Execute the full demo pipeline and return generated file paths.

    Args:
        frames: Number of simulation frames.
        output_dir: Directory for all outputs (created automatically).

    Returns:
        List of files created during the demo.
    """
    output_dir = output_dir or PROJECT_ROOT / "reports" / "demo"
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[Path] = []
    t_total = time.time()

    # ------------------------------------------------------------------
    # Step 0: Ensure sample data exists
    # ------------------------------------------------------------------
    t0 = time.time()
    csv_path = _ensure_sample_data(SAMPLE_CSV)
    print(f"  → elapsed: {time.time() - t0:.2f}s\n")

    # ------------------------------------------------------------------
    # Step 1: Causal chain analysis
    # ------------------------------------------------------------------
    print("=" * 60)
    print("STEP 1: Causal Chain Analysis")
    print("=" * 60)
    t0 = time.time()

    from data_analyzer import CausalChainExtractor

    extractor = CausalChainExtractor()
    extractor.load_logs([csv_path])
    extractor.compute_correlations()
    extractor.detect_lag_correlations(max_lag=10)
    extractor.build_causal_graph()
    chains_path = extractor.save_results(output_dir=output_dir)
    generated_files.append(chains_path)

    print(f"  Causal chains found: {len(extractor.causal_chains)}")
    print(f"  Saved: {chains_path}")
    print(f"  → elapsed: {time.time() - t0:.2f}s\n")

    # ------------------------------------------------------------------
    # Step 2: GDD generation (local, no API key)
    # ------------------------------------------------------------------
    print("=" * 60)
    print("STEP 2: GDD Generation (local)")
    print("=" * 60)
    t0 = time.time()

    from gdd_generator import GDDGenerator

    generator = GDDGenerator()
    generator.load_causal_chains(chains_path)
    if not extractor.df.empty:
        generator.raw_df = extractor.df
    gdd_content = generator.generate_local_gdd(game_id=GAME_ID)
    gdd_path = generator.save_gdd(gdd_content, game_id=GAME_ID, output_dir=output_dir)
    generated_files.append(gdd_path)

    print(f"  GDD length: {len(gdd_content)} chars")
    print(f"  Saved: {gdd_path}")
    print(f"  → elapsed: {time.time() - t0:.2f}s\n")

    # ------------------------------------------------------------------
    # Step 3: Visualizations
    # ------------------------------------------------------------------
    print("=" * 60)
    print("STEP 3: Chart Generation")
    print("=" * 60)
    t0 = time.time()

    from visualizer import generate_all_charts

    chart_paths = generate_all_charts(
        csv_path=csv_path,
        chains_json_path=chains_path,
        output_dir=output_dir,
    )
    generated_files.extend(chart_paths)

    for p in chart_paths:
        print(f"  Chart: {p.name}")
    print(f"  → elapsed: {time.time() - t0:.2f}s\n")

    # ------------------------------------------------------------------
    # Step 4: Simulation
    # ------------------------------------------------------------------
    print("=" * 60)
    print(f"STEP 4: Simulation ({frames} frames)")
    print("=" * 60)
    t0 = time.time()

    from game_prototype import ParkSimulator

    sim = ParkSimulator.from_gdd(gdd_path)
    sim_csv_path = output_dir / "simulation_output.csv"
    final_state = sim.run(frames=frames, csv_path=sim_csv_path)
    generated_files.append(sim_csv_path)

    print(f"  Final visitors: {final_state['visitor_count']}")
    print(f"  Final satisfaction: {final_state['avg_satisfaction']:.1f}")
    print(f"  Final park money: {final_state['park_money']:.0f}")
    print(f"  Saved: {sim_csv_path}")
    print(f"  → elapsed: {time.time() - t0:.2f}s\n")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed_total = time.time() - t_total
    print("=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print(f"\nGenerated {len(generated_files)} files in {output_dir}:")
    for p in generated_files:
        print(f"  {p.name}")
    print(f"\nTotal elapsed: {elapsed_total:.2f}s")

    return generated_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PS1 AI Player — end-to-end demo (no emulator needed)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=600,
        help="Simulation frames (default: 600)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: reports/demo)",
    )
    args = parser.parse_args()
    run_demo(frames=args.frames, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
