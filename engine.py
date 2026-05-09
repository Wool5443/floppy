import asyncio
from collections.abc import Callable
from pathlib import Path
from sys import stderr

from ffmpeg import Progress
from ffmpeg.asyncio import FFmpeg

import utils as u

ENCODE_CONFIGURATION: u.EncodeConfiguration | None = None
MIN_PROGRESS_FRAME_COUNT = 1
ProgressCallback = Callable[[float], None]
StatusCallback = Callable[[str], None]


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
) -> Path:
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
    )
    print(
        "Using "
        f"hwaccel={encode_configuration.encoder.hwaccel} "
        f"codec={encode_configuration.encoder.codec}"
    )

    suffix = input_path.suffix
    name = input_path.name.removesuffix(suffix)

    output_path = input_path.with_stem(f"{name}_compressed")

    ffmpeg = (
        FFmpeg()
        .option("y")
        .input(str(input_path))
        .output(
            str(output_path),
            encode_configuration.output_options,
        )
    )

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

    await ffmpeg.execute()

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
