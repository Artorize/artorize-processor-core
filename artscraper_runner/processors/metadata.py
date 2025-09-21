from __future__ import annotations

from typing import Any, Dict

from ..core import BaseProcessor, ProcessorResult
from ..utils import pil_image_from_path


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

        return ProcessorResult(name=self.name, ok=True, data=info)

