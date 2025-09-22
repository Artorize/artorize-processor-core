from __future__ import annotations

from typing import Any, Dict

from ..core import BaseProcessor, ProcessorResult
from ..utils import pil_image_from_path


class ImageHashesProcessor(BaseProcessor):
    name = "imagehash"
    description = "Computes a/pha/d/whash via the imagehash package."

    def available(self) -> bool:
        try:
            import imagehash  # type: ignore  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, image_path: str, context: Dict[str, Any]) -> ProcessorResult:
        try:
            import imagehash
        except Exception as e:
            return ProcessorResult(name=self.name, ok=False, error=f"import error: {e}")

        im = pil_image_from_path(image_path)
        if im is None:
            return ProcessorResult(name=self.name, ok=False, error="unable to open image")

        data: Dict[str, Any] = {}
        try:
            data["ahash"] = str(imagehash.average_hash(im))
        except Exception:
            pass
        try:
            data["phash"] = str(imagehash.phash(im))
        except Exception:
            pass
        try:
            data["dhash"] = str(imagehash.dhash(im))
        except Exception:
            pass
        try:
            data["whash-haar"] = str(imagehash.whash(im))
        except Exception:
            pass

        if not data:
            return ProcessorResult(name=self.name, ok=False, error="no hashes computed")
        return ProcessorResult(name=self.name, ok=True, data=data)


