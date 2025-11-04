from __future__ import annotations

import json
import shutil
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parent
    parent_dir = package_root.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    __package__ = package_root.name  # type: ignore[assignment]


try:
    import torch
    import torch.nn.functional as F
    import torchvision.transforms.functional as TF
    TORCH_AVAILABLE = True
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"PyTorch initialized with device: {DEVICE}")
except ImportError as exc:
    TORCH_AVAILABLE = False
    DEVICE = None
    warnings.warn(
        f"PyTorch stack not available ({exc}). GPU acceleration disabled. "
        "Install torch/torchvision as described in README.md to enable GPU support.",
        stacklevel=2,
    )

from .cli import build_processors
from .core import run_pipeline, dumps_json
from .utils import extend_sys_path
from .c2pa_metadata import C2PAManifestConfig, embed_c2pa_manifest
from .protection_pipeline import (
    ProtectionStage,
    ProtectionWorkflowConfig,
    PROJECT_CATALOGUE,
    POISON_MASK_AVAILABLE,
    _ensure_directory,
    _save_image,
    _build_project_status,
    _apply_poison_mask_if_enabled,
)

# Global RNG to keep transforms deterministic across runs
_RNG = np.random.default_rng(seed=20240917)
MAX_STAGE_DIM = 512

# GPU-accelerated transformation functions
def _apply_fawkes_like_gpu(image: Image.Image) -> Image.Image:
    """GPU-accelerated Gaussian noise cloaking."""
    if not TORCH_AVAILABLE:
        return _apply_fawkes_like_cpu(image)

    # Convert to tensor
    tensor = TF.to_tensor(image).unsqueeze(0).to(DEVICE)

    # Generate noise on GPU
    noise = torch.randn_like(tensor, device=DEVICE) * 6.5 / 255.0

    # Add noise and clamp
    noisy = torch.clamp(tensor + noise, 0, 1)

    # Convert back to PIL
    noisy_np = (noisy.squeeze(0).cpu().numpy() * 255).astype(np.uint8)
    noisy_np = np.transpose(noisy_np, (1, 2, 0))
    return Image.fromarray(noisy_np)


def _apply_fawkes_like_cpu(image: Image.Image) -> Image.Image:
    """CPU fallback for Fawkes effect."""
    arr = np.asarray(image, dtype=np.float32)
    noise = _RNG.normal(loc=0.0, scale=6.5, size=arr.shape)
    noisy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy)


def _apply_photoguard_like_gpu(image: Image.Image) -> Image.Image:
    """GPU-accelerated blur and edge detection."""
    if not TORCH_AVAILABLE:
        return _apply_photoguard_like_cpu(image)

    tensor = TF.to_tensor(image).unsqueeze(0).to(DEVICE)

    # Gaussian blur on GPU
    blurred = TF.gaussian_blur(tensor.squeeze(0), kernel_size=[5, 5], sigma=[1.6, 1.6])
    blurred = blurred.unsqueeze(0)

    # Edge detection using Sobel filters
    sobel_x = torch.tensor([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]],
                           dtype=torch.float32, device=DEVICE).view(1, 1, 3, 3)
    sobel_y = torch.tensor([[-1, -2, -1], [0, 0, 0], [1, 2, 1]],
                           dtype=torch.float32, device=DEVICE).view(1, 1, 3, 3)

    # Apply edge detection per channel
    edges_list = []
    for c in range(tensor.shape[1]):
        channel = tensor[:, c:c+1, :, :]
        edge_x = F.conv2d(channel, sobel_x, padding=1)
        edge_y = F.conv2d(channel, sobel_y, padding=1)
        edges = torch.sqrt(edge_x**2 + edge_y**2)
        edges_list.append(edges)
    edges = torch.cat(edges_list, dim=1)

    # Normalize edges
    edges = edges / edges.max()

    # Blend operations
    mixed = 0.6 * blurred + 0.4 * edges
    result = 0.65 * tensor + 0.35 * mixed
    result = torch.clamp(result, 0, 1)

    # Convert back
    result_np = (result.squeeze(0).cpu().numpy() * 255).astype(np.uint8)
    result_np = np.transpose(result_np, (1, 2, 0))
    return Image.fromarray(result_np)


