# Floppy

GTK4 video reencoder for HEVC or AV1 compression with automatic FFmpeg encoder detection.

## Features

- Detects usable HEVC and AV1 encoders on current machine.
- Prefers hardware encoders when available, falls back to software encoders.
- Supports choosing files/folders or dragging video files/folders.
- Reencodes files sequentially.
- Optional codec, quality, encoder preset, resolution, and maximum frame rate controls.
- Optional output folder.
- Keeps source resolution/FPS when those controls are set to `0`.
- Shows available acceleration for HEVC and AV1 before encoding.
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
python -m floppy.app
```

## Usage

1. Open app.
2. Choose input files/folder, or drag video files/folders into window.
3. Set quality.
4. Choose HEVC or AV1 codec.
5. Optional: choose encoder preset.
6. Optional: choose output folder.
7. Optional: set output resolution. `0` keeps source size.
8. Optional: set maximum frame rate. `0` keeps source FPS.
9. Optional: enable `Copy metadata` to copy FFmpeg metadata plus ExifTool tags.
10. Press `Reencode`.

Folder selection scans recursively for common video files.
Press `Stop` to terminate the current FFmpeg process and skip remaining files.

Output files are saved as `.mp4` next to source files by default, or into the
selected output folder, with `_compressed` added to filename. Existing output
names get a numeric suffix.

## Encoder Detection

Encoder detection probes FFmpeg with a tiny generated encode for each candidate.
The first usable encoder is selected from:

```text
HEVC: nvenc -> qsv -> vaapi -> amf -> vulkan -> libx265
AV1:  nvenc -> qsv -> vaapi -> amf -> libsvtav1 -> libaom-av1 -> librav1e
```

Current encoder is printed when reencoding starts:

```text
Using video_codec=hevc hwaccel=None codec=libx265
```
