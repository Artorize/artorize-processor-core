from __future__ import annotations

from typing import Any, Dict

from ..core import BaseProcessor, ProcessorResult
from ..utils import pil_image_from_path


def _make_json_serializable(obj: Any) -> Any:
    """
    Recursively convert non-JSON-serializable objects to serializable types.

    Handles:
    - IFDRational: Convert to float
    - bytes: Convert to string (decode UTF-8 or hex representation)
    - dict: Recursively process values
    - list/tuple: Recursively process elements
    """
    try:
        from PIL.TiffImagePlugin import IFDRational
        if isinstance(obj, IFDRational):
            # Convert rational to float
            return float(obj)
    except ImportError:
        pass

    if isinstance(obj, bytes):
        # Try UTF-8 decode, fallback to hex representation
        try:
            return obj.decode('utf-8')
        except UnicodeDecodeError:
            return obj.hex()

    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]

    # Return as-is for JSON-compatible types (str, int, float, bool, None)
    return obj


class MetadataProcessor(BaseProcessor):
    name = "metadata"
    description = "Extracts basic image metadata and EXIF tags."

    def available(self) -> bool:
        try:
            import PIL  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, image_path: str, context: Dict[str, Any]) -> ProcessorResult:
        im = pil_image_from_path(image_path)
        if im is None:
            return ProcessorResult(name=self.name, ok=False, error="unable to open image")
        info: Dict[str, Any] = {
            "format": getattr(im, "format", None),
            "size": getattr(im, "size", None),
            "mode": getattr(im, "mode", None),
        }
        # EXIF
        try:
            exif = getattr(im, "_getexif", None)
            if callable(exif):
                raw = exif() or {}
                # Best-effort decode EXIF tags
                try:
                    from PIL.ExifTags import TAGS
                    exif_decoded = {TAGS.get(k, k): v for k, v in raw.items()}
                except Exception:
                    exif_decoded = raw
                info["exif"] = exif_decoded
        except Exception:
            pass

        # Convert all non-JSON-serializable values to serializable types
        info = _make_json_serializable(info)

        return ProcessorResult(name=self.name, ok=True, data=info)