def _apply_photoguard_like_cpu(image: Image.Image) -> Image.Image:
    """CPU fallback for PhotoGuard effect."""
    blurred = image.filter(ImageFilter.GaussianBlur(radius=1.6))
    edges = image.filter(ImageFilter.FIND_EDGES)
    mixed = Image.blend(blurred, edges, alpha=0.4)
    return Image.blend(image, mixed, alpha=0.35)


def _apply_mist_like_gpu(image: Image.Image) -> Image.Image:
    """GPU-accelerated color enhancement."""
    if not TORCH_AVAILABLE:
        return _apply_mist_like_cpu(image)

    tensor = TF.to_tensor(image).unsqueeze(0).to(DEVICE)

    # Color enhancement
    tensor = TF.adjust_saturation(tensor.squeeze(0), 1.22)
    tensor = tensor.unsqueeze(0)

    # Contrast enhancement
    mean = tensor.mean(dim=[2, 3], keepdim=True)
    tensor = 1.08 * (tensor - mean) + mean

    # Sharpness via unsharp mask
    blurred = TF.gaussian_blur(tensor.squeeze(0), kernel_size=[3, 3], sigma=[0.8, 0.8])
    blurred = blurred.unsqueeze(0)
    sharpened = tensor + 0.12 * (tensor - blurred)

    result = torch.clamp(sharpened, 0, 1)

    result_np = (result.squeeze(0).cpu().numpy() * 255).astype(np.uint8)
    result_np = np.transpose(result_np, (1, 2, 0))
    return Image.fromarray(result_np)


def _apply_mist_like_cpu(image: Image.Image) -> Image.Image:
    """CPU fallback for Mist effect."""
    color_enhanced = ImageEnhance.Color(image).enhance(1.22)
    contrast_enhanced = ImageEnhance.Contrast(color_enhanced).enhance(1.08)
    sharp_enhanced = ImageEnhance.Sharpness(contrast_enhanced).enhance(1.12)
    return sharp_enhanced


def _apply_nightshade_like_gpu(image: Image.Image) -> Image.Image:
    """GPU-accelerated pixel shifting and noise."""
    if not TORCH_AVAILABLE:
        return _apply_nightshade_like_cpu(image)

    tensor = TF.to_tensor(image).unsqueeze(0).to(DEVICE)

    # Horizontal shift
    shifted = torch.roll(tensor, shifts=5, dims=3)

    # Generate noise
    noise = torch.randn_like(tensor, device=DEVICE) * 4.0 / 255.0

    # Mix
    mixed = 0.82 * tensor + 0.13 * shifted + noise
    result = torch.clamp(mixed, 0, 1)

    result_np = (result.squeeze(0).cpu().numpy() * 255).astype(np.uint8)
    result_np = np.transpose(result_np, (1, 2, 0))
    return Image.fromarray(result_np)


def _apply_nightshade_like_cpu(image: Image.Image) -> Image.Image:
    """CPU fallback for Nightshade effect."""
    arr = np.asarray(image, dtype=np.float32)
    shifted = np.roll(arr, shift=5, axis=1)
    noise = _RNG.normal(loc=0.0, scale=4.0, size=arr.shape)
    mixed = 0.82 * arr + 0.13 * shifted + noise
    mixed = np.clip(mixed, 0, 255).astype(np.uint8)
    return Image.fromarray(mixed)


