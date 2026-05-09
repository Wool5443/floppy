# Floppy

GTK4 video reencoder for HEVC compression with automatic FFmpeg encoder detection.

## Features

- Detects usable HEVC encoder on current machine.
- Prefers hardware encoders when available, falls back to `libx265`.
- Supports choosing or dragging multiple video files.
- Reencodes files sequentially.
- Optional quality, resolution, and maximum frame rate controls.
- Keeps source resolution/FPS when those controls are set to `0`.
- Shows per-file progress and batch count.

## Requirements

System packages on Fedora:

```bash
sudo dnf install ffmpeg gtk4 python3-gobject cairo-devel gobject-introspection-devel perl-Image-ExifTool
```

Python dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python app.py
```

## Usage

1. Open app.
2. Choose files or drag video files into window.
3. Set quality.
4. Optional: set output resolution. `0` keeps source size.
5. Optional: set maximum frame rate. `0` keeps source FPS.
6. Optional: enable `Copy metadata` to copy FFmpeg metadata plus ExifTool tags.
7. Press `Reencode`.

Output files are saved next to source files with `_compressed` added to filename.

## Encoder Detection

Encoder detection probes FFmpeg with a tiny generated HEVC encode. The first usable encoder is selected from:

```text
nvenc -> qsv -> vaapi -> amf -> vulkan -> libx265
```

Current encoder is printed when reencoding starts:

```text
Using hwaccel=None codec=libx265
```
