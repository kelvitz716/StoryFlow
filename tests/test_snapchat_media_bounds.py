"""Tests for H5: Snapchat media bounds, safe get, and username validation."""

import os
import pytest
from unittest.mock import MagicMock, patch

from core.platform import extract_snapchat_username
from downloaders.snapchat import SnapchatDownloader, _safe_get, _ALLOWED_MEDIA_HOST_SUFFIXES


@pytest.mark.parametrize("invalid_user", [
    "../x",
    "a b",
    "a" * 40,
    "user@name",
    "/etc/passwd",
    "!",
    "",
])
def test_invalid_usernames_return_none(invalid_user):
    """Invalid usernames (../x, a b, 40 chars, etc.) return None."""
    url = f"https://www.snapchat.com/add/{invalid_user}"
    assert extract_snapchat_username(url) is None

    url_at = f"https://www.snapchat.com/@{invalid_user}"
    assert extract_snapchat_username(url_at) is None


@pytest.mark.parametrize("valid_user", [
    "valid_user-123.test",
    "snapchatter",
    "a",
    "a" * 32,
])
def test_valid_usernames_succeed(valid_user):
    """Valid usernames conforming to ^[A-Za-z0-9._-]{1,32}$ return the username."""
    url = f"https://www.snapchat.com/add/{valid_user}"
    assert extract_snapchat_username(url) == valid_user


def test_host_not_in_allowlist_no_request_made(tmp_path):
    """Host not in the allowlist results in no HTTP request made and nothing written."""
    dl = SnapchatDownloader(output_path=str(tmp_path))
    dl.session = MagicMock()

    url = "https://unauthorized-cdn.com/media.mp4"
    res = dl._download_media(url, "validuser", 1, 1, "123456", str(tmp_path))

    assert res is None
    assert dl.session.get.call_count == 0
    assert len(list(tmp_path.iterdir())) == 0


def test_redirect_to_private_ip_blocked_nothing_written(tmp_path):
    """Redirect to 127.0.0.1 or a private IP is blocked and nothing is written."""
    dl = SnapchatDownloader(output_path=str(tmp_path))
    mock_session = MagicMock()
    dl.session = mock_session

    redirect_resp = MagicMock()
    redirect_resp.is_redirect = True
    redirect_resp.status_code = 302
    redirect_resp.headers = {"Location": "https://127.0.0.1/evil.mp4"}

    mock_session.get.return_value = redirect_resp

    with patch("downloaders.snapchat.is_safe_url", side_effect=lambda u: "127.0.0.1" not in u):
        res = dl._download_media("https://cf-st.sc-cdn.net/initial", "validuser", 1, 1, "123456", str(tmp_path))
        assert res is None
        # Only initial request made; redirect target was blocked
        assert mock_session.get.call_count == 1
        assert len(list(tmp_path.iterdir())) == 0


def test_stream_exceeding_cap_aborted_and_partial_file_deleted(tmp_path, monkeypatch):
    """Stream exceeding the size cap is aborted and the partial file deleted."""
    import downloaders.snapchat as sc_module
    monkeypatch.setattr(sc_module, "_MAX_FILE_SIZE_MB", 1)

    dl = sc_module.SnapchatDownloader(output_path=str(tmp_path))
    mock_session = MagicMock()
    dl.session = mock_session

    stream_resp = MagicMock()
    stream_resp.is_redirect = False
    stream_resp.status_code = 200
    stream_resp.headers = {}
    # Yield 3 chunks of 512KB = 1.5MB (exceeding 1MB limit)
    stream_resp.iter_content.return_value = [b"x" * (512 * 1024), b"y" * (512 * 1024), b"z" * (512 * 1024)]

    with patch("downloaders.snapchat.is_safe_url", return_value=True):
        mock_session.get.return_value = stream_resp
        res = dl._download_media("https://cf-st.sc-cdn.net/video.mp4", "validuser", 1, 1, "123456", str(tmp_path))
        assert res is None
        assert len(list(tmp_path.iterdir())) == 0
        stream_resp.close.assert_called()