def _apply_invisible_watermark_vectorized(image: Image.Image, watermark: str = "artscraper") -> Image.Image:
    """Vectorized LSB watermark embedding."""
    arr = np.asarray(image, dtype=np.uint8)
    flat = arr.reshape(-1)

    # Prepare bits
    payload = watermark.encode("utf-8")
    bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))

    if len(bits) > flat.size:
        return image

    # Vectorized LSB embedding
    masked = flat.copy()
    masked[:len(bits)] = (masked[:len(bits)] & 0xFE) | bits

    watermarked = masked.reshape(arr.shape)
    return Image.fromarray(watermarked)


def _apply_tree_ring_gpu(image: Image.Image, *, frequency: float = 9.0, amplitude: float = 18.0) -> Image.Image:
    """GPU-accelerated tree-ring watermark."""
    if not TORCH_AVAILABLE:
        return _apply_tree_ring_cpu(image, frequency=frequency, amplitude=amplitude)

    tensor = TF.to_tensor(image).unsqueeze(0).to(DEVICE)
    height, width = tensor.shape[2:]

    # Create radial distance map
    y_grid, x_grid = torch.meshgrid(
        torch.arange(height, device=DEVICE, dtype=torch.float32),
        torch.arange(width, device=DEVICE, dtype=torch.float32),
        indexing='ij'
    )

    center_y, center_x = height / 2.0, width / 2.0
    radial = torch.sqrt((y_grid - center_y)**2 + (x_grid - center_x)**2)

    # Generate rings
    rings = torch.sin(radial / max(frequency, 1e-5)) * amplitude / 255.0
    rings = rings.unsqueeze(0).unsqueeze(0)

    # Apply perturbation
    perturbed = tensor + rings
    result = torch.clamp(perturbed, 0, 1)

    result_np = (result.squeeze(0).cpu().numpy() * 255).astype(np.uint8)
    result_np = np.transpose(result_np, (1, 2, 0))
    return Image.fromarray(result_np)


def _apply_tree_ring_cpu(image: Image.Image, *, frequency: float = 9.0, amplitude: float = 18.0) -> Image.Image:
    """CPU fallback for tree-ring watermark."""
    arr = np.asarray(image, dtype=np.float32)
    height, width = arr.shape[:2]
    yy, xx = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
    center_y, center_x = height / 2.0, width / 2.0
    radial = np.sqrt((yy - center_y) ** 2 + (xx - center_x) ** 2)
    rings = np.sin(radial / max(frequency, 1e-5)) * amplitude
    perturbed = arr + rings[..., None]
    perturbed = np.clip(perturbed, 0, 255).astype(np.uint8)
    return Image.fromarray(perturbed)


def _apply_stegano_embed_vectorized(image: Image.Image, message: str = "Protected by artscraper") -> Image.Image:
    """Vectorized steganography embedding."""
    base = image.convert("RGB")
    arr = np.asarray(base, dtype=np.uint8)
    flat = arr.reshape(-1)

    payload = message.encode("utf-8")
    # Add terminator
    payload_with_term = np.concatenate([
        np.frombuffer(payload, dtype=np.uint8),
        np.zeros(1, dtype=np.uint8)
    ])
    bits = np.unpackbits(payload_with_term)

    if len(bits) > flat.size:
        return base

    # Vectorized embedding
    embedded = flat.copy()
    embedded[:len(bits)] = (embedded[:len(bits)] & 0xFE) | bits

    framed = embedded.reshape(arr.shape)
    return Image.fromarray(framed)




