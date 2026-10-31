"""Tests for Snapchat URL shape validation and username extraction."""

import pytest
from core.platform import extract_snapchat_username, _valid_snapchat_username


@pytest.mark.parametrize(
    "url,expected",
    [
        # /add/user
        ("https://snapchat.com/add/user", "user"),
        ("https://www.snapchat.com/add/user", "user"),
        ("https://snapchat.com/add/user/", "user"),
        ("https://www.snapchat.com/add/user/", "user"),
        ("https://snapchat.com/add/user?share_id=abc&locale=en-US", "user"),
        ("https://www.snapchat.com/add/user/?share_id=abc&locale=en-US", "user"),

        # /add/user/l
        ("https://snapchat.com/add/user/l", "user"),
        ("https://www.snapchat.com/add/user/l", "user"),
        ("https://snapchat.com/add/user/l/", "user"),
        ("https://snapchat.com/add/user/l?share_id=abc&locale=en-US", "user"),

        # /stories/user
        ("https://snapchat.com/stories/user", "user"),
        ("https://www.snapchat.com/stories/user", "user"),
        ("https://snapchat.com/stories/user/", "user"),
        ("https://snapchat.com/stories/user?share_id=abc&locale=en-US", "user"),

        # /spotlight/user
        ("https://snapchat.com/spotlight/user", "user"),
        ("https://www.snapchat.com/spotlight/user", "user"),
        ("https://snapchat.com/spotlight/user/", "user"),
        ("https://snapchat.com/spotlight/user?share_id=abc&locale=en-US", "user"),

        # /highlight/user
        ("https://snapchat.com/highlight/user", "user"),
        ("https://www.snapchat.com/highlight/user", "user"),
        ("https://snapchat.com/highlight/user/", "user"),
        ("https://snapchat.com/highlight/user?share_id=abc&locale=en-US", "user"),

        # /highlights/user
        ("https://snapchat.com/highlights/user", "user"),
        ("https://www.snapchat.com/highlights/user", "user"),
        ("https://snapchat.com/highlights/user/", "user"),
        ("https://snapchat.com/highlights/user?share_id=abc&locale=en-US", "user"),

        # /@user
        ("https://snapchat.com/@user", "user"),
        ("https://www.snapchat.com/@user", "user"),
        ("https://snapchat.com/@user/", "user"),
        ("https://snapchat.com/@user?share_id=abc&locale=en-US", "user"),
    ],
)
def test_valid_snapchat_url_shapes(url, expected):
    assert extract_snapchat_username(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://snapchat.com/add/../x",
        "https://snapchat.com/add/user with space",
        f"https://snapchat.com/add/{'a' * 33}",
        "https://snapchat.com/add/user/extra",
        "https://snapchat.com/add/..",
        "https://snapchat.com/add/.",
        "https://snapchat.com/add/",
        "https://snapchat.com/stories/user/extra/parts",
        "https://snapchat.com/@..",
        "https://snapchat.com/@.",
        "https://snapchat.com/@a b",
    ],
)
def test_rejected_snapchat_url_shapes(url):
    assert extract_snapchat_username(url) is None


@pytest.mark.parametrize(
    "name,is_valid",
    [
        ("valid_user-123.test", True),
        ("a", True),
        ("a" * 32, True),
        (".", False),
        ("..", False),
        ("...", True),
        ("a" * 33, False),
        ("invalid user", False),
        ("user@name", False),
        ("", False),
    ],
)
def test_valid_snapchat_username_helper(name, is_valid):
    assert _valid_snapchat_username(name) is is_valid
