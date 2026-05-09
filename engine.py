import asyncio
from collections.abc import Callable
from pathlib import Path

from ffmpeg import Progress
from ffmpeg.asyncio import FFmpeg

import utils as u

ENCODE_CONFIGURATION = u.get_encode_configuration()
DEFAULT_SAMPLE_QUALITY = 40
DEFAULT_SAMPLE_FILE = "IMG_7677.mov"
MIN_PROGRESS_FRAME_COUNT = 1
ProgressCallback = Callable[[float], None]


async def reencode(
    filename: u.PathLike,
    quality: int | None,
    resolution: int | None = None,
    frame_rate: float | None = None,
    copy_metadata: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    input_path = Path(filename).absolute()

    if copy_metadata:
        u.ensure_exiftool_available()

    source_resolution = u.get_resolution(input_path)
    source_frame_rate = u.get_frame_rate(input_path)
    output_resolution = None
    output_frame_rate = None

    if frame_rate is not None and source_frame_rate > frame_rate:
        output_frame_rate = frame_rate

    if resolution is not None and source_resolution > resolution:
        output_resolution = resolution

    encode_configuration = u.append_encode_options(
        ENCODE_CONFIGURATION,
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
            progress_callback(done)
        else:
            print(f"{done * 100:0.2f}%")

    await ffmpeg.execute()

    if copy_metadata:
        u.copy_metadata_with_exiftool(input_path, output_path)

    return output_path


async def main() -> None:
    await reencode(DEFAULT_SAMPLE_FILE, quality=DEFAULT_SAMPLE_QUALITY)


if __name__ == "__main__":
    asyncio.run(main())
