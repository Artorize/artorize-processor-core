"""Tests for version and updater functionality."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from artorize_runner.__version__ import (
    __version__,
    get_version_info,
    update_version_metadata,
    format_version_info,
    VERSION_FILE,
)
from artorize_runner.updater import (
    get_current_commit,
    get_current_branch,
)


def test_version_defined():
    """Test that version is defined."""
    assert __version__ is not None
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_get_version_info_no_metadata():
    """Test get_version_info when metadata file doesn't exist."""
    # Remove metadata file if it exists
    if VERSION_FILE.exists():
        VERSION_FILE.unlink()

    info = get_version_info()
    assert info["version"] == __version__
    assert info["last_update"] == "unknown"
    assert info["git_commit"] == "unknown"


def test_update_version_metadata():
    """Test updating version metadata."""
    test_commit = "abc123def456"

    # Update metadata
    update_version_metadata(test_commit)

    # Verify file was created
    assert VERSION_FILE.exists()

    # Verify contents
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    assert metadata["version"] == __version__
    assert metadata["git_commit"] == test_commit
    assert "last_update" in metadata
    assert metadata["last_update"] != "unknown"

    # Clean up
    VERSION_FILE.unlink()


def test_format_version_info():
    """Test formatting version info."""
    # Create test metadata
    test_commit = "test123abc"
    update_version_metadata(test_commit)

    # Format and verify
    formatted = format_version_info()
    assert "Artorize Processor Core" in formatted
    assert __version__ in formatted
    assert "Last Update:" in formatted
    assert "Git Commit:" in formatted

    # Clean up
    if VERSION_FILE.exists():
        VERSION_FILE.unlink()


def test_get_current_commit():
    """Test getting current git commit."""
    commit = get_current_commit()
    # Should return either a valid commit hash or 'unknown'
    assert commit is not None
    assert isinstance(commit, str)
    if commit != "unknown":
        # Valid commit hash should be 40 characters
        assert len(commit) == 40


def test_get_current_branch():
    """Test getting current git branch."""
    branch = get_current_branch()
    # Should return either a valid branch name or 'unknown'
    assert branch is not None
    assert isinstance(branch, str)
    # Branch name should not be empty if valid
    if branch != "unknown":
        assert len(branch) > 0