def _build_stage_sequence_gpu(config: ProtectionWorkflowConfig) -> Sequence[ProtectionStage]:
    """Build protection stages with GPU acceleration where available."""
    stages: List[ProtectionStage] = []

    if config.enable_fawkes:
        stages.append(ProtectionStage("fawkes", "Gaussian cloak perturbation", _apply_fawkes_like_gpu))
    if config.enable_photoguard:
        stages.append(ProtectionStage("photoguard", "Adversarial blur + edge fusion", _apply_photoguard_like_gpu))
    if config.enable_mist:
        stages.append(ProtectionStage("mist", "Colour variance amplification", _apply_mist_like_gpu))
    if config.enable_nightshade:
        stages.append(ProtectionStage("nightshade", "Spatial poison perturbation", _apply_nightshade_like_gpu))

    strategy = config.watermark_strategy
    if strategy == "invisible-watermark":
        def apply_watermark(image: Image.Image) -> Image.Image:
            return _apply_invisible_watermark_vectorized(image, watermark=config.watermark_text)
        stages.append(ProtectionStage("invisible-watermark", "LSB text watermark embed", apply_watermark))
    elif strategy == "tree-ring":
        def apply_tree_ring(image: Image.Image) -> Image.Image:
            return _apply_tree_ring_gpu(image, frequency=config.tree_ring_frequency, amplitude=config.tree_ring_amplitude)
        stages.append(ProtectionStage("tree-ring", "Radial tree-ring perturbation", apply_tree_ring))

    if config.enable_stegano_embed:
        def apply_stegano(image: Image.Image) -> Image.Image:
            return _apply_stegano_embed_vectorized(image, message=config.stegano_message)
        stages.append(ProtectionStage("stegano-embed", "Embed steganographic payload", apply_stegano))

    return stages


