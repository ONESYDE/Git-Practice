"""
converter.py

Convert videos into broadly compatible MP4 files.

Primary encoder:
    Intel Quick Sync H.264 (h264_qsv)

Automatic fallback:
    CPU H.264 (libx264)

Final format:
    H.264/AVC video
    AAC-LC audio
    MP4 container
    4:2:0 pixel format
    Fast-start metadata
"""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]


class ConversionError(RuntimeError):
    """Raised when FFmpeg cannot create or validate the final MP4."""


def _resolve_ffmpeg(ffmpeg_path: str | None) -> str:
    """Return a validated FFmpeg path or the ffmpeg command from PATH."""
    if ffmpeg_path:
        resolved = Path(
            os.path.abspath(
                os.path.expandvars(ffmpeg_path)
            )
        )

        if not resolved.is_file():
            raise FileNotFoundError(
                "ffmpeg.exe was not found:\n"
                f"{resolved}"
            )

        return str(resolved)

    return "ffmpeg"


def _run(
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    """
    Run FFmpeg safely without shell=True.

    Every FFmpeg argument must be a string.
    """
    for index, argument in enumerate(command):
        if not isinstance(argument, str):
            raise TypeError(
                "Invalid FFmpeg command argument.\n\n"
                f"Position: {index}\n"
                f"Type: {type(argument).__name__}\n"
                f"Value: {argument!r}\n\n"
                "Every FFmpeg command argument must be a string."
            )

    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
            startupinfo=startupinfo,
        )

    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def _unique_output_path(
    folder: Path,
    stem: str,
) -> Path:
    """Return an unused MP4 path for a local-file conversion."""
    candidate = folder / f"{stem}.mp4"

    if not candidate.exists():
        return candidate

    number = 1

    while True:
        candidate = folder / f"{stem} ({number}).mp4"

        if not candidate.exists():
            return candidate

        number += 1


def _temporary_path(
    final_path: Path,
) -> Path:
    """Return a unique temporary MP4 path beside the final file."""
    token = uuid.uuid4().hex[:12]

    return final_path.parent / (
        f".{final_path.stem}.{token}.tmp.mp4"
    )


def _remove_quietly(
    path: Path,
) -> None:
    """Delete a temporary file while ignoring cleanup errors."""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _inspect(
    ffmpeg: str,
    path: Path,
) -> str:
    """Return FFmpeg stream information for a media file."""
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(path),
        ]
    )

    return "\n".join(
        value
        for value in (
            result.stdout,
            result.stderr,
        )
        if value
    )


def _validate(
    ffmpeg: str,
    path: Path,
) -> None:
    """Validate codecs, pixel format, and full-file decoding."""
    if (
        not path.is_file()
        or path.stat().st_size < 1_024
    ):
        raise ConversionError(
            "The converted MP4 is missing or unexpectedly small."
        )

    media_info = _inspect(
        ffmpeg,
        path,
    ).lower()

    if "video: h264" not in media_info:
        raise ConversionError(
            "The final MP4 is not H.264 video."
        )

    # Intel Quick Sync may report 4:2:0 as NV12.
    # CPU libx264 normally reports yuv420p.
    if (
        "yuv420p" not in media_info
        and "nv12" not in media_info
    ):
        raise ConversionError(
            "The final MP4 does not use a compatible "
            "4:2:0 pixel format."
        )

    if (
        "audio:" in media_info
        and "audio: aac" not in media_info
    ):
        raise ConversionError(
            "The final MP4 contains non-AAC audio."
        )

    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-f",
            "null",
            os.devnull,
        ]
    )

    if result.returncode != 0:
        details = (
            result.stderr
            or result.stdout
            or "FFmpeg returned no validation details."
        )

        raise ConversionError(
            "The completed MP4 could not be decoded fully.\n\n"
            f"{details}"
        )


def _common_command_prefix(
    ffmpeg: str,
    source: Path,
) -> list[str]:
    """Return FFmpeg arguments shared by both encoders."""
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-fflags",
        "+genpts+discardcorrupt",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
    ]


def _common_command_suffix(
    temporary: Path,
) -> list[str]:
    """Return FFmpeg output arguments shared by both encoders."""
    return [
        "-tag:v",
        "avc1",
        "-c:a",
        "aac",
        "-profile:a",
        "aac_low",
        "-b:a",
        "128k",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-avoid_negative_ts",
        "make_zero",
        "-max_muxing_queue_size",
        "4096",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(temporary),
    ]


