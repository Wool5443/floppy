import asyncio
from pathlib import Path

from ffmpeg.asyncio import FFmpeg

from environment import append_encode_options, get_encode_configuration

ENCODE_CONFIGURATION = get_encode_configuration()


async def reencode(filename, quality, resolution=None):
    encode_configuration = append_encode_options(
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
            encode_configuration["output_options"],
        )
    )

    await ffmpeg.execute()


async def main():
    await reencode("Default.mp4", quality=40)


if __name__ == "__main__":
    asyncio.run(main())
