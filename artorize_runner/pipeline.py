"""
Unified protection pipeline with automatic GPU detection.

This module provides a single entry point that automatically detects
GPU availability and selects the optimal processing backend.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Set up logger
logger = logging.getLogger(__name__)

# Detect GPU availability
GPU_AVAILABLE = False
try:
    import torch
    GPU_AVAILABLE = torch.cuda.is_available()
    if GPU_AVAILABLE:
        logger.info(f"GPU detected: {torch.cuda.get_device_name(0)}")
    else:
        logger.info("CUDA not available, using CPU mode")
except ImportError:
    logger.info("PyTorch not installed, using CPU mode")


def setup_logging() -> None:
    """
    Configure comprehensive logging for system service deployment.

    Logs are formatted with timestamp, level, logger name, and message.
    All logs go to stdout/stderr which are captured by systemd and
    written to /var/log/artorize/runner.log and runner-error.log
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def run_pipeline(
    input_dir: str = "input",
    output_root: str = "outputs",
    include_hash_analysis: bool = True,
    max_workers: Optional[int] = None,
    use_multiprocessing: bool = False,
) -> Dict[str, object]:
    """
    Run the protection pipeline with automatic GPU detection.

    Args:
        input_dir: Directory containing input images
        output_root: Root directory for outputs
        include_hash_analysis: Whether to include hash analysis
        max_workers: Number of parallel workers (auto if None)
        use_multiprocessing: Use multiprocessing instead of threading

    Returns:
        Dictionary with processing results
    """
    if GPU_AVAILABLE:
        logger.info("Using GPU-accelerated pipeline")
        from .protection_pipeline_gpu import run_full_workflow_parallel

        return run_full_workflow_parallel(
            input_dir=input_dir,
            output_root=output_root,
            include_hash_analysis=include_hash_analysis,
            max_workers=max_workers,
            use_gpu=True,
            use_multiprocessing=use_multiprocessing,
        )
    else:
        logger.info("Using CPU pipeline")
        from .protection_pipeline import run_full_workflow

        return run_full_workflow(
            input_dir=input_dir,
            output_root=output_root,
            include_hash_analysis=include_hash_analysis,
        )


def main() -> None:
    """Main entry point with automatic GPU detection."""
    import argparse

    setup_logging()

    parser = argparse.ArgumentParser(
        description="Artorize Protection Pipeline (Auto-detects GPU)"
    )
    parser.add_argument("--input-dir", default="input", help="Input directory")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers")
    parser.add_argument("--multiprocessing", action="store_true", help="Use multiprocessing instead of threading")
    parser.add_argument("--no-analysis", action="store_true", help="Skip hash analysis")
    parser.add_argument("--cpu-only", action="store_true", help="Force CPU mode even if GPU is available")

    args = parser.parse_args()

    logger.info("Starting Artorize Protection Pipeline")
    logger.info(f"Configuration: input_dir={args.input_dir}, output_dir={args.output_dir}, "
               f"workers={args.workers or 'auto'}, multiprocessing={args.multiprocessing}, "
               f"analysis={'disabled' if args.no_analysis else 'enabled'}")

    # Override GPU detection if --cpu-only flag is set
    global GPU_AVAILABLE
    if args.cpu_only:
        logger.info("GPU disabled by --cpu-only flag")
        original_gpu_state = GPU_AVAILABLE
        GPU_AVAILABLE = False

    result = run_pipeline(
        input_dir=args.input_dir,
        output_root=args.output_dir,
        include_hash_analysis=not args.no_analysis,
        max_workers=args.workers,
        use_multiprocessing=args.multiprocessing,
    )

    # Restore GPU state
    if args.cpu_only:
        GPU_AVAILABLE = original_gpu_state

    logger.info("Pipeline processing completed")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
