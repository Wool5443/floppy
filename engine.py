import asyncio
import subprocess
from pathlib import Path

from ffmpeg.asyncio import FFmpeg


async def reencode(filename, quality):
    input_path = Path(filename).absolute()
    directory = input_path.root
    suffix = input_path.suffix
    name = input_path.name.removesuffix(suffix)

    output_path = Path(f"{directory}/{name}_compressed{suffix}")

    ffmpeg = (
        FFmpeg()
        .option("y")
        .input(input_path.as_posix())
        .output(
            f"{output_path.as_posix()}",
            {"codec:v": "libx265"},
            preset="veryslow",
            crf=24,
        )
    )

    await ffmpeg.execute()


# if __name__ == "__main__":
#     asyncio.run(main())
