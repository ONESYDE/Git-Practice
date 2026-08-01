"""
downloader.py

Downloads one authorized video URL into a temporary folder, converts it to one
validated H.264/AAC MP4, and removes the temporary source after success.

Final location:
    Downloads/OneSydeDownloader/<Course>/<Week>/<Video>.mp4
"""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from converter import make_itunes_mp4

try:
    import yt_dlp
except ModuleNotFoundError:
    yt_dlp = None


StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]

VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
}

BAD_KALTURA_HOSTS = [
    "cdnsecakmi.kaltura.com",
]

AUTH_HINTS = (
    "401",
    "403",
    "access denied",
    "authentication",
    "cookies",
    "forbidden",
    "login",
    "private",
    "sign in",
    "unauthorized",
)

# True:
#   Download every distinct video contained in a Kaltura playlist.
#
# False:
#   Download only the first video from a Kaltura playlist.
#
# Each actual video still produces only one permanent MP4.
DOWNLOAD_FULL_KALTURA_PLAYLIST = True

# ---------------------------------------------------------
# Application paths
# ---------------------------------------------------------

def app_dir() -> Path:
    """
    Return the folder containing downloader.py or the packaged EXE.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


def cookies_path() -> str:
    """
    Return the optional cookies.txt location.
    """
    return str(app_dir() / "cookies.txt")


def default_download_root() -> Path:
    """
    Return the permanent application output root.
    """
    return Path.home() / "Downloads" / "OneSydeDownloader"


def _safe_folder_name(
    value: str,
    fallback: str,
) -> str:
    """
    Return a Windows-safe Course or Week folder name.
    """
    cleaned = re.sub(
        r'[<>:"/\\|?*\x00-\x1F]',
        "_",
        (value or "").strip(),
    )

    cleaned = cleaned.rstrip(" .")

    return (cleaned or fallback)[:120]


def _build_final_folder(
    course: str,
    week: str,
) -> Path:
    """
    Create and return the Course/Week output folder.
    """
    root = default_download_root().resolve()

    folder = (
        root
        / _safe_folder_name(
            course,
            "Unsorted Course",
        )
        / _safe_folder_name(
            week,
            "Unsorted Week",
        )
    ).resolve()

    # Prevent Course/Week values from escaping the Downloads root.
    if folder != root and root not in folder.parents:
        raise ValueError(
            "The Course/Week output path is invalid."
        )

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    return folder


# ---------------------------------------------------------
# Tool detection
# ---------------------------------------------------------

def _resolve_ffmpeg(
    ffmpeg_path: str | None,
) -> str | None:
    """
    Find FFmpeg from:
    1. The path supplied by the GUI
    2. ffmpeg.exe beside the app
    3. The system PATH
    """
    if ffmpeg_path:
        candidate = Path(
            ffmpeg_path
        ).expanduser()

        if candidate.is_file():
            return str(
                candidate.resolve()
            )

    local_ffmpeg = (
        app_dir()
        / "ffmpeg.exe"
    )

    if local_ffmpeg.is_file():
        return str(local_ffmpeg)

    return shutil.which("ffmpeg")


def assert_tools_ready(
    ffmpeg_path: str | None = None,
) -> str:
    """
    Confirm that yt-dlp and FFmpeg are available.
    """
    if yt_dlp is None:
        raise RuntimeError(
            "yt-dlp is not installed.\n\n"
            "Run:\n"
            "python -m pip install --upgrade yt-dlp"
        )

    resolved = _resolve_ffmpeg(
        ffmpeg_path
    )

    if not resolved:
        raise RuntimeError(
            "FFmpeg was not found.\n\n"
            "Put ffmpeg.exe beside the app "
            "or add FFmpeg to PATH."
        )

    return resolved


# ---------------------------------------------------------
# URL safety and normalization
# ---------------------------------------------------------

def _validate_public_http_url(
    url: str,
) -> None:
    """
    Allow public HTTP(S) URLs and block unsafe local URL forms.
    """
    parsed = urllib.parse.urlsplit(
        url
    )

    if parsed.scheme.lower() not in {
        "http",
        "https",
    }:
        raise ValueError(
            "Only http:// and https:// URLs are allowed."
        )

    if not parsed.hostname:
        raise ValueError(
            "The URL does not contain a valid hostname."
        )

    if parsed.username or parsed.password:
        raise ValueError(
            "URLs containing embedded usernames "
            "or passwords are blocked."
        )

    hostname = (
        parsed.hostname
        .lower()
        .rstrip(".")
    )

    if (
        hostname == "localhost"
        or hostname.endswith(".local")
    ):
        raise ValueError(
            "Local/private-network URLs are blocked."
        )

    try:
        literal_ip = ipaddress.ip_address(
            hostname
        )
    except ValueError:
        literal_ip = None

    if (
        literal_ip is not None
        and not literal_ip.is_global
    ):
        raise ValueError(
            "Private, loopback, link-local, "
            "and reserved IP URLs are blocked."
        )


def normalize_url(
    url: str,
) -> str:
    """
    Normalize normal URLs and supported Kaltura URL forms.

    Supported Kaltura formats include:
    - entry_id/1_xxxxx
    - entry_id=1_xxxxx
    - playlist_id/1_xxxxx
    - playlist_id=1_xxxxx
    - flashvars[playlistAPI.kpl0Id]=1_xxxxx
    """
    cleaned = urllib.parse.unquote(
        (url or "").strip()
    )

    cleaned = (
        cleaned
        .strip()
        .strip('"')
        .strip("'")
        .strip()
    )

    cleaned = (
        cleaned
        .replace('"', "")
        .replace("'", "")
        .strip()
    )

    cleaned = re.sub(
        r"^https?://\s*https//",
        "https://",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"^https?://\s*http//",
        "http://",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"^https//",
        "https://",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"^http//",
        "http://",
        cleaned,
        flags=re.IGNORECASE,
    )

    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned

    if cleaned.lower().startswith(
        (
            "www.",
            "cdnapisec.kaltura.com",
            "cdnapi.kaltura.com",
        )
    ):
        cleaned = (
            "https://"
            + cleaned
        )

    # Remove URL fragments such as a trailing #.
    split = urllib.parse.urlsplit(
        cleaned
    )

    if split.scheme and split.netloc:
        cleaned = urllib.parse.urlunsplit(
            (
                split.scheme,
                split.netloc,
                split.path,
                split.query,
                "",
            )
        )

    _validate_public_http_url(
        cleaned
    )

    if "kaltura.com" not in cleaned.lower():
        return cleaned

    partner_match = (
        re.search(
            r"partner_id/(\d+)",
            cleaned,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"/p/(\d+)",
            cleaned,
            flags=re.IGNORECASE,
        )
    )

    uiconf_match = (
        re.search(
            r"uiconf_id/(\d+)",
            cleaned,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"[?&]uiconf_id=(\d+)",
            cleaned,
            flags=re.IGNORECASE,
        )
    )

    playlist_match = (
        re.search(
            r"/playlist_id/(\d_[A-Za-z0-9]+)",
            cleaned,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"[?&]playlist_id=(\d_[A-Za-z0-9]+)",
            cleaned,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:flashvars\[)?"
            r"playlistAPI\.kpl0Id\]?="
            r"(\d_[A-Za-z0-9]+)",
            cleaned,
            flags=re.IGNORECASE,
        )
    )

    entry_match = (
        re.search(
            r"/entry_id/(\d_[A-Za-z0-9]+)",
            cleaned,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"[?&]entry_id=(\d_[A-Za-z0-9]+)",
            cleaned,
            flags=re.IGNORECASE,
        )
    )

    if (
        not partner_match
        or not uiconf_match
    ):
        return cleaned

    partner_id = (
        partner_match.group(1)
    )

    uiconf_id = (
        uiconf_match.group(1)
    )

    if playlist_match:
        playlist_id = (
            playlist_match.group(1)
        )

        return (
            "https://www.kaltura.com/"
            "index.php/extwidget/preview/"
            f"partner_id/{partner_id}/"
            f"uiconf_id/{uiconf_id}/"
            f"playlist_id/{playlist_id}"
        )

    if entry_match:
        entry_id = (
            entry_match.group(1)
        )

        return _kaltura_entry_url(
            partner_id,
            uiconf_id,
            entry_id,
        )

    return cleaned


# ---------------------------------------------------------
# Kaltura helpers
# ---------------------------------------------------------

def _kaltura_parts(
    url: str,
) -> dict[str, str]:
    """
    Extract Kaltura IDs from a normalized URL.
    """
    parts: dict[str, str] = {}

    patterns = {
        "partner_id": (
            r"partner_id/(\d+)",
            r"/p/(\d+)",
        ),
        "uiconf_id": (
            r"uiconf_id/(\d+)",
            r"[?&]uiconf_id=(\d+)",
        ),
        "playlist_id": (
            r"playlist_id/(\d_[A-Za-z0-9]+)",
            r"[?&]playlist_id=(\d_[A-Za-z0-9]+)",
        ),
    }

    for key, key_patterns in patterns.items():
        for pattern in key_patterns:
            match = re.search(
                pattern,
                url,
                flags=re.IGNORECASE,
            )

            if match:
                parts[key] = (
                    match.group(1)
                )

                break

    return parts


def _kaltura_entry_url(
    partner_id: str,
    uiconf_id: str,
    entry_id: str,
) -> str:
    """
    Build a Kaltura single-video URL supported by yt-dlp.
    """
    return (
        "https://www.kaltura.com/"
        "index.php/extwidget/preview/"
        f"partner_id/{partner_id}/"
        f"uiconf_id/{uiconf_id}/"
        f"entry_id/{entry_id}"
    )


def _extract_entry_ids(
    value: object,
    playlist_id: str,
) -> list[str]:
    """
    Recursively collect Kaltura media entry IDs.
    """
    found: list[str] = []

    def add_entry(
        entry_id: str,
    ) -> None:
        cleaned = (
            entry_id.strip()
        )

        if (
            cleaned != playlist_id
            and re.fullmatch(
                r"\d_[A-Za-z0-9]+",
                cleaned,
            )
            and cleaned not in found
        ):
            found.append(
                cleaned
            )

    def walk(
        item: object,
    ) -> None:
        if isinstance(item, dict):
            explicit_entry = (
                item.get("entryId")
                or item.get("entry_id")
            )

            if isinstance(
                explicit_entry,
                str,
            ):
                add_entry(
                    explicit_entry
                )

            possible_id = (
                item.get("id")
            )

            object_type = str(
                item.get("objectType")
                or ""
            )

            looks_like_media_entry = (
                "MediaEntry" in object_type
                or "mediaType" in item
                or "dataUrl" in item
            )

            if (
                looks_like_media_entry
                and isinstance(
                    possible_id,
                    str,
                )
            ):
                add_entry(
                    possible_id
                )

            for nested in item.values():
                walk(
                    nested
                )

        elif isinstance(item, list):
            for nested in item:
                walk(
                    nested
                )

    walk(
        value
    )

    return found

def _entry_ids_from_text(
    text: str,
    playlist_id: str,
) -> list[str]:
    """
    Extract Kaltura entry IDs from JSON, HTML, JavaScript, or yt-dlp metadata.
    """
    found: list[str] = []

    patterns = (
        r'"entryId"\s*:\s*"(\d_[A-Za-z0-9]+)"',
        r'"entry_id"\s*:\s*"(\d_[A-Za-z0-9]+)"',
        r'"id"\s*:\s*"(\d_[A-Za-z0-9]+)"',
        r"entry_id[/=](\d_[A-Za-z0-9]+)",
        r"entryId[/=](\d_[A-Za-z0-9]+)",
    )

    for pattern in patterns:
        for entry_id in re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            cleaned = entry_id.strip()

            if (
                cleaned != playlist_id
                and cleaned not in found
            ):
                found.append(cleaned)

    return found


def _resolve_playlist_entries(
    canonical_url: str,
    original_url: str,
    cookie_file: str | None,
    on_status: StatusCallback | None,
) -> list[str]:
    """
    Resolve a Kaltura playlist into individual entry URLs.

    Resolution order:
    1. Kaltura playlist API
    2. yt-dlp metadata extraction
    3. Original embed-page HTML
    """
    parts = _kaltura_parts(canonical_url)

    partner_id = parts.get("partner_id")
    uiconf_id = parts.get("uiconf_id")
    playlist_id = parts.get("playlist_id")

    if (
        not partner_id
        or not uiconf_id
        or not playlist_id
    ):
        return []

    if on_status:
        on_status(
            f"Resolving Kaltura playlist {playlist_id}..."
        )

    entry_ids: list[str] = []

    request_body = urllib.parse.urlencode(
        {
            "format": "1",
            "partnerId": partner_id,
            "id": playlist_id,
            "detailed": "true",
        }
    ).encode("utf-8")

    api_urls = (
        (
            "https://www.kaltura.com/api_v3/"
            "service/playlist/action/execute"
        ),
        (
            "https://cdnapisec.kaltura.com/api_v3/"
            "service/playlist/action/execute"
        ),
    )

    # Attempt 1: official playlist API.
    for api_url in api_urls:
        try:
            request = urllib.request.Request(
                api_url,
                data=request_body,
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "Content-Type": (
                        "application/x-www-form-urlencoded"
                    ),
                    "User-Agent": "Mozilla/5.0",
                },
                method="POST",
            )

            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                response_text = response.read().decode(
                    "utf-8",
                    errors="replace",
                )

            data = json.loads(response_text)

            if (
                isinstance(data, dict)
                and data.get("objectType")
                == "KalturaAPIException"
            ):
                continue

            entry_ids = _extract_entry_ids(
                data,
                playlist_id,
            )

            if not entry_ids:
                entry_ids = _entry_ids_from_text(
                    response_text,
                    playlist_id,
                )

            if entry_ids:
                break

        except (
            OSError,
            json.JSONDecodeError,
        ):
            continue

    # Attempt 2: let yt-dlp inspect the original embed URL.
    if not entry_ids and yt_dlp is not None:
        try:
            metadata_options: dict[str, Any] = {
                "skip_download": True,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": False,
            }

            if cookie_file:
                metadata_options["cookiefile"] = cookie_file

            with yt_dlp.YoutubeDL(
                cast(Any, metadata_options)
            ) as metadata_downloader:  # type: ignore[union-attr]
                metadata = metadata_downloader.extract_info(
                    original_url,
                    download=False,
                )

            metadata_text = json.dumps(
                metadata,
                ensure_ascii=False,
                default=str,
            )

            entry_ids = _entry_ids_from_text(
                metadata_text,
                playlist_id,
            )

        except Exception as exc:  # noqa: BLE001
            if on_status:
                on_status(
                    f"Playlist metadata fallback was unavailable: {exc}"
                )
    # Attempt 3: inspect the old embed-page HTML directly.
    if not entry_ids:
        page_urls = dict.fromkeys(
            (
                original_url,
                canonical_url,
            )
        )

        for page_url in page_urls:
            try:
                request = urllib.request.Request(
                    page_url,
                    headers={
                        "Accept": "text/html,*/*",
                        "User-Agent": "Mozilla/5.0",
                    },
                )

                with urllib.request.urlopen(
                    request,
                    timeout=30,
                ) as response:
                    html = response.read().decode(
                        "utf-8",
                        errors="replace",
                    )

                html = urllib.parse.unquote(html)

                entry_ids = _entry_ids_from_text(
                    html,
                    playlist_id,
                )

                if entry_ids:
                    break

            except OSError:
                continue

    if not entry_ids:
        raise RuntimeError(
            "Kaltura recognized the playlist ID but no video "
            "entries could be resolved.\n\n"
            "The playlist may require an authenticated Canvas/"
            "Kaltura session. Export cookies.txt, enable cookies "
            "fallback, and retry."
        )

    entry_urls = [
        _kaltura_entry_url(
            partner_id,
            uiconf_id,
            entry_id,
        )
        for entry_id in entry_ids
    ]

    if on_status:
        on_status(
            f"Resolved {len(entry_urls)} playlist video(s)."
        )

    return entry_urls


# ---------------------------------------------------------
# Other URL helpers
# ---------------------------------------------------------

def _is_zoom_share_page(
    url: str,
) -> bool:
    """
    Return True for Zoom recording share/play pages.
    """
    parsed = urlparse(
        url
    )

    return (
        "zoom.us"
        in parsed.netloc.lower()
        and (
            "/rec/share/"
            in parsed.path.lower()
            or "/rec/play/"
            in parsed.path.lower()
        )
    )


def _looks_like_auth_problem(
    message: str,
) -> bool:
    """
    Return True when an error looks authentication-related.
    """
    lowered = (
        message or ""
    ).lower()

    return any(
        hint in lowered
        for hint in AUTH_HINTS
    )


# ---------------------------------------------------------
# yt-dlp helpers
# ---------------------------------------------------------

class _YtdlpLogger:
    """
    Send useful yt-dlp messages to the GUI.
    """

    def __init__(
        self,
        on_status: StatusCallback | None,
    ) -> None:
        self.on_status = on_status

    def debug(
        self,
        _message: str,
    ) -> None:
        pass

    def warning(
        self,
        message: str,
    ) -> None:
        if self.on_status:
            self.on_status(
                f"Warning: {message[:200]}"
            )

    def error(
        self,
        message: str,
    ) -> None:
        if self.on_status:
            self.on_status(
                f"Error: {message[:200]}"
            )


def _progress_hook(
    on_status: StatusCallback | None,
    on_progress: ProgressCallback | None,
) -> Callable[[dict[str, Any]], None]:
    """
    Create a yt-dlp progress callback.
    """

    def hook(
        data: dict[str, Any],
    ) -> None:
        status = data.get(
            "status"
        )

        if status == "downloading":
            downloaded = float(
                data.get("downloaded_bytes")
                or 0
            )

            total = float(
                data.get("total_bytes")
                or data.get(
                    "total_bytes_estimate"
                )
                or 0
            )

            if total > 0:
                percent = max(
                    0.0,
                    min(
                        100.0,
                        downloaded
                        / total
                        * 100.0,
                    ),
                )

                if on_progress:
                    on_progress(
                        percent
                    )

                if on_status:
                    on_status(
                        f"Downloading... {percent:.1f}%"
                    )

            elif on_status:
                on_status(
                    "Downloading..."
                )

        elif status == "finished":
            if on_progress:
                on_progress(
                    100.0
                )

            if on_status:
                on_status(
                    "Download finished. "
                    "Preparing the source video..."
                )

    return hook


def _download_once(
    url: str,
    job_folder: Path,
    ffmpeg_path: str,
    cookie_file: str | None,
    on_status: StatusCallback | None,
    on_progress: ProgressCallback | None,
    download_subtitles: bool,
) -> None:
    """
    Download one URL into an isolated temporary folder.
    """
    if yt_dlp is None:
        raise RuntimeError(
            "yt-dlp is not installed."
        )

    options: dict[str, Any] = {
        "outtmpl": str(
            job_folder
            / "%(title).180s [%(id)s].%(ext)s"
        ),

        "format": "bv*+ba/b",

        "merge_output_format": "mp4",

        # Playlist URLs are resolved before this function.
        "noplaylist": True,

        "windowsfilenames": True,

        "overwrites": True,

        "continuedl": True,

        # Do not preserve separate audio/video streams.
        "keepvideo": False,

        "keep_fragments": False,

        "socket_timeout": 120,

        "retries": 20,

        "fragment_retries": 20,

        "http_chunk_size": (
            10
            * 1024
            * 1024
        ),

        "user_agent": "Mozilla/5.0",

        "ffmpeg_location": ffmpeg_path,

        "extractor_args": {
            "kaltura": {
                "excluded_cdn_hosts": (
                    BAD_KALTURA_HOSTS
                )
            }
        },

        "progress_hooks": [
            _progress_hook(
                on_status,
                on_progress,
            )
        ],

        "logger": _YtdlpLogger(
            on_status
        ),

        "quiet": True,

        "no_warnings": False,
    }

    if cookie_file:
        options["cookiefile"] = (
            cookie_file
        )

    if download_subtitles:
        options.update(
            {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [
                    "en.*",
                    "en",
                ],
                "subtitlesformat": (
                    "srt/best"
                ),
                "convertsubtitles": "srt",
            }
        )

    with yt_dlp.YoutubeDL(
        cast(Any, options)
    ) as downloader:  # type: ignore[union-attr]

        result = downloader.download(
            [url]
        )

    if result:
        raise RuntimeError(
            "yt-dlp stopped with "
            f"error code {result}."
        )


# ---------------------------------------------------------
# Downloaded-file selection
# ---------------------------------------------------------

def _select_downloaded_video(
    job_folder: Path,
) -> Path | None:
    """
    Select exactly one completed source video.
    """
    candidates = [
        path
        for path in job_folder.rglob("*")
        if (
            path.is_file()
            and path.suffix.lower()
            in VIDEO_EXTENSIONS
        )
    ]

    if not candidates:
        return None

    def score(
        path: Path,
    ) -> tuple[int, int, int, int]:
        # yt-dlp temporary format files may end in .f137, .f140, etc.
        is_fragment = bool(
            re.search(
                r"\.f\d+$",
                path.stem,
                flags=re.IGNORECASE,
            )
        )

        is_mp4 = (
            path.suffix.lower()
            == ".mp4"
        )

        try:
            file_info = path.stat()

            return (
                0 if is_fragment else 1,
                1 if is_mp4 else 0,
                file_info.st_size,
                file_info.st_mtime_ns,
            )

        except OSError:
            return (
                0,
                0,
                0,
                0,
            )

    return max(
        candidates,
        key=score,
    )


def _remove_successful_job(
    job_folder: Path,
) -> None:
    """
    Remove temporary files only after conversion succeeds.
    """
    shutil.rmtree(
        job_folder,
        ignore_errors=True,
    )

    try:
        job_folder.parent.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------
# Main public download function
# ---------------------------------------------------------

def _download_convert_one(
    video_url: str,
    final_folder: Path,
    use_cookies: bool,
    resolved_ffmpeg: str,
    on_status: StatusCallback | None,
    on_progress: ProgressCallback | None,
    download_subtitles: bool,
    item_number: int,
    item_total: int,
) -> str:
    """
    Download, convert, validate, and clean up one individual video.

    The raw source exists only inside a hidden temporary folder.
    """
    job_folder = (
        final_folder
        / ".onesyde-working"
        / uuid.uuid4().hex
    )

    job_folder.mkdir(
        parents=True,
        exist_ok=False,
    )

    cookie_file = cookies_path()
    cookies_available = Path(cookie_file).is_file()

    def combined_download_progress(
        percent: float,
    ) -> None:
        """
        Reserve 0-75% for downloading and 78-100% for conversion.
        """
        if on_progress:
            scaled = max(
                0.0,
                min(
                    75.0,
                    float(percent) * 0.75,
                ),
            )

            on_progress(scaled)

    try:
        if on_status:
            on_status(
                f"Video {item_number}/{item_total}: "
                "downloading and converting..."
            )

        try:
            _download_once(
                video_url,
                job_folder,
                resolved_ffmpeg,
                None,
                on_status,
                combined_download_progress,
                download_subtitles,
            )

        except Exception as exc:
            message = str(exc)

            if (
                use_cookies
                and cookies_available
                and _looks_like_auth_problem(message)
            ):
                if on_status:
                    on_status(
                        f"Video {item_number}/{item_total}: "
                        "retrying with cookies.txt..."
                    )

                _download_once(
                    video_url,
                    job_folder,
                    resolved_ffmpeg,
                    cookie_file,
                    on_status,
                    combined_download_progress,
                    download_subtitles,
                )

            elif (
                use_cookies
                and not cookies_available
            ):
                raise FileNotFoundError(
                    "Cookies fallback is enabled, but "
                    "cookies.txt was not found.\n\n"
                    f"Expected location:\n{cookie_file}"
                ) from exc

            elif _looks_like_auth_problem(message):
                raise RuntimeError(
                    "This video appears to require login cookies.\n\n"
                    "Export cookies.txt from the authorized browser "
                    "session, place it beside the app, enable cookies "
                    "fallback, and retry.\n\n"
                    f"Details: {message}"
                ) from exc

            else:
                raise

        source = _select_downloaded_video(
            job_folder
        )

        if source is None:
            raise RuntimeError(
                "The download completed, but no finished video "
                "file was found."
            )

        if on_status:
            on_status(
                f"Video {item_number}/{item_total}: "
                "converting immediately..."
            )

        converted = make_itunes_mp4(
            source,
            ffmpeg_path=resolved_ffmpeg,
            output_dir=final_folder,
            replace_source=True,
            on_status=on_status,
            on_progress=on_progress,
        )

        # Remove the temporary raw download only after the MP4
        # has passed conversion and validation.
        _remove_successful_job(
            job_folder
        )

        return converted

    except Exception as exc:
        raise RuntimeError(
            f"Playlist video {item_number}/{item_total} did not "
            "finish successfully.\n\n"
            "Its temporary source was preserved here:\n"
            f"{job_folder}\n\n"
            f"Details: {exc}"
        ) from exc


def download_video(
    url: str,
    course: str,
    week: str,
    use_cookies: bool,
    on_status: StatusCallback | None = None,
    on_progress: ProgressCallback | None = None,
    ffmpeg_path: str | None = None,
    download_subtitles: bool = False,
) -> str:
    """
    Download and immediately convert one normal URL or Kaltura playlist.

    Individual URL:
        one final MP4

    Kaltura playlist URL:
        one final MP4 per distinct playlist video

    No permanent raw duplicates remain after successful validation.
    """
    resolved_ffmpeg = assert_tools_ready(
        ffmpeg_path
    )

    original_url = (
        url or ""
    ).strip()

    normalized_url = normalize_url(
        original_url
    )

    if not normalized_url:
        raise ValueError(
            "The video URL is empty."
        )

    if _is_zoom_share_page(
        normalized_url
    ):
        raise ValueError(
            "Zoom share/play links are not direct downloadable "
            "files. Use Zoom's Download button or provide a "
            "direct media URL."
        )

    final_folder = _build_final_folder(
        course,
        week,
    )

    parts = _kaltura_parts(
        normalized_url
    )

    playlist_id = parts.get(
        "playlist_id"
    )

    video_urls: list[str]

    if playlist_id:
        cookie_file = cookies_path()

        usable_cookie_file = (
            cookie_file
            if (
                use_cookies
                and Path(cookie_file).is_file()
            )
            else None
        )

        video_urls = _resolve_playlist_entries(
            canonical_url=normalized_url,
            original_url=original_url,
            cookie_file=usable_cookie_file,
            on_status=on_status,
        )

        if not DOWNLOAD_FULL_KALTURA_PLAYLIST:
            video_urls = video_urls[:1]

    else:
        video_urls = [
            normalized_url
        ]

    if not video_urls:
        raise RuntimeError(
            "No downloadable video URLs were resolved."
        )

    completed_files: list[str] = []

    for index, video_url in enumerate(
        video_urls,
        start=1,
    ):
        if on_progress:
            on_progress(0.0)

        completed = _download_convert_one(
            video_url=video_url,
            final_folder=final_folder,
            use_cookies=use_cookies,
            resolved_ffmpeg=resolved_ffmpeg,
            on_status=on_status,
            on_progress=on_progress,
            download_subtitles=download_subtitles,
            item_number=index,
            item_total=len(video_urls),
        )

        completed_files.append(
            completed
        )

    if on_progress:
        on_progress(100.0)

    if on_status:
        if len(completed_files) == 1:
            on_status(
                "Completed and verified: "
                f"{completed_files[0]}"
            )
        else:
            on_status(
                f"Completed and verified "
                f"{len(completed_files)} playlist videos."
            )

    return completed_files[-1]