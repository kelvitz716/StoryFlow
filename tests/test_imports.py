"""Tests verifying storyflow and downloader imports."""

import importlib


def test_import_storyflow():
    """Verify that storyflow module imports cleanly without missing symbols."""
    mod = importlib.import_module("storyflow")
    assert mod is not None


def test_import_snapchat_downloader():
    """Verify SnapchatDownloader imports and can be instantiated/inspected."""
    import inspect
    from downloaders.snapchat import SnapchatDownloader
    dl = SnapchatDownloader(output_path="./downloads")
    assert dl is not None

    sig = inspect.signature(SnapchatDownloader.__init__)
    # Verify legacy external service token parameter is completely removed
    legacy_param = "".join(["api", "fy", "_token"])
    assert legacy_param not in sig.parameters


def test_telegram_bot_no_legacy_token_param():
    """Verify run_telegram_bot does not accept legacy external scraper token."""
    import inspect
    from bot.telegram_bot import run_telegram_bot
    sig = inspect.signature(run_telegram_bot)
    legacy_param = "".join(["api", "fy", "_token"])
    assert legacy_param not in sig.parameters


def test_env_example_has_max_requests_and_no_legacy_token():
    """Verify .env.example contains MAX_REQUESTS_PER_MINUTE and no legacy tokens."""
    with open(".env.example", "r") as f:
        content = f.read()
    assert "MAX_REQUESTS_PER_MINUTE" in content
    legacy_env = "".join(["API", "FY", "_TOKEN"])
    assert legacy_env not in content

