# Floppy

GTK4 video reencoder for HEVC compression with automatic FFmpeg encoder detection.

## Features

- Detects usable HEVC encoder on current machine.
- Prefers hardware encoders when available, falls back to `libx265`.
- Supports choosing files, choosing folders, or dragging video files.
- Reencodes files sequentially.
- Optional quality, encoder preset, resolution, and maximum frame rate controls.
- Optional output folder.
- Keeps source resolution/FPS when those controls are set to `0`.
- Can stop the current encode and skip the rest of the batch.
- Shows per-file progress, batch count, and estimated remaining time.

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
2. Choose files, choose a folder, or drag video files into window.
3. Set quality.
4. Optional: choose encoder preset.
5. Optional: choose output folder.
6. Optional: set output resolution. `0` keeps source size.
7. Optional: set maximum frame rate. `0` keeps source FPS.
8. Optional: enable `Copy metadata` to copy FFmpeg metadata plus ExifTool tags.
9. Press `Reencode`.

Folder selection scans recursively for common video files.
Press `Stop` to terminate the current FFmpeg process and skip remaining files.

Output files are saved next to source files by default, or into the selected output
folder, with `_compressed` added to filename. Existing output names get a numeric
suffix.

## Encoder Detection

Encoder detection probes FFmpeg with a tiny generated HEVC encode. The first usable encoder is selected from:

```text
nvenc -> qsv -> vaapi -> amf -> vulkan -> libx265
```

Current encoder is printed when reencoding starts:

```text
Using hwaccel=None codec=libx265
```
