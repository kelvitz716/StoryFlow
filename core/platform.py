"""
Platform identification for StoryFlow.

Every branch calls is_safe_url() first.  A URL that resolves to a non-global
address is always "Unknown", regardless of its hostname.

Returns:
    - "Snapchat"  : snapchat.com (existing — uses custom scraper)
    - "Instagram" : instagram.com (existing — uses gallery-dl + yt-dlp fallback)
    - "TikTok"    : tiktok.com, vm.tiktok.com (existing)
    - "Twitter"   : twitter.com, x.com (existing)
    - "Facebook"  : facebook.com, fb.watch (existing)
    - <Site Name> : Any domain in _GALLERY_DL_DOMAINS (gallery-dl primary)
    - <Site Name> : Any domain in _YTDLP_DOMAINS (yt-dlp direct — skip gallery-dl)
    - "Generic"   : Other globally-routable HTTP/HTTPS URL
    - "Unknown"   : Unsafe, non-HTTP, or unresolvable URL
"""

import logging
from urllib.parse import urlparse
from typing import Optional
from core.security import validate_domain, is_safe_url


# ---------------------------------------------------------------------------
# gallery-dl primary sites (no mandatory cookie/OAuth).
# Source: https://github.com/mikf/gallery-dl/blob/master/docs/supportedsites.md
# Sites marked Cookies or OAuth-only are excluded (user's existing platforms
# already handle Instagram/TikTok/Twitter/Facebook/Snapchat).
# ---------------------------------------------------------------------------
_GALLERY_DL_DOMAINS: dict[str, str] = {
    # Numbers / short names
    "2ch.org": "2ch",
    "35photo.pro": "35PHOTO",
    "behoimi.org": "3dbooru",
    "4archive.org": "4archive",
    "4chan.org": "4chan",
    "4chanarchives.com": "4chanarchives",
    "500px.com": "500px",
    "8chan.moe": "8chan",
    "comics.8muses.com": "8muses",
    "8muses.com": "8muses",
    # A
    "myportfolio.com": "Adobe Portfolio",
    "adultempire.com": "Adult Empire",
    "agn.ph": "AGNPH",
    "ahottie.top": "AHottie",
    "allporncomic.com": "AllPornComic",
    "arca.live": "Arcalive",
    "architizer.com": "Architizer",
    "archiveofourown.org": "Archive of Our Own",
    "are.na": "Are.na",
    "artstation.com": "ArtStation",
    "audiochan.com": "Audiochan",
    # B
    "bbc.co.uk": "BBC",
    "behance.net": "Behance",
    "bellazon.com": "Bellazon",
    "bilibili.com": "Bilibili",
    "bsky.app": "Bluesky",
    "booth.pm": "BOOTH",
    "bunkr.si": "Bunkr",
    # C
    "catbox.moe": "Catbox",
    "cfake.com": "Celebrity Fakes",
    "chzzk.naver.com": "CHZZK",
    "ci-en.net": "Ci-en",
    "civitai.com": "Civitai",
    "comedywildlifephoto.com": "Comedy Wildlife Photography Awards",
    "comicvine.gamespot.com": "Comic Vine",
    "comick.io": "Comick",
    "coomer.st": "Coomer",
    "cyberdrop.cr": "Cyberdrop",
    "cyberfile.me": "CyberFile",
    # D
    "dandadan.net": "Dandadan",
    "danke.moe": "Danke fürs Lesen",
    "desktopography.net": "Desktopography",
    "deviantart.com": "DeviantArt",
    "discord.com": "Discord",
    "dynasty-scans.com": "Dynasty Reader",
    # E
    "aryion.com": "Eka's Portal",
    "eporner.com": "EPORNER",
    "erome.com": "EroMe",
    "everia.club": "EVERIA.CLUB",
    # F
    "fansly.com": "Fansly",
    "fapachi.com": "Fapachi",
    "fapello.com": "Fapello",
    "fikfap.com": "FikFap",
    "filester.me": "filester.me",
    "fitnakedgirls.com": "FitNakedGirls",
    "flickr.com": "Flickr",
    "foriio.com": "foriio",
    # G
    "furaffinity.net": "FurAffinity",
    "furbooru.org": "Furbooru",
    "gamcore.com": "Gamcore",
    "gelbooru.com": "Gelbooru",
    "gofile.io": "GoFile",
    "gurobooru.com": "Gurobooru",
    # H
    "hentai-cosplay-xxx.com": "Hentai Cosplay",
    "hentaienvy.com": "HentaiEnvy",
    "hentaiera.com": "HentaiEra",
    "hentaifox.com": "HentaiFox",
    "hentairox.com": "HentaiRox",
    "hentaizap.com": "HentaiZap",
    "hentainexus.com": "HentaiNexus",
    "hypnohub.net": "Hypnohub",
    # I
    "imagetwist.com": "ImageTwist",
    "imagevenue.com": "Imagevenue",
    "imgadult.com": "ImgAdult",
    "imgclick.net": "Imgclick",
    "imgdrive.net": "ImgDrive.net",
    "imgpv.com": "IMGPV",
    "imgspice.com": "Imgspice",
    "imgtaxi.com": "ImgTaxi.com",
    "imgwallet.com": "ImgWallet.com",
    "imgur.com": "Imgur",
    "i.imgur.com": "Imgur",
    "imhentai.xxx": "IMHentai",
    "imx.to": "IMX.to",
    # J / K
    "jpg7.cr": "JPG Fish",
    "konachan.com": "Konachan",
    # L
    "lesbian.energy": "Lesbian.energy",
    "loliboo.moe": "Lolibooru",
    "lolibooru.moe": "Lolibooru",
    # M
    "mangadex.org": "MangaDex",
    "mangafire.to": "MangaFire",
    "2.mangafreak.me": "MangaFreak",
    "mangapark.net": "MangaPark",
    "mangaread.org": "MangaRead",
    "mangareader.to": "MangaReader",
    "mangataro.org": "MangaTaro",
    "mangatown.com": "MangaTown",
    "mangoxo.com": "Mangoxo",
    "mixdrop.ag": "MixDrop",
    "misskey.io": "Misskey.io",
    "misskey.design": "Misskey.design",
    "misskey.art": "Misskey.art",
    "motherless.com": "Motherless",
    "myhentaigallery.com": "My Hentai Gallery",
    # N
    "blog.naver.com": "Naver Blog",
    "comic.naver.com": "Naver Webtoon",
    "nekohouse.su": "Nekohouse",
    "newgrounds.com": "Newgrounds",
    "seiga.nicovideo.jp": "Niconico Seiga",
    "nijie.info": "nijie",
    "nozomi.la": "Nozomi.la",
    "nsfwalbum.com": "NSFWalbum.com",
    "nudostar.tv": "NudoStar.TV",
    # O
    "ok.porn": "OK.PORN",
    # P
    "pexels.com": "Pexels",
    "pholder.com": "pholder",
    "vogue.com": "PhotoVogue",
    "picarto.tv": "Picarto",
    "picazor.com": "Picazor",
    "pictoa.com": "Pictoa",
    "piczel.tv": "Piczel",
    "pillowfort.social": "Pillowfort",
    "pixeldrain.com": "pixeldrain",
    "pixnet.net": "Pixnet",
    "pixiv.net": "Pixiv",
    "plurk.com": "Plurk",
    "pornhub.com": "Pornhub",
    "pornpics.com": "PornPics.com",
    "pornstars.tube": "PORNSTARS.TUBE",
    "poringa.net": "Poringa",
    "postimages.org": "Postimages",
    "pixhost.to": "PiXhost",
    # R
    "rawkuma.net": "Rawkuma",
    "readcomiconline.li": "Read Comic Online",
    "realbooru.com": "Realbooru",
    "redgifs.com": "RedGIFs",
    "rule34.paheal.net": "Rule 34",
    "rule34.us": "Rule 34",
    "rule34.world": "Rule 34 World",
    "rule34.xyz": "Rule 34 XYZ",
    "rule34.xxx": "Rule 34",
    "rule34hentai.net": "Rule34Hentai",
    # S
    "s3nd.pics": "S3ND",
    "safebooru.org": "Safebooru",
    "sankaku.app": "Sankaku Channel",
    "news.sankakucomplex.com": "Sankaku Complex",
    "scatbooru.co.uk": "Scatbooru",
    "scrolller.com": "Scrolller",
    "raw.senmanga.com": "Sen Manga",
    "sex.com": "Sex.com",
    "simply-hentai.com": "Simply Hentai",
    "sizebooru.com": "Size Booru",
    "skeb.jp": "Skeb",
    "slickpic.com": "SlickPic",
    "slideshare.net": "SlideShare",
    "soundgasm.net": "Soundgasm",
    "speakerdeck.com": "Speaker Deck",
    "steamgriddb.com": "SteamGridDB",
    "subscribestar.com": "SubscribeStar",
    "sxypix.com": "Sxypix",
    # T
    "tapas.io": "Tapas",
    "tcbscans.me": "TCB Scans",
    "telegra.ph": "Telegraph",
    "tenor.com": "Tenor",
    "thehentaiworld.com": "The Hentai World",
    "thefap.net": "TheFap",
    "tbib.org": "The Big ImageBoard",
    "tmohentai.com": "TMOHentai",
    "toyhou.se": "Toyhouse",
    "tumblr.com": "Tumblr",
    "tungsten.run": "Tungsten",
    "turbo.cr": "turbo.cr",
    "twibooru.org": "Twibooru",
    # U
    "unsplash.com": "Unsplash",
    "uploadir.com": "Uploadir",
    "urlgalleries.com": "Urlgalleries",
    # V
    "vipergirls.to": "Vipergirls",
    "vk.com": "VK",
    "vsco.co": "VSCO",
    # W
    "allhaven.cc": "Wallhaven",
    "wallhaven.cc": "Wallhaven",
    "allpapercave.com": "Wallpaper Cave",
    "wallpapercave.com": "Wallpaper Cave",
    "easyl.com": "Weasyl",
    "weasyl.com": "Weasyl",
    "ebmshare.com": "webmshare",
    "ebtoons.com": "WEBTOON",
    "webtoons.com": "WEBTOON",
    "eebcentral.com": "Weeb Central",
    "eebdex.org": "WeebDex",
    "eibo.com": "Weibo",
    "weibo.com": "Weibo",
    "hyp.it": "Whyp",
    "ikiart.org": "WikiArt.org",
    "wikiart.org": "WikiArt.org",
    "ikifeet.com": "Wikifeet",
    "wikifeet.com": "Wikifeet",
    "ikifeetx.com": "Wikifeetx",
    "commons.wikimedia.org": "Wikimedia Commons",
    # X
    "xasiat.com": "Xasiat",
    "xfolio.jp": "Xfolio",
    "xhamster.com": "xHamster",
    "xvideos.com": "XVideos",
    "xbooru.com": "Xbooru",
    # Y
    "yande.re": "yande.re",
    "yiffverse.com": "Yiff verse",
    "yourlesbians.com": "YourLesbians",
    # Z
    "zerochan.net": "Zerochan",
    # Booru variants
    "danbooru.donmai.us": "Danbooru",
    "e621.net": "e621",
    "e926.net": "e926",
    "e6ai.net": "e6AI",
    "derpibooru.org": "Derpibooru",
    "ponybooru.org": "Ponybooru",
    "lolibooru.moe": "Lolibooru",
    "sakugabooru.com": "Sakugabooru",
    # Forums
    "simpcity.cr": "SimpCity Forums",
    "nudostar.com": "NudoStar Forums",
    "allthefallen.moe": "All The Fallen",
    "celebforum.to": "celebforum",
    "forums.socialmediagirls.com": "Social Media Girls Forums",
    "blacktowhite.net": "BlacktoWhite",
    # 4chan archives
    "archive.4plebs.org": "4plebs",
    "archived.moe": "Archived.Moe",
    "archiveofsins.com": "Archive of Sins",
    "desuarchive.org": "Desuarchive",
    "boards.fireden.net": "Fireden",
    # Image hosts
    "acidimg.cc": "Acidimg",
    "fappic.com": "Fappic.com",
    "imglike.com": "Nude Celeb",
    "picstate.com": "PicState",
    "silverpic.net": "SilverPic.com",
    "turboimagehost.com": "TurboImageHost.com",
    "putmega.com": "Putmega",
    # Manga
    "nelomanga.net": "MangaNelo",
    "natomanga.com": "MangaNato",
    "manganato.gg": "MangaNato",
    "mangakakalot.gg": "MangaKakalot",
    "allgirl.booru.org": "All girl",
}

