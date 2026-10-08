"""Tests verifying storyflow and downloader imports."""

import importlib


def test_import_storyflow():
    """Verify that storyflow module imports cleanly without missing symbols."""
    mod = importlib.import_module("storyflow")
    assert mod is not None


def test_import_snapchat_downloader():
    """Verify SnapchatDownloader imports and can be instantiated/inspected."""
    from downloaders.snapchat import SnapchatDownloader
    dl = SnapchatDownloader(output_path="./downloads")
    assert dl is not None
