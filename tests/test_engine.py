import asyncio
import importlib
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import utils


class FakeProgress:
    def __init__(self, frame: int) -> None:
        self.frame = frame


class FakeFFmpeg:
    instances: list["FakeFFmpeg"] = []

    def __init__(self) -> None:
        self.input_path: str | None = None
        self.output_path: str | None = None
        self.output_options: utils.OutputOptions | None = None
        self.progress_handler: Callable[[FakeProgress], None] | None = None
        FakeFFmpeg.instances.append(self)

    def option(self, option: str) -> "FakeFFmpeg":
        assert option == "y"
        return self

    def input(self, input_path: str) -> "FakeFFmpeg":
        self.input_path = input_path
        return self

    def output(
        self,
        output_path: str,
        output_options: utils.OutputOptions,
    ) -> "FakeFFmpeg":
        self.output_path = output_path
        self.output_options = output_options
        return self

    def on(self, event: str) -> Callable[[Callable[[FakeProgress], None]], None]:
        assert event == "progress"

        def register(handler: Callable[[FakeProgress], None]) -> None:
            self.progress_handler = handler

        return register

    async def execute(self) -> None:
        assert self.progress_handler is not None
        self.progress_handler(FakeProgress(frame=25))


def import_engine_with_fake_configuration(monkeypatch: pytest.MonkeyPatch):
    encoder = utils.EncoderDefinition(
        codec="libx265",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        default_options={"preset": "veryslow"},
    )
    configuration = utils.EncodeConfiguration(name="libx265", encoder=encoder)

    monkeypatch.setattr(utils, "get_encode_configuration", lambda: configuration)
    sys.modules.pop("engine", None)
    engine = importlib.import_module("engine")
    monkeypatch.setattr(engine, "FFmpeg", FakeFFmpeg)
    FakeFFmpeg.instances.clear()
    return engine


def test_reencode_uses_selected_options_and_copies_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = import_engine_with_fake_configuration(monkeypatch)
    input_path = tmp_path / "video.mov"
    metadata_copies: list[tuple[Path, Path]] = []
    progress_values: list[float] = []

    monkeypatch.setattr(utils, "get_resolution", lambda filename: 1080)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 60.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)
    monkeypatch.setattr(utils, "ensure_exiftool_available", lambda: None)
    monkeypatch.setattr(
        utils,
        "copy_metadata_with_exiftool",
        lambda source, output: metadata_copies.append((source, output)),
    )

    output_path = asyncio.run(
        engine.reencode(
            input_path,
            quality=32,
            resolution=720,
            frame_rate=30,
            copy_metadata=True,
            progress_callback=progress_values.append,
        )
    )

    ffmpeg = FakeFFmpeg.instances[0]
    assert ffmpeg.input_path == str(input_path.absolute())
    assert ffmpeg.output_path == str(output_path)
    assert ffmpeg.output_options == {
        "codec:v": "libx265",
        "map_metadata": "0",
        "map_chapters": "0",
        "preset": "veryslow",
        "vf": "fps=30,scale=-2:720",
        "crf": 32,
    }
    assert output_path == input_path.absolute().with_stem("video_compressed")
    assert metadata_copies == [(input_path.absolute(), output_path)]
    assert progress_values == [0.5]


def test_reencode_does_not_start_when_metadata_copy_needs_missing_exiftool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = import_engine_with_fake_configuration(monkeypatch)
    input_path = tmp_path / "video.mov"

    def fail_exiftool_check() -> None:
        raise RuntimeError(utils.EXIFTOOL_UNAVAILABLE_ERROR)

    monkeypatch.setattr(utils, "ensure_exiftool_available", fail_exiftool_check)
    monkeypatch.setattr(utils, "get_resolution", lambda filename: 1080)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 60.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    with pytest.raises(RuntimeError, match=utils.EXIFTOOL_UNAVAILABLE_ERROR):
        asyncio.run(
            engine.reencode(
                input_path,
                quality=32,
                copy_metadata=True,
            )
        )

    assert FakeFFmpeg.instances == []


def test_reencode_keeps_source_resolution_and_fps_when_limits_are_higher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = import_engine_with_fake_configuration(monkeypatch)
    input_path = tmp_path / "video.mov"
    metadata_copies: list[tuple[Path, Path]] = []

    monkeypatch.setattr(utils, "get_resolution", lambda filename: 720)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 24.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)
    monkeypatch.setattr(
        utils,
        "copy_metadata_with_exiftool",
        lambda source, output: metadata_copies.append((source, output)),
    )

    asyncio.run(
        engine.reencode(
            input_path,
            quality=30,
            resolution=1080,
            frame_rate=60,
            copy_metadata=False,
        )
    )

    ffmpeg = FakeFFmpeg.instances[0]
    assert ffmpeg.output_options == {
        "codec:v": "libx265",
        "preset": "veryslow",
        "crf": 30,
    }
    assert metadata_copies == []
