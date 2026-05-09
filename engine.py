import asyncio
from pathlib import Path
from typing import Union

from ffmpeg import Progress
from ffmpeg.asyncio import FFmpeg

import environment as e

ENCODE_CONFIGURATION = e.get_encode_configuration()

PathLike = Union[str, Path]


async def reencode(
    filename: PathLike,
    quality: int | None,
    resolution: int | None = None,
) -> None:
    encode_configuration = e.append_encode_options(
        ENCODE_CONFIGURATION,
        resolution=resolution,
        quality=quality,
    )

    input_path = Path(filename).absolute()
    suffix = input_path.suffix
    name = input_path.name.removesuffix(suffix)

    output_path = input_path.with_name(f"{name}_compressed{suffix}")

    ffmpeg = (
        FFmpeg()
        .option("y")
        .input(input_path.as_posix())
        .output(
            output_path.as_posix(),
            encode_configuration.output_options,
        )
    )

    frame_count = e.get_frame_count(input_path)

    @ffmpeg.on("progress")
    def on_progress(progress: Progress) -> None:
        p = progress.frame
        print(f"{p / frame_count * 100:0.2f}%")

    await ffmpeg.execute()


async def main() -> None:
    f = "IMG_7677.mov"
    await reencode(f, quality=40)


if __name__ == "__main__":
    asyncio.run(main())
