"""
app_gui_modern.py

A modern-ish Tkinter/ttk app with:
- Download tab (Course/Week/URLs) using yt-dlp + auto convert
- Local Convert tab (convert existing files on your PC)

Designed to work both:
- Running as python script
- Bundled with PyInstaller into a real app (.exe)

Uses sv_ttk dark theme.
"""
from __future__ import annotations

import importlib
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from converter import make_itunes_mp4
from downloader import download_video, normalize_url

#
# -----------------------------
# OPTIONAL sv_ttk IMPORT
# -----------------------------
# This avoids VS Code/Pylance complaining if sv_ttk is not installed yet.
try:
    sv_ttk = importlib.import_module("sv_ttk")
    HAS_SVTTK = True
except ModuleNotFoundError:
    sv_ttk = None
    HAS_SVTTK = False


# -----------------------------
# RESOURCE HELPERS
# -----------------------------
def script_dir() -> str:
    """Return this script's folder in normal Python mode."""
    return os.path.dirname(os.path.abspath(__file__))


def exe_dir() -> str:
    """Return EXE folder in PyInstaller mode, otherwise script folder."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return script_dir()


def resource_path(relative_path: str) -> str:
    """Return path to bundled PyInstaller resource or local file."""
    base_path = getattr(sys, "_MEIPASS", script_dir())
    return os.path.join(base_path, relative_path)


def pick_ffmpeg_path() -> str | None:
    """
    Find ffmpeg in this order:
    1) bundled inside PyInstaller
    2) next to the EXE/script
    3) system PATH
    """
    bundled = resource_path("ffmpeg.exe")
    if os.path.exists(bundled):
        return bundled

    local = os.path.join(exe_dir(), "ffmpeg.exe")
    if os.path.exists(local):
        return local

    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg:
        return path_ffmpeg

    return None


FFMPEG_PATH = pick_ffmpeg_path()


# -----------------------------
# STATUS HELPERS
# -----------------------------
def cookie_status_text() -> str:
    """Show whether cookies.txt exists next to the running app."""
    from downloader import cookies_path

    cpath = cookies_path()

    if os.path.exists(cpath):
        return f"Cookies file: ✅ Found ({cpath})"

    return f"Cookies file: ❌ Missing optional file\n{cpath}"


def ffmpeg_status_text() -> str:
    """Show whether ffmpeg was found."""
    if FFMPEG_PATH:
        return f"FFmpeg: ✅ Found ({FFMPEG_PATH})"
    return "FFmpeg: ❌ Missing"


def set_state(widget, enabled: bool) -> None:
    """Enable or disable a ttk widget."""
    widget.configure(state=("normal" if enabled else "disabled"))


# -----------------------------
# MAIN WINDOW
# -----------------------------
root = tk.Tk()
root.title("OneSydeDownloader")
root.geometry("920x720")
root.minsize(860, 640)

if HAS_SVTTK and sv_ttk is not None:
    sv_ttk.set_theme("dark")

root.option_add("*Font", "SegoeUI 10")

root.grid_rowconfigure(0, weight=1)
root.grid_columnconfigure(0, weight=1)

container = ttk.Frame(root, padding=14)
container.grid(row=0, column=0, sticky="nsew")
container.grid_rowconfigure(0, weight=1)
container.grid_columnconfigure(0, weight=1)

tabs = ttk.Notebook(container)
tabs.grid(row=0, column=0, sticky="nsew")

tab_download = ttk.Frame(tabs, padding=12)
tab_convert = ttk.Frame(tabs, padding=12)

tabs.add(tab_download, text="Download + Auto Convert")
tabs.add(tab_convert, text="Convert Local Videos")


# -----------------------------
# DOWNLOAD TAB VARIABLES
# -----------------------------
course_var = tk.StringVar()
week_var = tk.StringVar()
cookies_var = tk.BooleanVar(value=False)

filepct_var = tk.StringVar(value="File: 0%")
status_var = tk.StringVar(value="Ready.")
current_var = tk.StringVar(value="")

cookies_status_var = tk.StringVar(value=cookie_status_text())
ffmpeg_status_var = tk.StringVar(value=ffmpeg_status_text())


# -----------------------------
# DOWNLOAD TAB LAYOUT
# -----------------------------
tab_download.grid_columnconfigure(0, weight=1)
tab_download.grid_columnconfigure(1, weight=1)
tab_download.grid_rowconfigure(1, weight=1)

card_inputs = ttk.LabelFrame(tab_download, text="Class Info", padding=12)
card_inputs.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=(0, 10))
card_inputs.grid_columnconfigure(1, weight=1)

ttk.Label(card_inputs, text="Course (e.g., CIS175)").grid(row=0, column=0, sticky="w", pady=6)
entry_course = ttk.Entry(card_inputs, textvariable=course_var)
entry_course.grid(row=0, column=1, sticky="ew", pady=6)

ttk.Label(card_inputs, text="Week (e.g., Week 4)").grid(row=1, column=0, sticky="w", pady=6)
entry_week = ttk.Entry(card_inputs, textvariable=week_var)
entry_week.grid(row=1, column=1, sticky="ew", pady=6)

card_opts = ttk.LabelFrame(tab_download, text="Options", padding=12)
card_opts.grid(row=0, column=1, sticky="ew", pady=(0, 10))
card_opts.grid_columnconfigure(0, weight=1)

chk_cookies = ttk.Checkbutton(
    card_opts,
    text="Allow cookies fallback (only if needed)",
    variable=cookies_var,
)
chk_cookies.grid(row=0, column=0, sticky="w")

ttk.Label(
    card_opts,
    text="Tip: The app tries without cookies first. Only retries with cookies.txt if access is blocked.",
    wraplength=380,
    justify="left",
).grid(row=1, column=0, sticky="w", pady=(8, 4))

ttk.Label(card_opts, textvariable=cookies_status_var, wraplength=380, justify="left").grid(
    row=2,
    column=0,
    sticky="w",
    pady=(6, 0),
)

ttk.Label(card_opts, textvariable=ffmpeg_status_var, wraplength=380, justify="left").grid(
    row=3,
    column=0,
    sticky="w",
    pady=(6, 0),
)

card_urls = ttk.LabelFrame(tab_download, text="Video URLs (one per line)", padding=12)
card_urls.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
card_urls.grid_rowconfigure(0, weight=1)
card_urls.grid_columnconfigure(0, weight=1)

text_urls = tk.Text(card_urls, height=10, wrap="none", borderwidth=1, relief="solid")
text_urls.grid(row=0, column=0, sticky="nsew")
text_urls.configure(bg="#1e1e1e", fg="#e6e6e6", insertbackground="#e6e6e6")

scroll_y = ttk.Scrollbar(card_urls, orient="vertical", command=text_urls.yview)
scroll_y.grid(row=0, column=1, sticky="ns")
text_urls.configure(yscrollcommand=scroll_y.set)

card_prog = ttk.LabelFrame(tab_download, text="Progress", padding=12)
card_prog.grid(row=2, column=0, columnspan=2, sticky="ew")
card_prog.grid_columnconfigure(0, weight=1)

ttk.Label(card_prog, text="Current file").grid(row=0, column=0, sticky="w")

file_bar = ttk.Progressbar(card_prog, mode="determinate", maximum=100)
file_bar.grid(row=1, column=0, sticky="ew", pady=(4, 2))

ttk.Label(card_prog, textvariable=filepct_var).grid(row=2, column=0, sticky="w", pady=(0, 10))

ttk.Label(card_prog, text="Overall (files completed)").grid(row=3, column=0, sticky="w")

overall_bar = ttk.Progressbar(card_prog, mode="determinate")
overall_bar.grid(row=4, column=0, sticky="ew", pady=(4, 10))

ttk.Label(card_prog, textvariable=current_var, wraplength=860, justify="left").grid(
    row=5,
    column=0,
    sticky="w",
)

ttk.Label(card_prog, textvariable=status_var, wraplength=860, justify="left").grid(
    row=6,
    column=0,
    sticky="w",
)

buttons = ttk.Frame(tab_download)
buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
buttons.grid_columnconfigure(1, weight=1)

btn_clear = ttk.Button(buttons, text="Clear URLs")
btn_clear.grid(row=0, column=0, sticky="w")

ttk.Frame(buttons).grid(row=0, column=1, sticky="ew")

btn_start = ttk.Button(buttons, text="Start Download")
btn_start.grid(row=0, column=2, sticky="e")


def refresh_cookie_status() -> None:
    cookies_status_var.set(cookie_status_text())


def refresh_ffmpeg_status() -> None:
    global FFMPEG_PATH
    FFMPEG_PATH = pick_ffmpeg_path()
    ffmpeg_status_var.set(ffmpeg_status_text())


def clear_urls() -> None:
    text_urls.delete("1.0", tk.END)


def enable_download_controls(enabled: bool) -> None:
    set_state(btn_start, enabled)
    set_state(btn_clear, enabled)
    set_state(entry_course, enabled)
    set_state(entry_week, enabled)
    set_state(chk_cookies, enabled)


def start_download() -> None:
    refresh_cookie_status()
    refresh_ffmpeg_status()

    if not FFMPEG_PATH or not os.path.exists(FFMPEG_PATH):
        messagebox.showerror(
            "Missing FFmpeg",
            "FFmpeg was not found.\n\n"
            "Fix options:\n"
            "1. Install FFmpeg and add it to PATH.\n"
            "2. Put ffmpeg.exe next to OneSydeDownloader.exe.\n"
            "3. Bundle ffmpeg.exe into the PyInstaller build.",
            parent=root,
        )
        return

    urls = [normalize_url(u) for u in text_urls.get("1.0", tk.END).splitlines()]
    urls = [u for u in urls if u]

    course = entry_course.get().strip()
    week = entry_week.get().strip()
    use_cookies = cookies_var.get()

    missing = []
    if not course:
        missing.append("Course")
    if not week:
        missing.append("Week")
    if not urls:
        missing.append("At least one URL")

    if missing:
        messagebox.showerror("Error", "Missing: " + ", ".join(missing), parent=root)
        return

    enable_download_controls(False)

    overall_bar["value"] = 0
    overall_bar["maximum"] = len(urls)
    file_bar["value"] = 0
    filepct_var.set("File: 0%")
    current_var.set("")
    status_var.set("Starting download + conversion...")

    q: queue.Queue[tuple[str, object]] = queue.Queue()

    def on_status(msg: str) -> None:
        q.put(("status", msg))

    def on_current(url_: str) -> None:
        q.put(("current", url_))

    def on_progress(pct: float) -> None:
        q.put(("progress", pct))

    def on_item_done() -> None:
        q.put(("item_done", None))

    def worker() -> None:
        try:
            for url_ in urls:
                on_current(url_)
                on_progress(0.0)

                download_video(
                    url=url_,
                    course=course,
                    week=week,
                    use_cookies=use_cookies,
                    on_status=on_status,
                    on_progress=on_progress,
                    ffmpeg_path=FFMPEG_PATH,
                    download_subtitles=False,
                )

                on_item_done()

            q.put(("done", None))
        except Exception as e:  # noqa: BLE001
            q.put(("error", str(e)))

    def poll_queue() -> None:
        try:
            while True:
                typ, payload = q.get_nowait()

                if typ == "status":
                    status_var.set(str(payload))

                elif typ == "current":
                    current_var.set(f"Current URL: {payload}")
                    file_bar["value"] = 0
                    filepct_var.set("File: 0%")

                elif typ == "progress":
                    try:
                        pct = float(payload) # type: ignore
                    except (ValueError, TypeError):
                        pct = 0.0
                    pct = max(0.0, min(100.0, pct))
                    file_bar["value"] = pct
                    filepct_var.set(f"File: {pct:.1f}%")

                elif typ == "item_done":
                    overall_bar["value"] += 1
                    file_bar["value"] = 100
                    filepct_var.set("File: 100%")

                elif typ == "done":
                    enable_download_controls(True)
                    status_var.set("✅ All downloads completed.")
                    btn_start.configure(text="✅ Done!")
                    root.after(2000, lambda: btn_start.configure(text="Start Download"))
                    return

                elif typ == "error":
                    enable_download_controls(True)
                    status_var.set("Error occurred.")
                    messagebox.showerror("Download Error", str(payload), parent=root)
                    return

        except queue.Empty:
            pass

        root.after(100, poll_queue)

    threading.Thread(target=worker, daemon=True).start()
    poll_queue()


btn_start.configure(command=start_download)
btn_clear.configure(command=clear_urls)

refresh_cookie_status()
refresh_ffmpeg_status()


# -----------------------------
# LOCAL CONVERT TAB
# -----------------------------
tab_convert.grid_rowconfigure(1, weight=1)
tab_convert.grid_columnconfigure(0, weight=1)

ttk.Label(
    tab_convert,
    text=("Convert videos already saved on your computer into iPhone/iTunes-friendly MP4. "
          "The converted copy is saved beside the original file."),
    wraplength=860,
    justify="left",
).grid(row=0, column=0, sticky="w", pady=(0, 10))

conv_frame = ttk.LabelFrame(tab_convert, text="Files to Convert", padding=12)
conv_frame.grid(row=1, column=0, sticky="nsew")
conv_frame.grid_rowconfigure(0, weight=1)
conv_frame.grid_columnconfigure(0, weight=1)

lst_files = tk.Listbox(conv_frame, height=12)
lst_files.grid(row=0, column=0, sticky="nsew")
lst_files.configure(bg="#1e1e1e", fg="#e6e6e6", selectbackground="#2b579a")

conv_scroll = ttk.Scrollbar(conv_frame, orient="vertical", command=lst_files.yview)
conv_scroll.grid(row=0, column=1, sticky="ns")
lst_files.configure(yscrollcommand=conv_scroll.set)

conv_status_var = tk.StringVar(value="Ready.")

ttk.Label(tab_convert, textvariable=conv_status_var, wraplength=860, justify="left").grid(
    row=2,
    column=0,
    sticky="w",
    pady=(10, 0),
)

conv_btns = ttk.Frame(tab_convert)
conv_btns.grid(row=3, column=0, sticky="ew", pady=(10, 0))
conv_btns.grid_columnconfigure(1, weight=1)

btn_add_files = ttk.Button(conv_btns, text="Add Files")
btn_clear_files = ttk.Button(conv_btns, text="Clear List")
btn_convert_files = ttk.Button(conv_btns, text="Convert Selected / All")

btn_add_files.grid(row=0, column=0, sticky="w")
btn_clear_files.grid(row=0, column=1, sticky="w", padx=(10, 0))
btn_convert_files.grid(row=0, column=2, sticky="e")


def add_files() -> None:
    paths = filedialog.askopenfilenames(
        parent=root,
        title="Select video files to convert",
        filetypes=[
            ("Video files", "*.mp4 *.mkv *.mov *.webm *.avi *.m4v"),
            ("All files", "*.*"),
        ],
    )

    for p in paths:
        lst_files.insert(tk.END, p)


def clear_files() -> None:
    lst_files.delete(0, tk.END)


def enable_convert_controls(enabled: bool) -> None:
    set_state(btn_add_files, enabled)
    set_state(btn_clear_files, enabled)
    set_state(btn_convert_files, enabled)


def convert_files() -> None:
    refresh_ffmpeg_status()

    if not FFMPEG_PATH or not os.path.exists(FFMPEG_PATH):
        messagebox.showerror(
            "Missing FFmpeg",
            "FFmpeg was not found.\n\n"
            "Install FFmpeg, put ffmpeg.exe next to the EXE, or bundle it.",
            parent=root,
        )
        return

    selected = list(lst_files.curselection())

    if not selected:
        files = [lst_files.get(i) for i in range(lst_files.size())]
    else:
        files = [lst_files.get(i) for i in selected]

    if not files:
        messagebox.showwarning("No files", "Add files first.", parent=root)
        return

    enable_convert_controls(False)

    q: queue.Queue[tuple[str, object]] = queue.Queue()

    def w_status(msg: str) -> None:
        q.put(("status", msg))

    def worker() -> None:
        try:
            for idx, f in enumerate(files, start=1):
                w_status(f"Converting {idx}/{len(files)}: {os.path.basename(f)}")
                outp = make_itunes_mp4(
                    f,
                    ffmpeg_path=FFMPEG_PATH,
                    output_dir=os.path.dirname(f),
                    replace_source=False,
                )
                w_status(f"✅ Created: {os.path.basename(outp)}")

            q.put(("done", None))
        except Exception as e:  # noqa: BLE001
            q.put(("error", str(e)))

    def poll() -> None:
        try:
            while True:
                typ, payload = q.get_nowait()

                if typ == "status":
                    conv_status_var.set(str(payload))

                elif typ == "done":
                    conv_status_var.set("✅ All conversions completed.")
                    enable_convert_controls(True)
                    return

                elif typ == "error":
                    conv_status_var.set("Error occurred.")
                    enable_convert_controls(True)
                    messagebox.showerror("Conversion Error", str(payload), parent=root)
                    return

        except queue.Empty:
            pass

        root.after(120, poll)

    threading.Thread(target=worker, daemon=True).start()
    poll()


btn_add_files.configure(command=add_files)
btn_clear_files.configure(command=clear_files)
btn_convert_files.configure(command=convert_files)


def main() -> None:
    root.mainloop()


if __name__ == "__main__":
    main()