def _apply_layers_batched(
    image_path: Path,
    target_dir: Path,
    config: ProtectionWorkflowConfig,
    use_gpu: bool = True
) -> List[Dict[str, object]]:
    """Apply protection layers with optional GPU acceleration."""
    original = Image.open(image_path)
    fmt = getattr(original, "format", None)
    rgb_image = original.convert("RGB")

    # Prepare working image
    working = rgb_image
    if max(rgb_image.size) > MAX_STAGE_DIM:
        scale = MAX_STAGE_DIM / float(max(rgb_image.size))
        new_size = (
            max(1, int(round(rgb_image.width * scale))),
            max(1, int(round(rgb_image.height * scale))),
        )
        working = rgb_image.resize(new_size, resample=Image.Resampling.LANCZOS)

    layers_dir = target_dir / "layers"
    _ensure_directory(layers_dir)

    stages: List[Dict[str, object]] = []

    # Save original
    base_dir = layers_dir / "00-original"
    _ensure_directory(base_dir)
    base_path = base_dir / image_path.name
    _save_image(original, base_path, fmt)
    stages.append({
        "stage": "original",
        "description": "Unmodified input image",
        "path": str(base_path.resolve()),
        "processing_size": list(rgb_image.size),
        "mask_path": None,
    })
    last_stage_path = base_path

    # Apply protection stages
    stage_sequence = _build_stage_sequence_gpu(config) if use_gpu else _build_stage_sequence_gpu(config)
    current = working
    previous_saved = rgb_image

    # Measure performance
    stage_times = {}

    for index, stage in enumerate(stage_sequence, start=1):
        layer_dir = layers_dir / f"{index:02d}-{stage.key}"
        _ensure_directory(layer_dir)

        # Time the stage application
        start_time = time.perf_counter()
        current = stage.apply(current)
        stage_times[stage.key] = time.perf_counter() - start_time

        # Resize if needed
        saved_image = current
        if saved_image.size != original.size:
            saved_image = saved_image.resize(original.size, resample=Image.Resampling.BICUBIC)

        # Save stage output
        stage_path = layer_dir / image_path.name
        _save_image(saved_image, stage_path, fmt)

        # Apply poison mask processor if enabled
        poison_mask_data = _apply_poison_mask_if_enabled(
            image=saved_image,
            original=previous_saved,
            config=config,
            layer_dir=layer_dir,
            stage_name=f"{index:02d}-{stage.key}"
        )

        stage_data = {
            "stage": stage.key,
            "description": stage.description,
            "path": str(stage_path.resolve()),
            "processing_size": list(current.size),
            "processing_time": stage_times[stage.key],
            "gpu_accelerated": use_gpu and TORCH_AVAILABLE,
            "is_protection_layer": True,  # Mark as protection layer for backend upload
        }

        # Add poison mask data to stage info if available
        if poison_mask_data:
            stage_data.update(poison_mask_data)
            stage_data["has_sac_mask"] = True  # Explicitly mark that SAC mask exists

        stages.append(stage_data)
        last_stage_path = stage_path
        previous_saved = saved_image.convert("RGB")

    # Handle C2PA manifest if enabled
    if config.enable_c2pa_manifest:
        c2pa_dir = target_dir / "c2pa"
        _ensure_directory(c2pa_dir)
        source_for_manifest = (
            last_stage_path
            if last_stage_path and last_stage_path.exists()
            else base_path
        )
        try:
            c2pa_result = embed_c2pa_manifest(
                source_path=source_for_manifest,
                dest_dir=c2pa_dir,
                manifest_config=config.c2pa_manifest,
                asset_id=image_path.stem,
            )
            signed_path = Path(c2pa_result["signed_path"])
            with Image.open(signed_path) as final_image:
                final_image.load()
                final_rgb = final_image.convert("RGB")
            previous_saved = final_rgb
            last_stage_path = signed_path
            stages.append({
                "stage": "c2pa-manifest",
                "description": "Embedded C2PA AI training manifest and IPTC signal",
                "path": str(signed_path.resolve()),
                "processing_size": list(original.size),
                "manifest_path": str(Path(c2pa_result["manifest_path"]).resolve()),
                "certificate_path": str(Path(c2pa_result["certificate_path"]).resolve()),
                "license_path": (
                    str(Path(c2pa_result["license_path"]).resolve())
                    if c2pa_result.get("license_path")
                    else None
                ),
                "xmp_path": str(Path(c2pa_result["xmp_path"]).resolve()),
            })
        except Exception as exc:
            fallback_path = source_for_manifest.resolve(strict=False)
            try:
                with Image.open(fallback_path) as fallback_image:
                    fallback_image.load()
                    fallback_rgb = fallback_image.convert("RGB")
            except Exception:
                fallback_rgb = previous_saved
            previous_saved = fallback_rgb
            stages.append({
                "stage": "c2pa-manifest",
                "description": "Attempted to embed C2PA manifest",
                "error": str(exc),
                "path": str(fallback_path),
                "processing_size": list(original.size),
                "artifact_dir": str(c2pa_dir.resolve()),
            })

    # Generate final comparison mask between final output and original input (MANDATORY)
    # This mask traces back to the original image and is required for provenance
    if POISON_MASK_AVAILABLE and previous_saved is not None:
        final_dir = layers_dir / f"{len(stage_sequence)+1:02d}-final-comparison"
        _ensure_directory(final_dir)

        final_poison_mask_data = _apply_poison_mask_if_enabled(
            image=previous_saved,
            original=rgb_image,
            config=config,
            layer_dir=final_dir,
            stage_name=f"{len(stage_sequence)+1:02d}-final-comparison",
            force=True,  # Final comparison is mandatory for provenance
            generate_sac=True  # Only generate SAC for final comparison (sent to backend)
        )

        if final_poison_mask_data:
            stages.append({
                "stage": "final-comparison",
                "description": "Complete protection mask (final vs original)",
                "path": None,
                "processing_size": list(original.size),
                "has_sac_mask": True,  # Explicitly mark that SAC mask exists (final comparison always has SAC)
                **final_poison_mask_data
            })

    return stages