def _qsv_command(
    ffmpeg: str,
    source: Path,
    temporary: Path,
    quality: int,
) -> list[str]:
    """Build an Intel Quick Sync H.264 conversion command."""
    return (
        _common_command_prefix(
            ffmpeg,
            source,
        )
        + [
            "-c:v",
            "h264_qsv",
            "-preset",
            "faster",
            "-global_quality",
            str(quality),
            "-profile:v",
            "main",
            "-vf",
            (
                "scale=trunc(iw/2)*2:"
                "trunc(ih/2)*2,"
                "format=nv12"
            ),
            "-fpsmax",
            "30",
        ]
        + _common_command_suffix(
            temporary
        )
    )


def _cpu_command(
    ffmpeg: str,
    source: Path,
    temporary: Path,
    preset: str,
    crf: int,
) -> list[str]:
    """Build the universal CPU H.264 fallback command."""
    return (
        _common_command_prefix(
            ffmpeg,
            source,
        )
        + [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-profile:v",
            "main",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-fpsmax",
            "30",
        ]
        + _common_command_suffix(
            temporary
        )
    )


def make_itunes_mp4(
    input_path: str | Path,
    *,
    ffmpeg_path: str | None = None,
    output_dir: str | Path | None = None,
    replace_source: bool = False,
    preset: str = "fast",
    crf: int = 23,
    qsv_quality: int = 25,
    on_status: StatusCallback | None = None,
    on_progress: ProgressCallback | None = None,
) -> str:
    """
    Convert one video into a validated H.264/AAC MP4.

    Intel Quick Sync is tried first. If it cannot encode a particular
    source, the function retries automatically with CPU libx264.

    Automatic downloads:
        output_dir=<Course/Week folder>
        replace_source=True

    Local conversions:
        replace_source=False
    """
    source = (
        Path(input_path)
        .expanduser()
        .resolve()
    )

    if not source.is_file():
        raise FileNotFoundError(
            "Input video was not found:\n"
            f"{source}"
        )

    destination = (
        Path(output_dir)
        .expanduser()
        .resolve()
        if output_dir is not None
        else source.parent
    )

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    if replace_source:
        # Automatic downloads keep one exact permanent MP4 filename.
        final_path = destination / f"{source.stem}.mp4"
    else:
        # Local conversions preserve the original file.
        final_path = _unique_output_path(
            destination,
            f"{source.stem} [Compatible]",
        )

    temporary = _temporary_path(
        final_path
    )

    ffmpeg = _resolve_ffmpeg(
        ffmpeg_path
    )

    qsv_command = _qsv_command(
        ffmpeg,
        source,
        temporary,
        qsv_quality,
    )

    cpu_command = _cpu_command(
        ffmpeg,
        source,
        temporary,
        preset,
        crf,
    )

    encoder_used = "Intel Quick Sync"

    try:
        if on_progress:
            on_progress(78.0)

        if on_status:
            on_status(
                "Converting with Intel Quick Sync..."
            )

        result = _run(
            qsv_command
        )

        if result.returncode != 0:
            qsv_details = (
                result.stderr
                or result.stdout
                or "No Quick Sync details were returned."
            )

            _remove_quietly(
                temporary
            )

            if on_status:
                on_status(
                    "Intel Quick Sync could not process this video. "
                    "Retrying with the CPU encoder..."
                )

            result = _run(
                cpu_command
            )

            encoder_used = "CPU libx264"

            if result.returncode != 0:
                cpu_details = (
                    result.stderr
                    or result.stdout
                    or "No CPU encoder details were returned."
                )

                raise ConversionError(
                    "Both hardware and CPU conversion failed.\n\n"
                    "Intel Quick Sync details:\n"
                    f"{qsv_details}\n\n"
                    "CPU encoder details:\n"
                    f"{cpu_details}"
                )

        if on_progress:
            on_progress(92.0)

        if on_status:
            on_status(
                "Validating the completed MP4..."
            )

        _validate(
            ffmpeg,
            temporary,
        )

        if on_progress:
            on_progress(98.0)

        # Publish only after conversion and validation both succeed.
        os.replace(
            temporary,
            final_path,
        )

        if (
            replace_source
            and source != final_path
        ):
            try:
                source.unlink()
            except OSError as exc:
                raise ConversionError(
                    "The final MP4 was created, but the temporary "
                    "source could not be removed:\n"
                    f"{source}\n\n"
                    f"{exc}"
                ) from exc

        if on_status:
            on_status(
                f"Compatible MP4 verified using {encoder_used}: "
                f"{final_path.name}"
            )

        if on_progress:
            on_progress(100.0)

        return str(final_path)

    finally:
        _remove_quietly(
            temporary
        )