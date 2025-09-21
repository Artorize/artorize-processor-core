from __future__ import annotations

import json
import os
import traceback
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ProcessorResult:
    name: str
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BaseProcessor:
    name: str = "base"
    description: str = ""

    def available(self) -> bool:
        return True

    def run(self, image_path: str, context: Dict[str, Any]) -> ProcessorResult:
        raise NotImplementedError


def safe_run(processor: BaseProcessor, image_path: str, context: Dict[str, Any]) -> ProcessorResult:
    try:
        if not processor.available():
            return ProcessorResult(name=processor.name, ok=False, error="processor not available")
        return processor.run(image_path, context)
    except Exception as e:
        return ProcessorResult(
            name=processor.name,
            ok=False,
            error=f"{e}\n" + traceback.format_exc(),
        )


def run_pipeline(image_path: str, processors: List[BaseProcessor]) -> Dict[str, Any]:
    results: List[ProcessorResult] = []
    ctx: Dict[str, Any] = {
        "cwd": os.getcwd(),
    }
    for p in processors:
        results.append(safe_run(p, image_path, ctx))

    summary = {
        "image_path": os.path.abspath(image_path),
        "processors": [asdict(r) for r in results],
    }
    return summary


def dumps_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False, default=str)

