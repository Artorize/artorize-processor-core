from __future__ import annotations

from typing import Any, Dict

from ..core import BaseProcessor, ProcessorResult
from ..utils import pil_image_from_path, ensure_rgb


class BlockHashProcessor(BaseProcessor):
    name = "blockhash"
    description = "Computes blockhash (BMVbIPH) via the blockhash package."

    def available(self) -> bool:
        try:
            import blockhash  # type: ignore  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, image_path: str, context: Dict[str, Any]) -> ProcessorResult:
        try:
            import blockhash as bh
        except Exception as e:
            return ProcessorResult(name=self.name, ok=False, error=f"import error: {e}")

        im = pil_image_from_path(image_path)
        if im is None:
            return ProcessorResult(name=self.name, ok=False, error="unable to open image")

        im = ensure_rgb(im)
        if im is None:
            return ProcessorResult(name=self.name, ok=False, error="unable to normalize mode")

        try:
            h16 = bh.blockhash(im, 16)
            h8 = bh.blockhash(im, 8)
            data: Dict[str, Any] = {"bits16": h16, "bits8": h8}
            return ProcessorResult(name=self.name, ok=True, data=data)
        except Exception as e:
            return ProcessorResult(name=self.name, ok=False, error=str(e))