def test_oversized_content_length_nothing_written(tmp_path, monkeypatch):
    """Oversized Content-Length causes early rejection without writing any file."""
    import downloaders.snapchat as sc_module
    monkeypatch.setattr(sc_module, "_MAX_FILE_SIZE_MB", 500)

    dl = sc_module.SnapchatDownloader(output_path=str(tmp_path))
    mock_session = MagicMock()
    dl.session = mock_session

    resp = MagicMock()
    resp.is_redirect = False
    resp.status_code = 200
    # 600 MB exceeds 500 MB limit
    resp.headers = {"Content-Length": str(600 * 1024 * 1024)}

    with patch("downloaders.snapchat.is_safe_url", return_value=True):
        mock_session.get.return_value = resp
        res = dl._download_media("https://cf-st.sc-cdn.net/video.mp4", "validuser", 1, 1, "123456", str(tmp_path))
        assert res is None
        assert len(list(tmp_path.iterdir())) == 0
        resp.close.assert_called()


def test_disk_critical_file_skipped(tmp_path):
    """When disk is critical, download is skipped without making requests."""
    dl = SnapchatDownloader(output_path=str(tmp_path))
    dl.session = MagicMock()

    with patch("downloaders.snapchat.is_storage_critical", return_value=(True, 95.0)):
        res = dl._download_media("https://cf-st.sc-cdn.net/video.mp4", "validuser", 1, 1, "123456", str(tmp_path))
        assert res is None
        assert dl.session.get.call_count == 0
        assert len(list(tmp_path.iterdir())) == 0


# ---------------------------------------------------------------------------
# G4: Snapchat stops at item cap and at byte cap
# ---------------------------------------------------------------------------

def test_snapchat_stops_at_item_cap(tmp_path, monkeypatch):
    """Snapchat download loop stops once MAX_FILES_PER_JOB items are downloaded."""
    import downloaders.snapchat as sc_module
    monkeypatch.setattr(sc_module, "_MAX_FILES_PER_JOB", 2)
    monkeypatch.setattr(sc_module, "_MAX_JOB_SIZE_MB", 100)

    dl = sc_module.SnapchatDownloader(output_path=str(tmp_path))
    items = [
        {"mediaUrl": "https://cf-st.sc-cdn.net/1.jpg", "mediaType": 0, "timestamp": "1"},
        {"mediaUrl": "https://cf-st.sc-cdn.net/2.jpg", "mediaType": 0, "timestamp": "2"},
        {"mediaUrl": "https://cf-st.sc-cdn.net/3.jpg", "mediaType": 0, "timestamp": "3"},
        {"mediaUrl": "https://cf-st.sc-cdn.net/4.jpg", "mediaType": 0, "timestamp": "4"},
    ]

    dl._scrape_page = MagicMock(return_value=items)
    # Mock _download_media to return dummy file path and write a small file
    def _fake_download(media_url, username, index, media_type, timestamp, output_path):
        fpath = os.path.join(output_path, f"snap_{index}.jpg")
        with open(fpath, "wb") as f:
            f.write(b"img")
        return fpath

    dl._download_media = MagicMock(side_effect=_fake_download)

    res = dl._download_stories("testuser", job_id="job123", mode="stories")

    assert res["success"] is True
    assert res.get("limit_reached") is True
    assert len(res["files"]) == 2
    assert dl._download_media.call_count == 2


def test_snapchat_stops_at_byte_cap(tmp_path, monkeypatch):
    """Snapchat download loop stops once cumulative downloaded bytes reach MAX_JOB_SIZE_MB."""
    import downloaders.snapchat as sc_module
    # Set limit to 1 MB
    monkeypatch.setattr(sc_module, "_MAX_JOB_SIZE_MB", 1)
    monkeypatch.setattr(sc_module, "_MAX_FILES_PER_JOB", 100)

    dl = sc_module.SnapchatDownloader(output_path=str(tmp_path))
    items = [
        {"mediaUrl": "https://cf-st.sc-cdn.net/1.mp4", "mediaType": 1, "timestamp": "1"},
        {"mediaUrl": "https://cf-st.sc-cdn.net/2.mp4", "mediaType": 1, "timestamp": "2"},
        {"mediaUrl": "https://cf-st.sc-cdn.net/3.mp4", "mediaType": 1, "timestamp": "3"},
    ]

    dl._scrape_page = MagicMock(return_value=items)
    # Each download writes 600 KB -> first is 600 KB, second is 1.2 MB (exceeds 1 MB)
    def _fake_download(media_url, username, index, media_type, timestamp, output_path):
        fpath = os.path.join(output_path, f"snap_{index}.mp4")
        with open(fpath, "wb") as f:
            f.write(b"M" * 600 * 1024)
        return fpath

    dl._download_media = MagicMock(side_effect=_fake_download)

    res = dl._download_stories("testuser", job_id="job123", mode="stories")

    assert res["success"] is True
    assert res.get("limit_reached") is True
    assert len(res["files"]) == 2
    assert dl._download_media.call_count == 2
