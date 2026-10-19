"""Registry and dispatch engine for platform downloaders."""

from typing import Optional, Callable, Dict, Any


class DownloaderRegistry:
    """Dispatches media download requests to appropriate platform extractors."""

    def __init__(self, snapchat=None, gallery_dl=None):
        self.snapchat = snapchat
        self.gallery_dl = gallery_dl

    async def download(
        self,
        url: str,
        platform: str,
        user_id: Optional[str] = None,
        job_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Route URL to the correct downloader backend based on platform and link type."""
        is_spotlight = "/spotlight/" in url
        if platform == "Snapchat" and self.snapchat and not is_spotlight:
            return await self.snapchat.download(url, user_id, job_id)
        elif self.gallery_dl:
            return await self.gallery_dl.download(
                url,
                platform,
                user_id,
                job_id,
                progress_callback=progress_callback
            )
        else:
            return {'success': False, 'error': 'Downloader not initialized'}
