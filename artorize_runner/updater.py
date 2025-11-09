"""Self-update functionality for artorize-processor-core."""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Tuple

from .__version__ import update_version_metadata

logger = logging.getLogger(__name__)

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def get_current_commit() -> str:
    """
    Get the current git commit hash.

    Returns:
        Git commit hash or 'unknown' if not in a git repo
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return "unknown"


def get_current_branch() -> str:
    """
    Get the current git branch name.

    Returns:
        Branch name or 'unknown' if not in a git repo
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return "unknown"


def check_for_updates() -> Tuple[bool, str]:
    """
    Check if updates are available from the remote repository.

    Returns:
        Tuple of (updates_available, message)
    """
    try:
        # Fetch latest changes from remote
        logger.info("Checking for updates...")
        result = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return False, f"Failed to fetch updates: {result.stderr}"

        # Check if local is behind remote
        current_branch = get_current_branch()
        if current_branch == "unknown":
            return False, "Not in a git repository"

        result = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..origin/{current_branch}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return False, f"Failed to check for updates: {result.stderr}"

        commits_behind = int(result.stdout.strip())
        if commits_behind > 0:
            return True, f"{commits_behind} update(s) available"
        else:
            return False, "Already up to date"

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError) as e:
        return False, f"Error checking for updates: {str(e)}"


def perform_update() -> Tuple[bool, str]:
    """
    Pull latest changes from the remote repository.

    Returns:
        Tuple of (success, message)
    """
    try:
        current_branch = get_current_branch()
        if current_branch == "unknown":
            return False, "Not in a git repository"

        logger.info(f"Pulling updates from origin/{current_branch}...")

        # Pull with retry logic (exponential backoff)
        max_retries = 4
        retry_delays = [2, 4, 8, 16]  # seconds

        for attempt in range(max_retries):
            result = subprocess.run(
                ["git", "pull", "origin", current_branch],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                # Update successful
                new_commit = get_current_commit()
                update_version_metadata(new_commit)
                logger.info("Update completed successfully")
                return True, f"Updated to commit {new_commit[:8]}"

            # Check if it's a network error
            if "network" in result.stderr.lower() or "timeout" in result.stderr.lower():
                if attempt < max_retries - 1:
                    import time
                    delay = retry_delays[attempt]
                    logger.warning(f"Network error, retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue

            # Non-network error or final retry failed
            return False, f"Failed to update: {result.stderr}"

        return False, "Failed to update after multiple retries"

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, f"Error during update: {str(e)}"


def auto_update(force: bool = False) -> None:
    """
    Automatically check for and apply updates.

    Args:
        force: If True, always pull updates without checking
    """
    if force:
        success, message = perform_update()
        if success:
            logger.info(message)
        else:
            logger.warning(message)
        return

    # Check if updates are available
    updates_available, message = check_for_updates()

    if updates_available:
        logger.info(message)
        success, update_message = perform_update()
        if success:
            logger.info(update_message)
            logger.info("Restart may be required for changes to take effect")
        else:
            logger.warning(update_message)
    else:
        logger.debug(message)

    # Update metadata even if no updates were applied
    current_commit = get_current_commit()
    update_version_metadata(current_commit)
