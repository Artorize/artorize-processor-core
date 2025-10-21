"""
DEPRECATED: TinEye processor removed due to pytineye dependency incompatibility with Python 3.12+

The pytineye library requires future==0.18.2, which depends on the 'imp' module that was removed in Python 3.12.
This processor is kept for reference but will always return unavailable.

To re-enable: pip install pytineye (only works with Python 3.11 or earlier)
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from ..core import BaseProcessor, ProcessorResult
from ..utils import load_image_bytes


class TinEyeProcessor(BaseProcessor):
    name = "tineye"
    description = "DEPRECATED: TinEye API processor (pytineye incompatible with Python 3.12+)"

    def __init__(self, max_results: int = 10):
        self.max_results = max_results

    def available(self) -> bool:
        # DEPRECATED: Always returns False due to pytineye Python 3.12+ incompatibility
        return False
        # Legacy code (commented out):
        # api_key = os.getenv("TINEYE_API_KEY")
        # if not api_key:
        #     return False
        # try:
        #     import pytineye  # noqa: F401
        #     from pytineye.api import TinEyeAPIRequest  # noqa: F401
        #     return True
        # except Exception:
        #     return False

    def run(self, image_path: str, context: Dict[str, Any]) -> ProcessorResult:
        api_key = os.getenv("TINEYE_API_KEY")
        if not api_key:
            return ProcessorResult(name=self.name, ok=False, error="TINEYE_API_KEY not set")

        try:
            from pytineye.api import TinEyeAPIRequest
        except Exception as e:
            return ProcessorResult(name=self.name, ok=False, error=f"import error: {e}")

        try:
            client = TinEyeAPIRequest(api_key=api_key)
            data = load_image_bytes(image_path)
            resp = client.search_data(data=data, limit=self.max_results)
            matches: List[Dict[str, Any]] = []
            for m in resp.matches[: self.max_results]:
                matches.append(
                    {
                        "image_url": m.image_url,
                        "domain": m.domain,
                        "score": m.score,
                        "width": m.width,
                        "height": m.height,
                        "filesize": m.filesize,
                        "format": m.format,
                        "backlinks": [
                            {"url": b.url, "backlink": b.backlink, "crawl_date": b.crawl_date}
                            for b in (m.backlinks or [])
                        ],
                    }
                )
            return ProcessorResult(name=self.name, ok=True, data={"count": len(matches), "matches": matches})
        except Exception as e:
            return ProcessorResult(name=self.name, ok=False, error=str(e))

