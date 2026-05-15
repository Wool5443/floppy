import asyncio
from collections.abc import Callable
from pathlib import Path
from sys import stderr
from threading import Lock
from typing import Any

from ffmpeg import Progress
from ffmpeg.asyncio import FFmpeg

import utils as u

ENCODE_CONFIGURATION: u.EncodeConfiguration | None = None
MIN_PROGRESS_FRAME_COUNT = 1
ProgressCallback = Callable[[float], None]
StatusCallback = Callable[[str], None]
OUTPUT_SUFFIX = "_compressed"


class ReencodeStopped(Exception):
    pass


class ReencodeController:
    def __init__(self) -> None:
        self._cancelled = False
        self._ffmpeg: Any | None = None
        self._lock = Lock()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def set_active_ffmpeg(self, ffmpeg: Any) -> None:
        with self._lock:
            self._ffmpeg = ffmpeg
            cancelled = self._cancelled

        if cancelled:
            self._terminate(ffmpeg)

    def clear_active_ffmpeg(self, ffmpeg: Any) -> None:
        with self._lock:
            if self._ffmpeg is ffmpeg:
                self._ffmpeg = None

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            ffmpeg = self._ffmpeg

        if ffmpeg is not None:
            self._terminate(ffmpeg)

    def _terminate(self, ffmpeg: Any) -> None:
        try:
            ffmpeg.terminate()
        except Exception as error:
            print(f"Could not terminate FFmpeg: {error}", file=stderr)


def get_encode_configuration() -> u.EncodeConfiguration:
    global ENCODE_CONFIGURATION

    if ENCODE_CONFIGURATION is None:
        ENCODE_CONFIGURATION = u.get_encode_configuration()

    return ENCODE_CONFIGURATION


async def reencode(
    filename: u.PathLike,
    quality: int | None,
    resolution: int | None = None,
    frame_rate: float | None = None,
    copy_metadata: bool = False,
    progress_callback: ProgressCallback | None = None,
    status_callback: StatusCallback | None = None,
    preset: str | None = None,
    controller: ReencodeController | None = None,
    output_folder: u.PathLike | None = None,
) -> Path:
    if controller is not None and controller.cancelled:
        raise ReencodeStopped

    input_path = Path(filename).absolute()

    if copy_metadata:
        u.ensure_exiftool_available()

    source_resolution = u.get_resolution(input_path)
    source_frame_rate = u.get_frame_rate(input_path)
    output_resolution = None
    output_frame_rate = None

    source_resolution_failed = source_resolution == u.VIDEO_DATA_ERROR
    source_frame_rate_failed = source_frame_rate == u.VIDEO_DATA_ERROR

    if (
        resolution is not None
        and frame_rate is not None
        and source_resolution_failed
        and source_frame_rate_failed
    ):
        _send_status(
            status_callback,
            "Could not read source size/FPS, keeping source size/FPS",
        )
    elif resolution is not None and source_resolution_failed:
        _send_status(status_callback, "Could not read source size, keeping source size")
    elif frame_rate is not None and source_frame_rate_failed:
        _send_status(status_callback, "Could not read source FPS, keeping source FPS")

    if frame_rate is not None and source_frame_rate > frame_rate:
        output_frame_rate = frame_rate

    if resolution is not None and source_resolution > resolution:
        output_resolution = resolution

    encode_configuration = u.append_encode_options(
        get_encode_configuration(),
        resolution=output_resolution,
        quality=quality,
        frame_rate=output_frame_rate,
        copy_metadata=copy_metadata,
        preset=preset,
    )
    print(
        "Using "
        f"hwaccel={encode_configuration.encoder.hwaccel} "
        f"codec={encode_configuration.encoder.codec}"
    )

    output_path = _output_path(input_path, output_folder)

    ffmpeg = (
        FFmpeg()
        .option("y")
        .input(str(input_path))
        .output(
            str(output_path),
            encode_configuration.output_options,
        )
    )
    if controller is not None:
        controller.set_active_ffmpeg(ffmpeg)
        if controller.cancelled:
            controller.clear_active_ffmpeg(ffmpeg)
            raise ReencodeStopped

    @ffmpeg.on("start")
    def on_start(_arguments: list[str]) -> None:  # pyright: ignore[reportUnusedFunction]
        if controller is not None and controller.cancelled:
            controller.cancel()

    frame_count = u.get_frame_count(input_path)
    progress_frame_count = frame_count

    if output_frame_rate is not None and source_frame_rate > 0:
        progress_frame_count = int(frame_count * output_frame_rate / source_frame_rate)

    @ffmpeg.on("progress")
    def on_progress(progress: Progress) -> None:  # pyright: ignore[reportUnusedFunction]
        if progress_frame_count < MIN_PROGRESS_FRAME_COUNT:
            return

        p = progress.frame
        done = p / progress_frame_count

        if progress_callback is not None:
            try:
                progress_callback(done)
            except Exception as error:
                print(f"Progress callback failed: {error}", file=stderr)
        else:
            print(f"{done * 100:0.2f}%")

    try:
        await ffmpeg.execute()
    finally:
        if controller is not None:
            controller.clear_active_ffmpeg(ffmpeg)

    if controller is not None and controller.cancelled:
        raise ReencodeStopped

    if copy_metadata:
        u.copy_metadata_with_exiftool(input_path, output_path)

    return output_path


def _send_status(status_callback: StatusCallback | None, message: str) -> None:
    if status_callback is None:
        print(message)
        return

    try:
        status_callback(message)
    except Exception as error:
        print(f"Status callback failed: {error}", file=stderr)


def _output_path(input_path: Path, output_folder: u.PathLike | None) -> Path:
    suffix = input_path.suffix
    name = input_path.name.removesuffix(suffix)

    if output_folder is None:
        return input_path.with_stem(f"{name}{OUTPUT_SUFFIX}")

    folder = Path(output_folder).absolute()
    output_path = folder / f"{name}{OUTPUT_SUFFIX}{suffix}"

    if not output_path.exists():
        return output_path

    counter = 2
    while True:
        candidate = folder / f"{name}{OUTPUT_SUFFIX}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
