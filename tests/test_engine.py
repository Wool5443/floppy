import asyncio
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from floppy import engine, utils


class FakeProgress:
    def __init__(self, frame: int) -> None:
        self.frame = frame
        self.time = timedelta(seconds=5)


class FakeFFmpeg:
    instances: list["FakeFFmpeg"] = []

    def __init__(self) -> None:
        self.input_path: str | None = None
        self.output_path: str | None = None
        self.output_options: utils.OutputOptions | None = None
        self.progress_handler: Callable[[FakeProgress], None] | None = None
        self.start_handler: Callable[[list[str]], None] | None = None
        self.terminated = False
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

    def on(self, event: str) -> Callable[[Callable[..., None]], None]:
        assert event in {"start", "progress"}

        def register(handler: Callable[..., None]) -> None:
            if event == "start":
                self.start_handler = handler
            else:
                self.progress_handler = handler

        return register

    async def execute(self) -> None:
        assert self.start_handler is not None
        self.start_handler([])
        assert self.progress_handler is not None
        self.progress_handler(FakeProgress(frame=25))

    def terminate(self) -> None:
        self.terminated = True


def use_fake_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    encoder = utils.EncoderDefinition(
        codec="libx265",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        speed_options={
            utils.ENCODE_SPEED_FAST: {"preset": "fast"},
            utils.ENCODE_SPEED_BALANCED: {"preset": "medium"},
            utils.ENCODE_SPEED_BEST_COMPRESSION: {"preset": "slow"},
        },
        default_options={"pix_fmt": "yuv420p10le"},
    )
    configuration = utils.EncodeConfiguration(name="libx265", encoder=encoder)

    monkeypatch.setattr(
        utils,
        "get_encode_configuration",
        lambda video_codec=utils.DEFAULT_VIDEO_CODEC: configuration,
    )
    monkeypatch.setattr(
        engine,
        "AVAILABLE_ENCODE_CONFIGURATIONS",
        {utils.DEFAULT_VIDEO_CODEC: [configuration]},
    )
    monkeypatch.setattr(engine, "ENCODE_CONFIGURATIONS", {})
    monkeypatch.setattr(engine, "FFmpeg", FakeFFmpeg)
    FakeFFmpeg.instances.clear()


def test_reencode_uses_selected_options_and_copies_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
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
        "pix_fmt": "yuv420p10le",
        "preset": "slow",
        "vf": "fps=30,scale=-2:720",
        "crf": 35,
    }
    assert output_path == input_path.absolute().with_name("video_compressed.mp4")
    assert metadata_copies == [(input_path.absolute(), output_path)]
    assert progress_values == [0.5]


def test_reencode_uses_selected_speed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)

    monkeypatch.setattr(utils, "get_resolution", lambda filename: 1080)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 60.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    asyncio.run(
        engine.reencode(
            tmp_path / "video.mov",
            quality=32,
            speed=utils.ENCODE_SPEED_FAST,
        )
    )

    assert FakeFFmpeg.instances[0].output_options["preset"] == "fast"


def test_reencode_uses_selected_av1_codec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    encoder = utils.EncoderDefinition(
        codec="libsvtav1",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        quality_max=63,
        speed_options={
            utils.ENCODE_SPEED_BALANCED: {"preset": "7"},
            utils.ENCODE_SPEED_BEST_COMPRESSION: {"preset": "4"},
        },
        default_options={"pix_fmt": "yuv420p10le"},
    )
    configuration = utils.EncodeConfiguration(name="libsvtav1", encoder=encoder)
    monkeypatch.setattr(
        utils,
        "get_encode_configuration",
        lambda video_codec=utils.DEFAULT_VIDEO_CODEC: configuration,
    )
    monkeypatch.setattr(
        engine,
        "AVAILABLE_ENCODE_CONFIGURATIONS",
        {utils.VIDEO_CODEC_AV1: [configuration]},
    )
    monkeypatch.setattr(engine, "ENCODE_CONFIGURATIONS", {})
    monkeypatch.setattr(engine, "FFmpeg", FakeFFmpeg)
    FakeFFmpeg.instances.clear()
    monkeypatch.setattr(utils, "get_resolution", lambda filename: 1080)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 60.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    asyncio.run(
        engine.reencode(
            tmp_path / "video.mov",
            quality=32,
            video_codec=utils.VIDEO_CODEC_AV1,
        )
    )

    assert FakeFFmpeg.instances[0].output_options == {
        "codec:v": "libsvtav1",
        "pix_fmt": "yuv420p10le",
        "preset": "4",
        "crf": 44,
    }


def test_reencode_uses_output_folder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    input_path = tmp_path / "input" / "video.mov"
    output_folder = tmp_path / "output"
    input_path.parent.mkdir()
    output_folder.mkdir()

    monkeypatch.setattr(utils, "get_resolution", lambda filename: 1080)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 60.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    output_path = asyncio.run(
        engine.reencode(
            input_path,
            quality=32,
            output_folder=output_folder,
        )
    )

    assert output_path == output_folder.absolute() / "video_compressed.mp4"
    assert FakeFFmpeg.instances[0].output_path == str(output_path)


def test_reencode_adds_suffix_when_output_folder_file_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    input_path = tmp_path / "video.mov"
    output_folder = tmp_path / "output"
    output_folder.mkdir()
    (output_folder / "video_compressed.mp4").write_text("")
    (output_folder / "video_compressed_2.mp4").write_text("")

    monkeypatch.setattr(utils, "get_resolution", lambda filename: 1080)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 60.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    output_path = asyncio.run(
        engine.reencode(
            input_path,
            quality=32,
            output_folder=output_folder,
        )
    )

    assert output_path == output_folder.absolute() / "video_compressed_3.mp4"
    assert FakeFFmpeg.instances[0].output_path == str(output_path)