# ---------------------------------------------------------------------------
# yt-dlp primary sites — gallery-dl has no extractor for these.
# Sending to gallery-dl first would waste time; route directly to yt-dlp.
# ---------------------------------------------------------------------------
_YTDLP_DOMAINS: dict[str, str] = {
    # Video platforms
    "youtube.com": "YouTube",
    "m.youtube.com": "YouTube",
    "music.youtube.com": "YouTube Music",
    "youtu.be": "YouTube",
    "vimeo.com": "Vimeo",
    "player.vimeo.com": "Vimeo",
    "twitch.tv": "Twitch",
    "clips.twitch.tv": "Twitch",
    "m.twitch.tv": "Twitch",
    "dailymotion.com": "Dailymotion",
    "dai.ly": "Dailymotion",
    "rumble.com": "Rumble",
    "odysee.com": "Odysee",
    "kick.com": "Kick",
    "streamable.com": "Streamable",
    "medal.tv": "Medal.TV",
    "clipe.tv": "Clipe.TV",
    "vlive.tv": "VLive",
    "ok.ru": "OK.ru",
    # Music / Audio
    "soundcloud.com": "SoundCloud",
    "on.soundcloud.com": "SoundCloud",
    "bandcamp.com": "Bandcamp",
    "mixcloud.com": "Mixcloud",
    "audiomack.com": "Audiomack",
    # Reddit (video posts)
    "reddit.com": "Reddit",
    "old.reddit.com": "Reddit",
    "redd.it": "Reddit",
    "v.redd.it": "Reddit",
    # Anime / Manga streaming
    "crunchyroll.com": "Crunchyroll",
    "funimation.com": "Funimation",
    "bilibili.tv": "Bilibili TV",
    "niconico.jp": "Niconico",
    "nicovideo.jp": "Niconico",
    "nico.ms": "Niconico",
    # Other notable video sites
    "liveleak.com": "LiveLeak",
    "gfycat.com": "Gfycat",
    "9gag.com": "9GAG",
    "ted.com": "TED",
    "twit.tv": "TWiT",
    "nebula.tv": "Nebula",
    "dropout.tv": "Dropout",
    "adn.com": "ADN",
    "peertube.social": "PeerTube",
    "tilvids.com": "TILvids",
    "video.blahaj.zone": "Blahaj Zone",
    "kolektiva.media": "Kolektiva",
    # Short video / clips
    "streamff.com": "Streamff",
    "clippituser.tv": "Clippituser",
}

