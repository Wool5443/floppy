import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from ffmpeg import Progress
from ffmpeg.asyncio import FFmpeg

from . import utils as u

logger = logging.getLogger(__name__)
AVAILABLE_ENCODE_CONFIGURATIONS: dict[str, list[u.EncodeConfiguration]] | None = None
ENCODE_CONFIGURATIONS: dict[str, u.EncodeConfiguration] = {}
MIN_PROGRESS_FRAME_COUNT = 1
ProgressCallback = Callable[[float], None]
StatusCallback = Callable[[str], None]
OUTPUT_SUFFIX = "_compressed"
OUTPUT_EXTENSION = ".mp4"


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
            logger.warning("Could not terminate FFmpeg: %s", error)


def get_available_encode_configurations() -> dict[str, list[u.EncodeConfiguration]]:
    global AVAILABLE_ENCODE_CONFIGURATIONS

    if AVAILABLE_ENCODE_CONFIGURATIONS is None:
        AVAILABLE_ENCODE_CONFIGURATIONS = u.get_available_encode_configurations()

    return AVAILABLE_ENCODE_CONFIGURATIONS


def get_encode_configuration(
    video_codec: str = u.DEFAULT_VIDEO_CODEC,
) -> u.EncodeConfiguration:
    if video_codec not in ENCODE_CONFIGURATIONS:
        configurations = get_available_encode_configurations().get(video_codec, [])
        if not configurations:
            ENCODE_CONFIGURATIONS[video_codec] = u.get_encode_configuration(video_codec)
        else:
            ENCODE_CONFIGURATIONS[video_codec] = configurations[0]

    return ENCODE_CONFIGURATIONS[video_codec]


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
    video_codec: str = u.DEFAULT_VIDEO_CODEC,
) -> Path:
    if controller is not None and controller.cancelled:
        logger.info("Reencode skipped because controller is already cancelled")
        raise ReencodeStopped

    input_path = Path(filename).absolute()

    if copy_metadata:
        logger.info("Checking ExifTool before metadata copy")
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
        logger.warning("Could not read source size/FPS for %s", input_path)
        _send_status(
            status_callback,
            "Could not read source size/FPS, keeping source size/FPS",
        )
    elif resolution is not None and source_resolution_failed:
        logger.warning("Could not read source size for %s", input_path)
        _send_status(status_callback, "Could not read source size, keeping source size")
    elif frame_rate is not None and source_frame_rate_failed:
        logger.warning("Could not read source FPS for %s", input_path)
        _send_status(status_callback, "Could not read source FPS, keeping source FPS")

    if frame_rate is not None and source_frame_rate > frame_rate:
        output_frame_rate = frame_rate

    if resolution is not None and source_resolution > resolution:
        output_resolution = resolution

    encode_configuration = u.append_encode_options(
        get_encode_configuration(video_codec),
        resolution=output_resolution,
        quality=quality,
        frame_rate=output_frame_rate,
        copy_metadata=copy_metadata,
        preset=preset,
    )
    logger.info(
        "Using video_codec=%s hwaccel=%s codec=%s",
        video_codec,
        encode_configuration.encoder.hwaccel,
        encode_configuration.encoder.codec,
    )

    output_path = _output_path(input_path, output_folder)
    logger.info("Reencoding %s to %s", input_path, output_path)

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
            logger.info("Reencode stopped before FFmpeg start: %s", input_path)
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
                logger.warning("Progress callback failed: %s", error)
        else:
            logger.debug("Progress for %s: %.2f%%", input_path, done * 100)

    try:
        await ffmpeg.execute()
    finally:
        if controller is not None:
            controller.clear_active_ffmpeg(ffmpeg)

    if controller is not None and controller.cancelled:
        logger.info("Reencode stopped: %s", input_path)
        raise ReencodeStopped

    if copy_metadata:
        logger.info("Copying metadata to %s", output_path)
        u.copy_metadata_with_exiftool(input_path, output_path)

    logger.info("Finished reencoding %s", output_path)
    return output_path


def _send_status(status_callback: StatusCallback | None, message: str) -> None:
    if status_callback is None:
        logger.info(message)
        return

    try:
        status_callback(message)
    except Exception as error:
        logger.warning("Status callback failed: %s", error)


def _output_path(input_path: Path, output_folder: u.PathLike | None) -> Path:
    name = input_path.name.removesuffix(input_path.suffix)

    if output_folder is None:
        return input_path.with_name(f"{name}{OUTPUT_SUFFIX}{OUTPUT_EXTENSION}")

    folder = Path(output_folder).absolute()
    output_path = folder / f"{name}{OUTPUT_SUFFIX}{OUTPUT_EXTENSION}"

    if not output_path.exists():
        return output_path

    counter = 2
    while True:
        candidate = folder / f"{name}{OUTPUT_SUFFIX}_{counter}{OUTPUT_EXTENSION}"
        if not candidate.exists():
            return candidate
        counter += 1
