from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Literal

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from .cli import build_processors
from .core import run_pipeline, dumps_json
from .utils import extend_sys_path
from .c2pa_metadata import C2PAManifestConfig, embed_c2pa_manifest

# Import poison mask processor functions
try:
    from processors.poison_mask.processor import compute_mask, build_metadata
    POISON_MASK_AVAILABLE = True
except ImportError:
    POISON_MASK_AVAILABLE = False

@dataclass
class ProtectionStage:
    """Represents a single protection transformation layer."""

    key: str
    description: str
    apply: Callable[[Image.Image], Image.Image]

@dataclass
class ProtectionWorkflowConfig:
    """Controls which protection layers are executed and in what variants."""

    enable_fawkes: bool = True
    enable_photoguard: bool = True
    enable_mist: bool = True
    enable_nightshade: bool = True
    watermark_strategy: Optional[Literal["invisible-watermark", "tree-ring"]] = "invisible-watermark"
    watermark_text: str = "artscraper"
    tree_ring_frequency: float = 9.0
    tree_ring_amplitude: float = 18.0
    enable_stegano_embed: bool = False
    stegano_message: str = "Protected by artscraper"
    enable_c2pa_manifest: bool = True
    c2pa_manifest: C2PAManifestConfig = field(default_factory=C2PAManifestConfig)
    enable_poison_mask: bool = True
    poison_mask_filter_id: str = "poison-mask"
    poison_mask_css_class: str = "poisoned-image"



# Global RNG to keep transforms deterministic across runs
_RNG = np.random.default_rng(seed=20240917)
MAX_STAGE_DIM = 512


def _apply_fawkes_like(image: Image.Image) -> Image.Image:
    """Approximate the cloaking effect with controlled Gaussian noise."""
    arr = np.asarray(image, dtype=np.float32)
    noise = _RNG.normal(loc=0.0, scale=6.5, size=arr.shape)
    noisy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy)


def _apply_photoguard_like(image: Image.Image) -> Image.Image:
    """Blend the image with its smoothed + edge representation."""
    blurred = image.filter(ImageFilter.GaussianBlur(radius=1.6))
    edges = image.filter(ImageFilter.FIND_EDGES)
    mixed = Image.blend(blurred, edges, alpha=0.4)
    return Image.blend(image, mixed, alpha=0.35)


def _apply_mist_like(image: Image.Image) -> Image.Image:
    """Boost colour variance and contrast to mimic Mist perturbations."""
    color_enhanced = ImageEnhance.Color(image).enhance(1.22)
    contrast_enhanced = ImageEnhance.Contrast(color_enhanced).enhance(1.08)
    sharp_enhanced = ImageEnhance.Sharpness(contrast_enhanced).enhance(1.12)
    return sharp_enhanced


def _apply_nightshade_like(image: Image.Image) -> Image.Image:
    """Introduce structured perturbations by spatially mixing pixels."""
    arr = np.asarray(image, dtype=np.float32)
    shifted = np.roll(arr, shift=5, axis=1)
    noise = _RNG.normal(loc=0.0, scale=4.0, size=arr.shape)
    mixed = 0.82 * arr + 0.13 * shifted + noise
    mixed = np.clip(mixed, 0, 255).astype(np.uint8)
    return Image.fromarray(mixed)


def _apply_invisible_watermark(image: Image.Image, watermark: str = "artscraper") -> Image.Image:
    """Embed a simple LSB watermark derived from text."""
    arr = np.asarray(image, dtype=np.uint8)
    flat = arr.reshape(-1)
    bits: List[int] = []
    for byte in watermark.encode("utf-8"):
        for bit in range(8):
            bits.append((byte >> bit) & 1)
    if len(bits) > flat.size:
        return image
    masked = flat.copy()
    for idx, bit in enumerate(bits):
        value = int(masked[idx])
        masked[idx] = np.uint8((value & 0xFE) | bit)
    watermarked = masked.reshape(arr.shape)
    return Image.fromarray(watermarked)