def test_reencode_controller_terminates_active_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    controller = engine.ReencodeController()

    monkeypatch.setattr(utils, "get_resolution", lambda filename: 1080)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 60.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    def cancel_on_progress(_fraction: float) -> None:
        controller.cancel()

    with pytest.raises(engine.ReencodeStopped):
        asyncio.run(
            engine.reencode(
                tmp_path / "video.mov",
                quality=32,
                progress_callback=cancel_on_progress,
                controller=controller,
            )
        )

    assert FakeFFmpeg.instances[0].terminated is True


def test_reencode_does_not_start_when_controller_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    controller = engine.ReencodeController()
    controller.cancel()

    with pytest.raises(engine.ReencodeStopped):
        asyncio.run(
            engine.reencode(
                tmp_path / "video.mov",
                quality=32,
                controller=controller,
            )
        )

    assert FakeFFmpeg.instances == []


def test_reencode_does_not_start_when_metadata_copy_needs_missing_exiftool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
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
    use_fake_configuration(monkeypatch)
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
        "pix_fmt": "yuv420p10le",
        "preset": "slow",
        "crf": 36,
    }
    assert metadata_copies == []


def test_reencode_does_not_probe_encoder_on_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    monkeypatch.setattr(engine, "ENCODE_CONFIGURATIONS", {})
    monkeypatch.setattr(utils, "get_resolution", lambda filename: 720)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 24.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    asyncio.run(engine.reencode(tmp_path / "video.mov", quality=30))

    assert engine.ENCODE_CONFIGURATIONS[utils.DEFAULT_VIDEO_CODEC] is not None


def test_reencode_ignores_progress_callback_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    monkeypatch.setattr(utils, "get_resolution", lambda filename: 720)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 24.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    def fail_progress(_fraction: float) -> None:
        raise RuntimeError("progress failed")

    output_path = asyncio.run(
        engine.reencode(
            tmp_path / "video.mov",
            quality=30,
            progress_callback=fail_progress,
        )
    )

    assert output_path == (tmp_path / "video.mov").absolute().with_name(
        "video_compressed.mp4"
    )


def test_reencode_uses_duration_progress_when_frame_count_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    progress_values: list[float] = []
    monkeypatch.setattr(utils, "get_resolution", lambda filename: 720)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 24.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: utils.VIDEO_DATA_ERROR)
    monkeypatch.setattr(utils, "get_duration_seconds", lambda filename: 10.0)
    monkeypatch.setattr(utils, "get_real_frame_rate", lambda filename: utils.VIDEO_DATA_ERROR)

    asyncio.run(
        engine.reencode(
            tmp_path / "video.webm",
            quality=30,
            progress_callback=progress_values.append,
        )
    )

    assert progress_values == [0.5]


def test_reencode_estimates_frame_progress_when_frame_count_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    progress_values: list[float] = []
    monkeypatch.setattr(utils, "get_resolution", lambda filename: 720)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 24.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: utils.VIDEO_DATA_ERROR)
    monkeypatch.setattr(utils, "get_duration_seconds", lambda filename: 10.0)
    monkeypatch.setattr(utils, "get_real_frame_rate", lambda filename: 25.0)

    asyncio.run(
        engine.reencode(
            tmp_path / "video.webm",
            quality=30,
            progress_callback=progress_values.append,
        )
    )

    assert progress_values == [0.1]


def test_reencode_reports_source_size_and_fps_probe_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    status_messages: list[str] = []

    monkeypatch.setattr(utils, "get_resolution", lambda filename: utils.VIDEO_DATA_ERROR)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: utils.VIDEO_DATA_ERROR)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    asyncio.run(
        engine.reencode(
            tmp_path / "video.mov",
            quality=30,
            resolution=720,
            frame_rate=30,
            status_callback=status_messages.append,
        )
    )

    assert status_messages == [
        "Could not read source size/FPS, keeping source size/FPS",
    ]
    assert FakeFFmpeg.instances[0].output_options == {
        "codec:v": "libx265",
        "pix_fmt": "yuv420p10le",
        "preset": "slow",
        "crf": 36,
    }


def test_reencode_reports_source_fps_probe_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    status_messages: list[str] = []

    monkeypatch.setattr(utils, "get_resolution", lambda filename: 1080)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: utils.VIDEO_DATA_ERROR)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    asyncio.run(
        engine.reencode(
            tmp_path / "video.mov",
            quality=30,
            frame_rate=30,
            status_callback=status_messages.append,
        )
    )

    assert status_messages == ["Could not read source FPS, keeping source FPS"]


def test_reencode_ignores_status_callback_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_fake_configuration(monkeypatch)
    monkeypatch.setattr(utils, "get_resolution", lambda filename: utils.VIDEO_DATA_ERROR)
    monkeypatch.setattr(utils, "get_frame_rate", lambda filename: 24.0)
    monkeypatch.setattr(utils, "get_frame_count", lambda filename: 100)

    def fail_status(_message: str) -> None:
        raise RuntimeError("status failed")

    output_path = asyncio.run(
        engine.reencode(
            tmp_path / "video.mov",
            quality=30,
            resolution=720,
            status_callback=fail_status,
        )
    )

    assert output_path == (tmp_path / "video.mov").absolute().with_name(
        "video_compressed.mp4"
    )
