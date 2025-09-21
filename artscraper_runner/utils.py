import io
import os
import sys
from typing import Optional, Tuple


# Ensure repo-local packages remain importable when running from source

def extend_sys_path(repo_root: Optional[str] = None) -> None:
    root = repo_root or os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    processors_dir = os.path.join(root, "processors")
    if os.path.isdir(processors_dir) and processors_dir not in sys.path:
        sys.path.insert(0, processors_dir)


def load_image_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def pil_image_from_path(path: str):
    try:
        from PIL import Image
    except Exception:
        return None

    try:
        im = Image.open(path)
        # Defer actual loading; call load to force decode for downstream consistency
        im.load()
        return im
    except Exception:
        # Try RAW handling if rawpy is available
        try:
            import rawpy  # type: ignore
            import numpy as np  # type: ignore
            data = rawpy.imread(path)
            rgb = data.postprocess()
            im = Image.fromarray(rgb)
            return im
        except Exception:
            return None


def ensure_rgb(im) -> Optional[object]:
    try:
        if getattr(im, "mode", None) in ("1", "L", "P"):
            return im.convert("RGB")
        if getattr(im, "mode", None) == "LA":
            return im.convert("RGBA")
        return im
    except Exception:
        return None