def _apply_tree_ring(image: Image.Image, *, frequency: float = 9.0, amplitude: float = 18.0) -> Image.Image:
    """Add a provenance-style tree-ring watermark through radial modulation."""
    arr = np.asarray(image, dtype=np.float32)
    height, width = arr.shape[:2]
    yy, xx = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
    center_y, center_x = height / 2.0, width / 2.0
    radial = np.sqrt((yy - center_y) ** 2 + (xx - center_x) ** 2)
    rings = np.sin(radial / max(frequency, 1e-5)) * amplitude
    perturbed = arr + rings[..., None]
    perturbed = np.clip(perturbed, 0, 255).astype(np.uint8)
    return Image.fromarray(perturbed)



def _apply_stegano_embed(image: Image.Image, message: str = "Protected by artscraper") -> Image.Image:
    """Embed a short payload using classic LSB steganography."""
    base = image.convert("RGB")
    arr = np.asarray(base, dtype=np.uint8)
    flat = arr.reshape(-1)
    payload = message.encode("utf-8")
    bits: List[int] = []
    for byte in payload:
        for bit in range(7, -1, -1):
            bits.append((byte >> bit) & 1)
    bits.extend([0] * 8)  # sentinel terminator
    if len(bits) > flat.size:
        return base
    embedded = flat.copy()
    for idx, bit in enumerate(bits):
        embedded[idx] = np.uint8((embedded[idx] & 0xFE) | bit)
    framed = embedded.reshape(arr.shape)
    return Image.fromarray(framed)



def _build_stage_sequence(config: ProtectionWorkflowConfig) -> Sequence[ProtectionStage]:
    """Construct the ordered protection stages for the given configuration."""
    stages: List[ProtectionStage] = []
    if config.enable_fawkes:
        stages.append(ProtectionStage("fawkes", "Gaussian cloak perturbation", _apply_fawkes_like))
    if config.enable_photoguard:
        stages.append(ProtectionStage("photoguard", "Adversarial blur + edge fusion", _apply_photoguard_like))
    if config.enable_mist:
        stages.append(ProtectionStage("mist", "Colour variance amplification", _apply_mist_like))
    if config.enable_nightshade:
        stages.append(ProtectionStage("nightshade", "Spatial poison perturbation", _apply_nightshade_like))

    strategy = config.watermark_strategy
    if strategy == "invisible-watermark":
        def apply_watermark(image: Image.Image, text: str = config.watermark_text) -> Image.Image:
            return _apply_invisible_watermark(image, watermark=text)

        stages.append(ProtectionStage("invisible-watermark", "LSB text watermark embed", apply_watermark))
    elif strategy == "tree-ring":
        def apply_tree_ring(image: Image.Image, freq: float = config.tree_ring_frequency, amp: float = config.tree_ring_amplitude) -> Image.Image:
            return _apply_tree_ring(image, frequency=freq, amplitude=amp)

        stages.append(ProtectionStage("tree-ring", "Radial tree-ring perturbation", apply_tree_ring))

    if config.enable_stegano_embed:
        def apply_stegano(image: Image.Image, text: str = config.stegano_message) -> Image.Image:
            return _apply_stegano_embed(image, message=text)

        stages.append(ProtectionStage("stegano-embed", "Embed steganographic payload", apply_stegano))

    return stages


def _apply_poison_mask_if_enabled(
    image: Image.Image,
    original: Image.Image,
    config: ProtectionWorkflowConfig,
    target_dir: Path,
    stage_name: str
) -> Optional[Dict[str, object]]:
    """Apply poison mask processor if enabled and available."""
    if not config.enable_poison_mask or not POISON_MASK_AVAILABLE:
        return None

    try:
        # Create poison mask directory
        poison_dir = target_dir / "poison_mask"
        poison_dir.mkdir(exist_ok=True)

        # Compute the poison mask
        mask_result = compute_mask(original, image)

        # Save mask images
        mask_hi_path = poison_dir / f"{stage_name}_mask_hi.png"
        mask_lo_path = poison_dir / f"{stage_name}_mask_lo.png"
        mask_result.hi_image.save(mask_hi_path)
        mask_result.lo_image.save(mask_lo_path)

        # Build metadata
        metadata = build_metadata(
            original_path=Path("original.png"),  # placeholder
            processed_path=Path("processed.png"),  # placeholder
            mask_hi_path=mask_hi_path,
            mask_lo_path=mask_lo_path,
            size=mask_result.size,
            diff_stats=mask_result.diff_stats,
            diff_min=mask_result.diff_min,
            diff_max=mask_result.diff_max,
            filter_id=config.poison_mask_filter_id,
            css_class=config.poison_mask_css_class,
        )

        # Save metadata
        metadata_path = poison_dir / f"{stage_name}_poison_metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

        return {
            "poison_mask_hi_path": str(mask_hi_path.resolve()),
            "poison_mask_lo_path": str(mask_lo_path.resolve()),
            "poison_metadata_path": str(metadata_path.resolve()),
            "diff_stats": mask_result.diff_stats,
        }

    except Exception as exc:
        print(f"Warning: Poison mask processing failed: {exc}")
        return None