# Public set used by gallery_dl.py to decide whether to skip gallery-dl
YTDLP_DIRECT_PLATFORMS: frozenset[str] = frozenset(_YTDLP_DOMAINS.values())

# Combined lookup: domain → display name
_ALL_KNOWN_DOMAINS: dict[str, str] = {**_GALLERY_DL_DOMAINS, **_YTDLP_DOMAINS}


def identify_platform(url: str) -> str:
    """
    Identify the platform for a given URL.

    Priority order:
    1. Safety gate (is_safe_url) — returns "Unknown" on failure
    2. Existing named platforms (Snapchat, Instagram, TikTok, Twitter, Facebook)
    3. Known gallery-dl / yt-dlp domains → proper display name
    4. Any other http/https URL → "Generic" (still routed to gallery-dl + yt-dlp)
    5. Everything else → "Unknown"
    """
    if not is_safe_url(url):
        return "Unknown"

    # ── 2. Existing platform implementations (do not touch) ─────────────────
    if validate_domain(url, ['snapchat.com']):
        return "Snapchat"
    if validate_domain(url, ['instagram.com']):
        return "Instagram"
    if validate_domain(url, ['tiktok.com', 'vm.tiktok.com']):
        return "TikTok"
    if validate_domain(url, ['twitter.com', 'x.com']):
        return "Twitter"
    if validate_domain(url, ['facebook.com', 'fb.watch']):
        return "Facebook"

    # ── 3. Known gallery-dl / yt-dlp domains ────────────────────────────────
    try:
        hostname = urlparse(url).hostname or ""
        # Strip leading "www." for lookup
        bare = hostname.removeprefix("www.")
        if bare in _ALL_KNOWN_DOMAINS:
            return _ALL_KNOWN_DOMAINS[bare]
        # Try full hostname (e.g. seiga.nicovideo.jp already has subdomain)
        if hostname in _ALL_KNOWN_DOMAINS:
            return _ALL_KNOWN_DOMAINS[hostname]
    except Exception as exc:
        logging.debug(f"identify_platform domain lookup error: {exc}")

    # ── 4. Generic HTTP/HTTPS ────────────────────────────────────────────────
    if url.startswith(('http://', 'https://')):
        return "Generic"

    return "Unknown"


