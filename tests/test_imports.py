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

    # Verify no apify_token in __init__ parameters
    sig = inspect.signature(SnapchatDownloader.__init__)
    assert "apify_token" not in sig.parameters


def test_telegram_bot_no_apify_token_param():
    """Verify run_telegram_bot does not accept apify_token."""
    import inspect
    from bot.telegram_bot import run_telegram_bot
    sig = inspect.signature(run_telegram_bot)
    assert "apify_token" not in sig.parameters


def test_env_example_has_max_requests_and_no_apify():
    """Verify .env.example contains MAX_REQUESTS_PER_MINUTE and no APIFY_TOKEN."""
    with open(".env.example", "r") as f:
        content = f.read()
    assert "MAX_REQUESTS_PER_MINUTE" in content
    assert "APIFY_TOKEN" not in content