def _generate_layer_mask_from_poison(
    mask_hi: Image.Image,
    mask_lo: Image.Image,
    amplification: float = 4.0
) -> Image.Image:
    """Generate visualization mask from poison mask hi/lo planes."""
    # Convert to grayscale if needed
    if mask_hi.mode != 'L':
        mask_hi = mask_hi.convert('L')
    if mask_lo.mode != 'L':
        mask_lo = mask_lo.convert('L')

    hi_arr = np.asarray(mask_hi, dtype=np.uint16)
    lo_arr = np.asarray(mask_lo, dtype=np.uint16)

    # Reconstruct the encoded difference magnitude
    encoded = (hi_arr << 8) | lo_arr
    diff_magnitude = np.abs(encoded.astype(np.int32) - 32768)

    # Amplify for visualization and convert to grayscale
    amplified = np.clip(diff_magnitude * amplification / 128, 0, 255).astype(np.uint8)

    return Image.fromarray(amplified, 'L')


def _generate_layer_mask(previous: Image.Image, current: Image.Image, poison_mask_data: Optional[Dict[str, object]] = None) -> Image.Image:
    """Generate visualization mask, preferring poison mask data if available."""
    if poison_mask_data and POISON_MASK_AVAILABLE:
        try:
            # Use poison mask data for visualization
            hi_path = Path(poison_mask_data["poison_mask_hi_path"])
            lo_path = Path(poison_mask_data["poison_mask_lo_path"])

            with Image.open(hi_path) as hi_img, Image.open(lo_path) as lo_img:
                return _generate_layer_mask_from_poison(hi_img, lo_img)

        except Exception as exc:
            print(f"Warning: Failed to use poison mask for visualization, falling back to simple diff: {exc}")

    # Fallback to original method
    if previous.size != current.size:
        previous = previous.resize(current.size, resample=Image.Resampling.BICUBIC)
    prev_arr = np.asarray(previous.convert("RGB"), dtype=np.int16)
    curr_arr = np.asarray(current.convert("RGB"), dtype=np.int16)
    diff = np.abs(curr_arr - prev_arr)
    diff_max = diff.max(axis=2)
    amplified = np.clip(diff_max * 4, 0, 255).astype(np.uint8)
    mask = Image.fromarray(amplified)
    return mask if mask.mode == "L" else mask.convert("L")


DEFAULT_WORKFLOW_CONFIG = ProtectionWorkflowConfig()
PROTECTION_STAGES: Sequence[ProtectionStage] = tuple(_build_stage_sequence(DEFAULT_WORKFLOW_CONFIG))


