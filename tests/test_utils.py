import subprocess
from pathlib import Path

import pytest

from floppy import utils


def test_append_encode_options_adds_quality_filter_and_metadata() -> None:
    encoder = utils.EncoderDefinition(
        codec="libx265",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        preset_options=["slow", "veryslow"],
        default_options={"preset": "veryslow"},
    )
    configuration = utils.EncodeConfiguration(name="libx265", encoder=encoder)

    result = utils.append_encode_options(
        configuration,
        resolution=720,
        quality=28,
        frame_rate=30,
        copy_metadata=True,
    )

    assert result is not configuration
    assert result.output_options == {
        "codec:v": "libx265",
        "map_metadata": "0",
        "map_chapters": "0",
        "preset": "veryslow",
        "vf": "fps=30,scale=-2:720",
        "crf": 28,
    }


def test_append_encode_options_overrides_preset() -> None:
    encoder = utils.EncoderDefinition(
        codec="libx265",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        preset_options=["fast", "medium", "slow"],
        default_preset="medium",
        default_options={"preset": "medium"},
    )
    configuration = utils.EncodeConfiguration(name="libx265", encoder=encoder)

    result = utils.append_encode_options(
        configuration,
        resolution=None,
        quality=28,
        preset="fast",
    )

    assert result.output_options["preset"] == "fast"


def test_append_encode_options_rejects_unsupported_preset() -> None:
    encoder = utils.EncoderDefinition(
        codec="libx265",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        preset_options=["fast"],
    )
    configuration = utils.EncodeConfiguration(name="libx265", encoder=encoder)

    with pytest.raises(ValueError, match="Unsupported preset"):
        utils.append_encode_options(
            configuration,
            resolution=None,
            quality=28,
            preset="slow",
        )


def test_append_encode_options_omits_filter_when_resolution_and_fps_unset() -> None:
    encoder = utils.EncoderDefinition(
        codec="hevc_vaapi",
        needs_hwupload=False,
        hwaccel="vaapi",
        quality_options=["qp"],
    )
    configuration = utils.EncodeConfiguration(name="vaapi", encoder=encoder)

    result = utils.append_encode_options(
        configuration,
        resolution=None,
        quality=None,
    )

    assert result.output_options == {"codec:v": "hevc_vaapi"}


def test_append_encode_options_uploads_for_hw_encoder() -> None:
    encoder = utils.EncoderDefinition(
        codec="hevc_vaapi",
        needs_hwupload=True,
        hwaccel="vaapi",
        quality_options=["qp"],
    )
    configuration = utils.EncodeConfiguration(name="vaapi", encoder=encoder)

    result = utils.append_encode_options(
        configuration,
        resolution=None,
        quality=24,
    )

    assert result.output_options["vf"] == "format=nv12,hwupload"
    assert result.output_options["qp"] == 24


def test_get_hevc_codecs_parses_ffmpeg_encoder_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = """
     V....D libx265              libx265 H.265 / HEVC
     V..... hevc_nvenc           NVIDIA NVENC hevc encoder
     A..... mp3                  MP3 audio
    """

    def fake_run_ffmpeg(
        args: list[str],
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert args == ["-encoders"]
        assert timeout is None
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(utils, "_run_ffmpeg", fake_run_ffmpeg)

    assert utils._get_hevc_codecs() == ["libx265", "hevc_nvenc"]


def test_copy_metadata_with_exiftool_uses_expected_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], float | None]] = []

    def fake_run_exiftool(
        args: list[str],
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args, timeout))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(utils, "_run_exiftool", fake_run_exiftool)

    utils.copy_metadata_with_exiftool(Path("input.mov"), Path("output.mov"))

    assert calls == [
        (
            [
                "-overwrite_original",
                "-TagsFromFile",
                "input.mov",
                "-all:all",
                "output.mov",
            ],
            None,
        )
    ]


def test_copy_metadata_with_exiftool_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_exiftool(
        args: list[str],
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(utils, "_run_exiftool", fake_run_exiftool)

    with pytest.raises(RuntimeError, match=utils.EXIFTOOL_METADATA_COPY_ERROR):
        utils.copy_metadata_with_exiftool("input.mov", "output.mov")


def test_ensure_exiftool_available_checks_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], float | None]] = []

    def fake_run_exiftool(
        args: list[str],
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args, timeout))
        return subprocess.CompletedProcess(args, 0, stdout="12.40", stderr="")

    monkeypatch.setattr(utils, "_run_exiftool", fake_run_exiftool)

    utils.ensure_exiftool_available()

    assert calls == [(["-ver"], None)]


def test_ensure_exiftool_available_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_exiftool(
        args: list[str],
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(utils, "_run_exiftool", fake_run_exiftool)

    with pytest.raises(RuntimeError, match=utils.EXIFTOOL_UNAVAILABLE_ERROR):
        utils.ensure_exiftool_available()


def test_get_frame_count_returns_error_for_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        utils,
        "_get_video_data",
        lambda filename, field: subprocess.CompletedProcess(
            [],
            0,
            stdout="N/A",
            stderr="",
        ),
    )

    assert utils.get_frame_count("input.mov") == utils.VIDEO_DATA_ERROR


def test_get_frame_rate_returns_error_for_zero_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        utils,
        "_get_video_data",
        lambda filename, field: subprocess.CompletedProcess(
            [],
            0,
            stdout="0/0",
            stderr="",
        ),
    )

    assert utils.get_frame_rate("input.mov") == utils.VIDEO_DATA_ERROR


def test_get_resolution_returns_error_for_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        utils,
        "_get_video_data",
        lambda filename, field: subprocess.CompletedProcess(
            [],
            0,
            stdout="N/A",
            stderr="",
        ),
    )

    assert utils.get_resolution("input.mov") == utils.VIDEO_DATA_ERROR


def test_collect_video_files_recursively_filters_and_sorts(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    first = folder / "b.MP4"
    second = nested / "a.mov"
    ignored = nested / "note.txt"
    first.write_text("")
    second.write_text("")
    ignored.write_text("")

    assert utils.collect_video_files(folder) == [first, second]


def test_get_preset_options_returns_copy() -> None:
    encoder = utils.EncoderDefinition(
        codec="libx265",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        preset_options=["fast", "medium"],
        default_preset="medium",
    )
    configuration = utils.EncodeConfiguration(name="libx265", encoder=encoder)

    presets = utils.get_preset_options(configuration)
    presets.append("slow")

    assert utils.get_preset_options(configuration) == ["fast", "medium"]
    assert utils.get_default_preset(configuration) == "medium"
