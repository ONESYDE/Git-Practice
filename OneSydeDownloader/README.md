# OneSydeDownloader

OneSydeDownloader is a Windows desktop application for downloading authorized
video content and automatically converting it into a broadly compatible MP4
format.

The application organizes videos by course and week, supports individual video
URLs and Kaltura playlist embeds, and removes temporary raw files after a
successful conversion.

## Features

- Modern dark-mode Tkinter interface
- Download and conversion in one automatic workflow
- Multiple URLs supported, one URL per line
- Kaltura individual-entry support
- Kaltura playlist and legacy embed-link support
- Course and week folder organization
- Optional `cookies.txt` authentication fallback
- Intel Quick Sync hardware acceleration
- Automatic CPU encoding fallback
- H.264/AVC video output
- AAC-LC audio output
- MP4 validation before temporary files are removed
- Local video conversion tab
- PyInstaller-compatible resource detection

## Download Workflow

For each video, the application performs the following process:

```text
Resolve URL
    ↓
Download to a temporary working folder
    ↓
Convert to H.264/AAC MP4
    ↓
Validate the completed MP4
    ↓
Move the MP4 into the Course/Week folder
    ↓
Remove the temporary raw download
```

A permanent raw duplicate is not retained after successful conversion and
validation.

## Output Location

Downloaded videos are organized under:

```text
C:\Users\<username>\Downloads\OneSydeDownloader
```

Example:

```text
OneSydeDownloader
└── CIS333
    └── WEEK 3
        ├── Lab 4.6.4 Create New User.mp4
        ├── Lab 4.6.5 Rename a User Account.mp4
        └── Lab 4.6.6 Delete a User Account.mp4
```

## Supported URLs

The application supports URLs recognized by `yt-dlp`, including tested Kaltura
formats such as:

- Individual Kaltura entry URLs
- Kaltura `playlist_id` URLs
- Legacy Kaltura playlist embed URLs containing:

```text
flashvars[playlistAPI.kpl0Id]
```

A Kaltura playlist is resolved into its individual video entries. Each entry is
downloaded, converted, validated, and cleaned up before the next entry begins.

## Video Format

Completed files use the following compatibility profile:

```text
Container: MP4
Video: H.264/AVC
Video tag: avc1
Pixel format: yuv420p or NV12
Maximum frame rate: 30 FPS
Audio: AAC-LC
Audio bitrate: 128 kbps
Fast-start metadata: Enabled
```

The application attempts Intel Quick Sync hardware encoding first. When Quick
Sync cannot process a video, it automatically retries with the `libx264` CPU
encoder.

## Requirements

- Windows
- A recent Python 3 installation
- FFmpeg
- Python packages listed in `requirements.txt`

Install the Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Place `ffmpeg.exe` beside the Python files or make FFmpeg available through the
system PATH.

## Running the Application

From the `OneSydeDownloader` project folder:

```powershell
python app_gui_modern.py
```

When using a virtual environment:

```powershell
.\.venv\Scripts\python.exe app_gui_modern.py
```

## Using the Download Tab

1. Enter the course name.
2. Enter the week name.
3. Paste one authorized video URL per line.
4. Leave cookies fallback disabled unless the website requires authentication.
5. Select **Start Download**.
6. Wait for downloading, conversion, and validation to complete.

Do not open a file as soon as the download progress reaches 100%. The
application still needs to convert and validate the video before reporting
completion.

## Optional Cookies Authentication

Some authorized videos may require an authenticated browser session.

When needed:

1. Export your authorized browser cookies to `cookies.txt`.
2. Place `cookies.txt` beside the application.
3. Enable **Allow cookies fallback**.
4. Retry the download.

The application attempts downloading without cookies first.

## Privacy and Repository Safety

The following files must never be committed to GitHub:

```text
cookies.txt
ffmpeg.exe
downloaded videos
.venv
.onesyde-working
build
dist
```

These files are excluded by the repository's `.gitignore`.

Authentication cookies may contain private session information. Never share or
publish them.

## Authorized Use

OneSydeDownloader is intended only for media that the user owns or is
authorized to download.

Users are responsible for complying with:

- Copyright laws
- Website terms of service
- Institutional policies
- Course-content restrictions
- Access-control requirements

This project is not intended to bypass digital rights management or obtain
content without authorization.

## Project Files

```text
OneSydeDownloader
├── app_gui_modern.py
├── converter.py
├── downloader.py
├── requirements.txt
└── README.md
```

### `app_gui_modern.py`

Provides the Tkinter desktop interface, download queue, progress display, local
conversion controls, and FFmpeg detection.

### `downloader.py`

Normalizes URLs, resolves Kaltura playlists, downloads videos through `yt-dlp`,
handles optional cookies, and manages temporary working folders.

### `converter.py`

Converts downloaded or local videos into validated H.264/AAC MP4 files using
Intel Quick Sync with an automatic CPU fallback.

## Current Status

The application currently supports:

- Successful Kaltura playlist resolution
- Sequential download and conversion
- Hardware-accelerated encoding
- CPU fallback encoding
- Automatic temporary-file cleanup
- Course and week organization
- Validated MP4 output