PROJECT_CATALOGUE: Sequence[Dict[str, Optional[str]]] = (
    {"name": "Pillow", "stage": "runtime", "notes": "Used for all image decoding and outputs."},
    {"name": "imagehash", "stage": "analysis-imagehash", "notes": "Perceptual hashes computed via processor."},
    {"name": "Fawkes", "stage": "fawkes", "notes": "Applied synthetic cloaking perturbation."},
    {"name": "PhotoGuard", "stage": "photoguard", "notes": "Applied blur/edge blend to impede edits."},
    {"name": "Mist v2", "stage": "mist", "notes": "Applied colour/contrast perturbation layer."},
    {"name": "Nightshade (research code)", "stage": "nightshade", "notes": "Injected structured poisoning pattern."},
    {"name": "invisible-watermark", "stage": "invisible-watermark", "notes": "Embedded lightweight LSB watermark."},
    {"name": "Tree-Ring", "stage": "tree-ring", "notes": "Radial provenance watermark (optional)."},
    {"name": "Stegano (embed)", "stage": "stegano-embed", "notes": "Embedded hidden payload at export."},
    {"name": "Stegano (analysis)", "stage": "analysis-stegano", "notes": "Steganography reveal attempted via processor."},
    {"name": "Poison Mask Processor", "stage": "poison-mask", "notes": "High-fidelity reconstruction masks with JS snippets."},
    {"name": "CorruptEncoder", "stage": None, "notes": "Framework for poisoning encoders; not run per-image."},
    {"name": "SecMI", "stage": None, "notes": "Membership inference research code; not image-level."},
    {"name": "MIA-diffusion", "stage": None, "notes": "Diffusion membership inference pipeline; not run."},
    {"name": "pytineye", "stage": None, "notes": "API client requires key; skipped."},
    {"name": "hCaptcha-challenger", "stage": None, "notes": "Captcha solver is out-of-scope for image protection."},
    {"name": "c2pa-python", "stage": "c2pa-manifest", "notes": "Embedded AI training manifest with C2PA."},
)


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _save_image(image: Image.Image, destination: Path, fmt: Optional[str]) -> None:
    if fmt:
        image.save(destination, format=fmt)
    else:
        image.save(destination)