def extract_snapchat_username(url: str) -> Optional[str]:
    """
    Extract username from Snapchat URL.

    Supported URL patterns:
        - https://www.snapchat.com/add/username
        - https://www.snapchat.com/add/username/
        - https://www.snapchat.com/add/username/l
        - https://snapchat.com/stories/username
        - https://snapchat.com/spotlight/username

    Args:
        url: Snapchat URL

    Returns:
        Username string or None if extraction fails
    """
    try:
        parsed = urlparse(url)
        path = parsed.path.strip('/')

        # Split path into segments
        segments = [s for s in path.split('/') if s]

        # Expected patterns: /add/username, /stories/username, /spotlight/username, /highlight/username, /@username

        if len(segments) == 1 and segments[0].startswith('@'):
            return segments[0].lstrip('@')

        if len(segments) < 2:
            logging.warning(f"Invalid Snapchat URL format: {url}")
            return None

        action = segments[0].lower()

        if action in ('add', 'stories', 'spotlight', 'highlight', 'highlights'):
            username = segments[1].lstrip('@')
            # Clean username (remove trailing 'l' from some share links)
            if len(segments) > 2 and segments[2] == 'l':
                pass  # Username is already correct
            return username
        else:
            logging.warning(f"Unrecognized Snapchat URL action: {action}")
            return None

    except Exception as e:
        logging.error(f"Failed to extract Snapchat username: {e}")
        return None