def process_image_wrapper(args: Tuple[Path, Path, ProtectionWorkflowConfig, bool, bool]) -> Dict[str, object]:
    """Wrapper function for parallel processing of images."""
    image_path, output_root, workflow_config, include_hash_analysis, use_gpu = args

    target_dir = output_root / image_path.stem
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    analysis_summary: Optional[Dict[str, object]] = None
    if include_hash_analysis:
        processors = build_processors(include_tineye=False)
        analysis_summary = run_pipeline(str(image_path), processors)
        analysis_path = target_dir / "analysis.json"
        analysis_path.write_text(dumps_json(analysis_summary), encoding="ascii")

    stage_records = _apply_layers_batched(image_path, target_dir, workflow_config, use_gpu)
    project_status = _build_project_status(stage_records, analysis_summary)

    summary = {
        "image": str(image_path.resolve()),
        "analysis": str((target_dir / "analysis.json").resolve()) if analysis_summary else None,
        "layers": stage_records,
        "projects": project_status,
    }
    summary_path = target_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="ascii")

    return {
        "image": str(image_path.resolve()),
        "output_dir": str(target_dir.resolve()),
        "summary": str(summary_path.resolve()),
    }


def run_full_workflow_parallel(
    input_dir: Path | str = Path("input"),
    output_root: Path | str = Path("outputs"),
    include_hash_analysis: bool = True,
    config: ProtectionWorkflowConfig | None = None,
    max_workers: int = None,
    use_gpu: bool = True,
    use_multiprocessing: bool = False
) -> Dict[str, object]:
    """Execute workflow with parallel processing and optional GPU acceleration.

    Args:
        input_dir: Directory containing input images
        output_root: Root directory for outputs
        include_hash_analysis: Whether to run hash analysis
        config: Protection workflow configuration
        max_workers: Maximum parallel workers (None for auto)
        use_gpu: Enable GPU acceleration if available
        use_multiprocessing: Use process pool instead of thread pool
    """
    extend_sys_path()
    input_dir = Path(input_dir)
    output_root = Path(output_root)
    workflow_config = config or ProtectionWorkflowConfig()

    if not input_dir.exists():
        raise FileNotFoundError(f"input directory not found: {input_dir}")

    # Collect all image paths
    image_paths = sorted(p for p in input_dir.iterdir() if p.is_file())

    if not image_paths:
        return {"processed": [], "message": "No images found in input directory"}

    # Prepare arguments for parallel processing
    args_list = [
        (image_path, output_root, workflow_config, include_hash_analysis, use_gpu)
        for image_path in image_paths
    ]

    outputs: List[Dict[str, object]] = []
    start_time = time.perf_counter()

    # Choose executor based on configuration
    if use_multiprocessing and len(image_paths) > 1:
        executor_class = ProcessPoolExecutor
    else:
        executor_class = ThreadPoolExecutor

    # Process images in parallel
    with executor_class(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_image_wrapper, args): args[0]
            for args in args_list
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                outputs.append(result)
                print(f"Processed: {futures[future].name}")
            except Exception as e:
                print(f"Error processing {futures[future]}: {e}")

    total_time = time.perf_counter() - start_time

    return {
        "processed": outputs,
        "total_processing_time": total_time,
        "gpu_available": TORCH_AVAILABLE and torch.cuda.is_available(),
        "device_used": str(DEVICE) if TORCH_AVAILABLE else "cpu",
        "parallel_workers": max_workers or "auto"
    }


def main() -> None:
    """Main entry point with GPU and parallel processing."""
    import argparse

    parser = argparse.ArgumentParser(description="Protection pipeline with GPU acceleration")
    parser.add_argument("--input-dir", default="input", help="Input directory")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers")
    parser.add_argument("--no-gpu", action="store_true", help="Disable GPU acceleration")
    parser.add_argument("--multiprocessing", action="store_true", help="Use multiprocessing instead of threading")
    parser.add_argument("--no-analysis", action="store_true", help="Skip hash analysis")

    args = parser.parse_args()

    result = run_full_workflow_parallel(
        input_dir=args.input_dir,
        output_root=args.output_dir,
        include_hash_analysis=not args.no_analysis,
        max_workers=args.workers,
        use_gpu=not args.no_gpu,
        use_multiprocessing=args.multiprocessing
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
