"""
Tests for multi-site platform identification and routing (gallery-dl + yt-dlp).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.platform import (
    identify_platform,
    YTDLP_DIRECT_PLATFORMS,
    _GALLERY_DL_DOMAINS,
    _YTDLP_DOMAINS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_safe(url: str, safe: bool = True):
    """Patch is_safe_url to return a fixed value."""
    return patch("core.platform.is_safe_url", return_value=safe)

def _mock_safe_and_validate(url: str):
    """Patch both is_safe_url and validate_domain for clean unit tests."""
    def _validate(u, domains):
        from urllib.parse import urlparse
        host = (urlparse(u).hostname or "").removeprefix("www.")
        return any(host == d or host.endswith("." + d) for d in domains)

    return patch("core.platform.is_safe_url", return_value=True), \
           patch("core.platform.validate_domain", side_effect=_validate)


# ---------------------------------------------------------------------------
# Existing platforms must not be changed
# ---------------------------------------------------------------------------

class TestExistingPlatformsUnchanged:
    """The five original platforms must still resolve to the same names."""

    @pytest.mark.parametrize("url,expected", [
        ("https://snapchat.com/add/test", "Snapchat"),
        ("https://www.snapchat.com/stories/foo", "Snapchat"),
        ("https://instagram.com/p/abc123", "Instagram"),
        ("https://www.instagram.com/stories/foo/", "Instagram"),
        ("https://tiktok.com/@user/video/123", "TikTok"),
        ("https://vm.tiktok.com/abc", "TikTok"),
        ("https://twitter.com/user/status/1", "Twitter"),
        ("https://x.com/user/status/1", "Twitter"),
        ("https://facebook.com/photo/123", "Facebook"),
        ("https://fb.watch/abc", "Facebook"),
    ])
    def test_named_platforms_unchanged(self, url, expected):
        with patch("core.platform.is_safe_url", return_value=True):
            assert identify_platform(url) == expected


# ---------------------------------------------------------------------------
# gallery-dl known domains → correct name
# ---------------------------------------------------------------------------

class TestGalleryDLDomains:

    @pytest.mark.parametrize("url,expected_name", [
        ("https://www.deviantart.com/user/gallery", "DeviantArt"),
        ("https://www.artstation.com/artwork/abc", "ArtStation"),
        ("https://www.flickr.com/photos/user/", "Flickr"),
        ("https://500px.com/photo/123", "500px"),
        ("https://www.newgrounds.com/art/view/x/y", "Newgrounds"),
        ("https://bsky.app/profile/user.bsky.social", "Bluesky"),
        ("https://www.behance.net/gallery/123/Title", "Behance"),
        ("https://www.bilibili.com/read/cv123", "Bilibili"),
        ("https://danbooru.donmai.us/posts/123", "Danbooru"),
        ("https://e621.net/posts?tags=fox", "e621"),
        ("https://imgur.com/gallery/abc", "Imgur"),
        ("https://i.imgur.com/abc.jpg", "Imgur"),
        ("https://www.redgifs.com/watch/abc", "RedGIFs"),
        ("https://www.tumblr.com/user/post/123", "Tumblr"),
        ("https://www.pixiv.net/artworks/123", "Pixiv"),
        ("https://www.reddit.com/r/pics/comments/abc/", "Reddit"),  # reddit in _YTDLP
        ("https://soundcloud.com/artist/track", "SoundCloud"),  # soundcloud in _YTDLP
        ("https://www.xvideos.com/video123", "XVideos"),
        ("https://xhamster.com/videos/abc", "xHamster"),
        ("https://www.unsplash.com/photos/abc", "Unsplash"),
        ("https://pexels.com/photo/abc-123", "Pexels"),
        ("https://mangadex.org/chapter/abc/1", "MangaDex"),
        ("https://www.webtoons.com/en/action/test/episode-1/viewer", "WEBTOON"),
    ])
    def test_gallery_dl_domains_resolved(self, url, expected_name):
        with patch("core.platform.is_safe_url", return_value=True):
            result = identify_platform(url)
            assert result == expected_name, (
                f"URL {url!r} → got {result!r}, expected {expected_name!r}"
            )


# ---------------------------------------------------------------------------
# yt-dlp primary domains → correct name
# ---------------------------------------------------------------------------

class TestYtdlpDomains:

    @pytest.mark.parametrize("url,expected_name", [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "YouTube"),
        ("https://youtu.be/dQw4w9WgXcQ", "YouTube"),
        ("https://music.youtube.com/watch?v=abc", "YouTube Music"),
        ("https://vimeo.com/123456789", "Vimeo"),
        ("https://www.twitch.tv/channelname", "Twitch"),
        ("https://clips.twitch.tv/ClipName", "Twitch"),
        ("https://www.dailymotion.com/video/x123", "Dailymotion"),
        ("https://dai.ly/x123", "Dailymotion"),
        ("https://soundcloud.com/artist/track", "SoundCloud"),
        ("https://on.soundcloud.com/abc", "SoundCloud"),
        ("https://bandcamp.com", "Bandcamp"),
        ("https://rumble.com/v-abc.html", "Rumble"),
        ("https://kick.com/channel", "Kick"),
        ("https://streamable.com/abc", "Streamable"),
        ("https://www.nicovideo.jp/watch/sm12345", "Niconico"),
        ("https://crunchyroll.com/en/watch/abc", "Crunchyroll"),
        ("https://old.reddit.com/r/videos/comments/abc/", "Reddit"),
        ("https://v.redd.it/abc123", "Reddit"),
        ("https://odysee.com/@channel:5/video:4", "Odysee"),
    ])
    def test_ytdlp_domains_resolved(self, url, expected_name):
        with patch("core.platform.is_safe_url", return_value=True):
            result = identify_platform(url)
            assert result == expected_name, (
                f"URL {url!r} → got {result!r}, expected {expected_name!r}"
            )

    def test_all_ytdlp_domains_in_direct_platforms_set(self):
        """Every value in _YTDLP_DOMAINS must appear in YTDLP_DIRECT_PLATFORMS."""
        for domain, name in _YTDLP_DOMAINS.items():
            assert name in YTDLP_DIRECT_PLATFORMS, (
                f"{domain!r} → {name!r} is missing from YTDLP_DIRECT_PLATFORMS"
            )


# ---------------------------------------------------------------------------
# Unknown / unsafe URLs still return correct sentinel
# ---------------------------------------------------------------------------

class TestFallbackAndUnknown:

    def test_unknown_domain_returns_generic(self):
        """A random publicly-routable domain returns 'Generic', not 'Unknown'."""
        with patch("core.platform.is_safe_url", return_value=True):
            result = identify_platform("https://some-random-site-xyz.example.com/page")
            assert result == "Generic"

    def test_unsafe_url_returns_unknown(self):
        """Any URL that fails is_safe_url is 'Unknown' regardless of hostname."""
        with patch("core.platform.is_safe_url", return_value=False):
            assert identify_platform("https://youtube.com/watch?v=abc") == "Unknown"

    def test_private_ip_returns_unknown(self):
        """192.168.x.x resolves to Unknown without mocking (real SSRF check)."""
        result = identify_platform("http://192.168.1.1/admin")
        assert result == "Unknown"

    def test_localhost_returns_unknown(self):
        result = identify_platform("http://localhost:8096/web")
        assert result == "Unknown"

    def test_tailscale_ip_returns_unknown(self):
        result = identify_platform("http://100.64.0.1/")
        assert result == "Unknown"


# ---------------------------------------------------------------------------
# Routing: GalleryDLDownloader routes yt-dlp-primary sites directly
# ---------------------------------------------------------------------------

class TestDownloaderRouting:

    @pytest.mark.asyncio
    async def test_youtube_routes_directly_to_ytdlp(self):
        """YouTube URLs must bypass gallery-dl entirely."""
        from downloaders.gallery_dl import GalleryDLDownloader
        import tempfile

        dl = GalleryDLDownloader(
            output_path=tempfile.mkdtemp(),
            cookie_path=tempfile.mkdtemp(),
        )

        ytdlp_result = {'success': True, 'files': ['/tmp/video.mp4'], 'platform': 'YouTube'}

        with patch.object(dl, '_download_with_ytdlp', new=AsyncMock(return_value=ytdlp_result)) as mock_ytdlp, \
             patch.object(dl, '_execute_with_retry', new=AsyncMock()) as mock_gdl:

            result = await dl.download("https://youtu.be/dQw4w9WgXcQ", "YouTube", user_id="123")

        # gallery-dl must NOT have been called
        mock_gdl.assert_not_called()
        # yt-dlp must have been called
        mock_ytdlp.assert_called_once()
        assert result['success'] is True

    @pytest.mark.asyncio
    async def test_unknown_site_gets_ytdlp_fallback(self):
        """A 'Generic' platform should attempt gallery-dl, then fall back to yt-dlp."""
        from downloaders.gallery_dl import GalleryDLDownloader
        import tempfile

        dl = GalleryDLDownloader(
            output_path=tempfile.mkdtemp(),
            cookie_path=tempfile.mkdtemp(),
        )

        # gallery-dl fails
        gdl_fail = {'success': False, 'error': 'No extractor found'}
        ytdlp_ok  = {'success': True, 'files': ['/tmp/file.jpg'], 'platform': 'Generic'}

        with patch.object(dl, '_execute_with_retry', new=AsyncMock(return_value=gdl_fail)), \
             patch.object(dl, '_get_download_files', return_value=set()), \
             patch.object(dl, '_download_with_ytdlp', new=AsyncMock(return_value=ytdlp_ok)) as mock_fallback:

            result = await dl.download("https://some-site.example.com/post/1", "Generic")

        mock_fallback.assert_called_once()
        assert result['success'] is True

    @pytest.mark.asyncio
    async def test_snapchat_skips_ytdlp_fallback(self):
        """Snapchat must NOT trigger yt-dlp fallback (it has its own downloader)."""
        from downloaders.gallery_dl import GalleryDLDownloader
        import tempfile

        dl = GalleryDLDownloader(
            output_path=tempfile.mkdtemp(),
            cookie_path=tempfile.mkdtemp(),
        )

        gdl_fail = {'success': False, 'error': 'No extractor'}

        with patch.object(dl, '_execute_with_retry', new=AsyncMock(return_value=gdl_fail)), \
             patch.object(dl, '_get_download_files', return_value=set()), \
             patch.object(dl, '_download_with_ytdlp', new=AsyncMock()) as mock_ytdlp:

            await dl.download("https://www.snapchat.com/add/test", "Snapchat")

        mock_ytdlp.assert_not_called()
