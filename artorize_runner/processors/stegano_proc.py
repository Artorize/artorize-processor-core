from __future__ import annotations

from typing import Any, Dict

from ..core import BaseProcessor, ProcessorResult


class SteganoProcessor(BaseProcessor):
    name = "stegano"
    description = "Attempts simple LSB steganography reveal using Stegano."

    def available(self) -> bool:
        try:
            import stegano  # type: ignore  # noqa: F401
            from stegano import lsb  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, image_path: str, context: Dict[str, Any]) -> ProcessorResult:
        try:
            from stegano import lsb
        except Exception as e:
            return ProcessorResult(name=self.name, ok=False, error=f"import error: {e}")

        try:
            hidden = lsb.reveal(image_path)
            found = hidden is not None
            snippet = None
            if found:
                text = str(hidden)
                snippet = text[:200]
            return ProcessorResult(name=self.name, ok=True, data={"found": found, "preview": snippet})
        except Exception as e:
            # Commonly fails for non-LSB-encoded images; treat as not found
            return ProcessorResult(name=self.name, ok=True, data={"found": False, "error": str(e)})

