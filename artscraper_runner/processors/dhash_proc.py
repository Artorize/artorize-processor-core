from __future__ import annotations

from typing import Any, Dict

from ..core import BaseProcessor, ProcessorResult
from ..utils import pil_image_from_path


class DHashProcessor(BaseProcessor):
    name = "dhash"
    description = "Computes Ben Hoyt's dhash (row/col) from the dhash module."

    def available(self) -> bool:
        try:
            import dhash  # type: ignore  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, image_path: str, context: Dict[str, Any]) -> ProcessorResult:
        try:
            import dhash as _dhash
        except Exception as e:
            return ProcessorResult(name=self.name, ok=False, error=f"import error: {e}")

        im = pil_image_from_path(image_path)
        if im is None:
            return ProcessorResult(name=self.name, ok=False, error="unable to open image")

        try:
            row, col = _dhash.dhash_row_col(im)
            data: Dict[str, Any] = {
                "row_hash": row,
                "col_hash": col,
                "hex": _dhash.format_hex(row, col),
            }
            return ProcessorResult(name=self.name, ok=True, data=data)
        except Exception as e:
            return ProcessorResult(name=self.name, ok=False, error=str(e))

