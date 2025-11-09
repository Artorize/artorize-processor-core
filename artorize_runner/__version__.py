"""Version information for artorize-processor-core."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict

__version__ = "0.1.0"

# Version metadata file path
VERSION_FILE = Path(__file__).parent.parent / ".version_metadata.json"


def get_version_info() -> Dict[str, str]:
    """
    Get version information including last update time.

    Returns:
        Dictionary with version, last_update, and git_commit
    """
    info = {
        "version": __version__,
        "last_update": "unknown",
        "git_commit": "unknown",
    }

    if VERSION_FILE.exists():
        try:
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                metadata = json.load(f)
                info.update(metadata)
        except (json.JSONDecodeError, OSError):
            pass

    return info


def update_version_metadata(git_commit: str) -> None:
    """
    Update version metadata file with current timestamp and git commit.

    Args:
        git_commit: Current git commit hash
    """
    metadata = {
        "version": __version__,
        "last_update": datetime.now().isoformat(),
        "git_commit": git_commit,
    }

    try:
        with open(VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, indent=2, fp=f)
    except OSError as e:
        # Silently fail if we can't write the file
        pass


def format_version_info() -> str:
    """
    Format version information as a human-readable string.

    Returns:
        Formatted version string
    """
    info = get_version_info()

    lines = [
        f"Artorize Processor Core v{info['version']}",
        f"Last Update: {info['last_update']}",
        f"Git Commit: {info['git_commit'][:8] if len(info['git_commit']) > 8 else info['git_commit']}",
    ]

    return "\n".join(lines)