def _apply_layers(
    image_path: Path,
    target_dir: Path,
    config: ProtectionWorkflowConfig,
) -> List[Dict[str, object]]:
    original = Image.open(image_path)
    fmt = getattr(original, "format", None)
    rgb_image = original.convert("RGB")

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

    stage_sequence = _build_stage_sequence(config)
    current = working
    previous_saved = rgb_image
    for index, stage in enumerate(stage_sequence, start=1):
        layer_dir = layers_dir / f"{index:02d}-{stage.key}"
        _ensure_directory(layer_dir)
        current = stage.apply(current)
        saved_image = current
        if saved_image.size != original.size:
            saved_image = saved_image.resize(original.size, resample=Image.Resampling.BICUBIC)
        stage_path = layer_dir / image_path.name
        _save_image(saved_image, stage_path, fmt)

        # Apply poison mask processor if enabled
        poison_mask_data = _apply_poison_mask_if_enabled(
            image=saved_image,
            original=previous_saved,
            config=config,
            target_dir=target_dir,
            stage_name=f"{index:02d}-{stage.key}"
        )

        mask_filename = f"{image_path.stem}_{stage.key}_mask.png"
        mask_path = layer_dir / mask_filename
        mask_image = _generate_layer_mask(previous_saved, saved_image, poison_mask_data)
        mask_image.save(mask_path, format="PNG")

        stage_data = {
            "stage": stage.key,
            "description": stage.description,
            "path": str(stage_path.resolve()),
            "processing_size": list(current.size),
            "mask_path": str(mask_path.resolve()),
        }

        # Add poison mask data to stage info if available
        if poison_mask_data:
            stage_data.update(poison_mask_data)

        stages.append(stage_data)
        last_stage_path = stage_path
        previous_saved = saved_image.convert("RGB")

    if config.enable_c2pa_manifest:
        c2pa_dir = target_dir / "c2pa"
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
            mask_filename = f"{image_path.stem}_c2pa-manifest_mask.png"
            mask_path = c2pa_dir / mask_filename
            with Image.open(signed_path) as final_image:
                final_image.load()
                final_rgb = final_image.convert("RGB")
            mask_image = _generate_layer_mask(previous_saved, final_rgb)
            mask_image.save(mask_path, format="PNG")
            previous_saved = final_rgb
            last_stage_path = signed_path
            stages.append({
                "stage": "c2pa-manifest",
                "description": "Embedded C2PA AI training manifest and IPTC signal",
                "path": str(signed_path.resolve()),
                "processing_size": list(original.size),
                "mask_path": str(mask_path.resolve()),
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
            mask_filename = f"{image_path.stem}_c2pa-manifest_mask.png"
            mask_path = c2pa_dir / mask_filename
            try:
                with Image.open(fallback_path) as fallback_image:
                    fallback_image.load()
                    fallback_rgb = fallback_image.convert("RGB")
            except Exception:
                fallback_rgb = previous_saved
            mask_image = _generate_layer_mask(previous_saved, fallback_rgb)
            mask_image.save(mask_path, format="PNG")
            previous_saved = fallback_rgb
            stages.append({
                "stage": "c2pa-manifest",
                "description": "Attempted to embed C2PA manifest",
                "error": str(exc),
                "path": str(fallback_path),
                "processing_size": list(original.size),
                "mask_path": str(mask_path.resolve()),
                "artifact_dir": str(c2pa_dir.resolve()),
            })

    return stages


def _build_project_status(
    stage_records: Sequence[Dict[str, object]],
    analysis_records: Optional[Dict[str, object]],
) -> List[Dict[str, object]]:
    stage_index = {record["stage"]: record for record in stage_records}
    analysis_index = {}
    if analysis_records:
        for proc in analysis_records.get("processors", []):
            if isinstance(proc, dict):
                name = proc.get("name")
                if name:
                    analysis_index[name] = proc

    statuses: List[Dict[str, object]] = []
    for project in PROJECT_CATALOGUE:
        key = project.get("stage")
        record: Dict[str, object] = {
            "name": project["name"],
            "notes": project.get("notes"),
            "applied": False,
        }
        if key == "runtime":
            record.update({
                "applied": True,
                "evidence": "Pillow handled decoding/encoding for every layer.",
            })
        elif key and key.startswith("analysis-"):
            processor_name = key.split("-", 1)[1]
            proc_info = analysis_index.get(processor_name)
            if proc_info:
                record.update({
                    "applied": bool(proc_info.get("ok")),
                    "evidence": proc_info,
                })
            else:
                record["notes"] = (record.get("notes") or "") + " Processor unavailable."
        elif key == "poison-mask":
            # Check if any stage has poison mask data
            poison_applied = any(
                "poison_mask_hi_path" in stage_record
                for stage_record in stage_records
            )
            record.update({
                "applied": poison_applied,
                "evidence": "Poison mask files generated for protection stages." if poison_applied else None,
            })
        elif key and key in stage_index:
            stage_record = stage_index[key]
            applied = not stage_record.get("error")
            record.update({
                "applied": applied,
                "layer_path": stage_record.get("path"),
            })
            if stage_record.get("error"):
                record["error"] = stage_record["error"]
        else:
            record.setdefault("notes", project.get("notes"))
        statuses.append(record)
    return statuses


def run_full_workflow(
    input_dir: Path | str = Path("input"),
    output_root: Path | str = Path("outputs"),
    include_hash_analysis: bool = True,
    config: ProtectionWorkflowConfig | None = None,
) -> Dict[str, object]:
    """Execute hashing analysis and stacked protection layers for each input image."""
    extend_sys_path()
    input_dir = Path(input_dir)
    output_root = Path(output_root)
    workflow_config = config or ProtectionWorkflowConfig()

    if not input_dir.exists():
        raise FileNotFoundError(f"input directory not found: {input_dir}")

    outputs: List[Dict[str, object]] = []
    for image_path in sorted(p for p in input_dir.iterdir() if p.is_file()):
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

        stage_records = _apply_layers(image_path, target_dir, workflow_config)
        project_status = _build_project_status(stage_records, analysis_summary)

        summary = {
            "image": str(image_path.resolve()),
            "analysis": str((target_dir / "analysis.json").resolve()) if analysis_summary else None,
            "layers": stage_records,
            "projects": project_status,
        }
        summary_path = target_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="ascii")

        outputs.append({
            "image": str(image_path.resolve()),
            "output_dir": str(target_dir.resolve()),
            "summary": str(summary_path.resolve()),
        })

    return {"processed": outputs}


def main() -> None:
    result = run_full_workflow()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
