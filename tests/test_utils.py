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
        speed_options={
            utils.ENCODE_SPEED_BALANCED: {"preset": "medium"},
            utils.ENCODE_SPEED_BEST_COMPRESSION: {"preset": "slow"},
        },
        default_options={"pix_fmt": "yuv420p10le"},
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
        "pix_fmt": "yuv420p10le",
        "preset": "slow",
        "vf": "fps=30,scale=-2:720",
        "crf": 37,
    }


def test_append_encode_options_sets_speed_option() -> None:
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
    )
    configuration = utils.EncodeConfiguration(name="libx265", encoder=encoder)

    result = utils.append_encode_options(
        configuration,
        resolution=None,
        quality=28,
        speed=utils.ENCODE_SPEED_FAST,
    )

    assert result.output_options["preset"] == "fast"


def test_append_encode_options_uses_encoder_speed_option_name() -> None:
    encoder = utils.EncoderDefinition(
        codec="libaom-av1",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        speed_options={
            utils.ENCODE_SPEED_BALANCED: {"cpu-used": 5},
        },
        default_options={"cpu-used": 4, "b:v": 0},
    )
    configuration = utils.EncodeConfiguration(name="libaom-av1", encoder=encoder)

    result = utils.append_encode_options(
        configuration,
        resolution=None,
        quality=30,
        speed=utils.ENCODE_SPEED_BALANCED,
    )

    assert result.output_options["cpu-used"] == 5
    assert "preset" not in result.output_options


def test_append_encode_options_rejects_unsupported_speed() -> None:
    encoder = utils.EncoderDefinition(
        codec="libx265",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
    )
    configuration = utils.EncodeConfiguration(name="libx265", encoder=encoder)

    with pytest.raises(ValueError, match="Unsupported encode speed"):
        utils.append_encode_options(
            configuration,
            resolution=None,
            quality=28,
            speed="slow",
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

    assert result.output_options["vf"] == "format=p010,hwupload"
    assert result.output_options["qp"] == 39


def test_get_ffmpeg_video_encoders_parses_encoder_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = """
     V....D libx265              libx265 H.265 / HEVC
     V..... av1_nvenc            NVIDIA NVENC av1 encoder
     A..... mp3                  MP3 audio
    """

    monkeypatch.setattr(
        utils,
        "_run_ffmpeg",
        lambda args, timeout=None: subprocess.CompletedProcess(
            args,
            0,
            stdout=output,
            stderr="",
        ),
    )

    assert utils._get_ffmpeg_video_encoders() == ["libx265", "av1_nvenc"]


def test_get_available_encode_configurations_groups_by_codec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        utils,
        "_get_ffmpeg_video_encoders",
        lambda: ["hevc_vaapi", "libx265", "av1_nvenc", "libsvtav1"],
    )
    monkeypatch.setattr(utils, "_can_encode", lambda encoder: True)

    result = utils.get_available_encode_configurations()

    assert [configuration.name for configuration in result[utils.VIDEO_CODEC_HEVC]] == [
        "vaapi",
        "libx265",
    ]
    assert [configuration.name for configuration in result[utils.VIDEO_CODEC_AV1]] == [
        "nvenc",
        "libsvtav1",
    ]


def test_get_encode_configuration_selects_highest_priority_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        utils,
        "get_available_encode_configurations",
        lambda: {
            utils.VIDEO_CODEC_HEVC: [],
            utils.VIDEO_CODEC_AV1: [
                utils.EncodeConfiguration(
                    name="qsv",
                    encoder=utils.ENCODERS_BY_VIDEO_CODEC[utils.VIDEO_CODEC_AV1]["qsv"],
                )
            ],
        },
    )

    assert utils.get_encode_configuration(utils.VIDEO_CODEC_AV1).name == "qsv"


def test_select_default_video_codec_prefers_hardware() -> None:
    result = utils.select_default_video_codec(
        {
            utils.VIDEO_CODEC_HEVC: [
                utils.EncodeConfiguration(
                    name="libx265",
                    encoder=utils.ENCODERS_BY_VIDEO_CODEC[utils.VIDEO_CODEC_HEVC][
                        "libx265"
                    ],
                ),
            ],
            utils.VIDEO_CODEC_AV1: [
                utils.EncodeConfiguration(
                    name="vaapi",
                    encoder=utils.ENCODERS_BY_VIDEO_CODEC[utils.VIDEO_CODEC_AV1][
                        "vaapi"
                    ],
                ),
            ],
        }
    )

    assert result == utils.VIDEO_CODEC_AV1


def test_select_default_video_codec_falls_back_to_av1_without_hardware() -> None:
    result = utils.select_default_video_codec(
        {
            utils.VIDEO_CODEC_HEVC: [
                utils.EncodeConfiguration(
                    name="libx265",
                    encoder=utils.ENCODERS_BY_VIDEO_CODEC[utils.VIDEO_CODEC_HEVC][
                        "libx265"
                    ],
                ),
            ],
            utils.VIDEO_CODEC_AV1: [
                utils.EncodeConfiguration(
                    name="libsvtav1",
                    encoder=utils.ENCODERS_BY_VIDEO_CODEC[utils.VIDEO_CODEC_AV1][
                        "libsvtav1"
                    ],
                ),
            ],
        }
    )

    assert result == utils.VIDEO_CODEC_AV1


def test_select_default_video_codec_uses_hevc_when_only_hevc_available() -> None:
    result = utils.select_default_video_codec(
        {
            utils.VIDEO_CODEC_HEVC: [
                utils.EncodeConfiguration(
                    name="libx265",
                    encoder=utils.ENCODERS_BY_VIDEO_CODEC[utils.VIDEO_CODEC_HEVC][
                        "libx265"
                    ],
                ),
            ],
            utils.VIDEO_CODEC_AV1: [],
        }
    )

    assert result == utils.VIDEO_CODEC_HEVC


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


def test_get_duration_seconds_uses_format_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_get_format_data(
        filename: utils.PathLike,
        field: str,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((str(filename), field))
        return subprocess.CompletedProcess([], 0, stdout="12.5", stderr="")

    monkeypatch.setattr(utils, "_get_format_data", fake_get_format_data)

    assert utils.get_duration_seconds("input.webm") == 12.5
    assert calls == [("input.webm", "duration")]


def test_get_duration_seconds_returns_error_for_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        utils,
        "_get_format_data",
        lambda filename, field: subprocess.CompletedProcess(
            [],
            0,
            stdout="N/A",
            stderr="",
        ),
    )

    assert utils.get_duration_seconds("input.webm") == utils.VIDEO_DATA_ERROR


def test_get_real_frame_rate_uses_r_frame_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_get_video_data(
        filename: utils.PathLike,
        field: str,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((str(filename), field))
        return subprocess.CompletedProcess([], 0, stdout="30000/1001", stderr="")

    monkeypatch.setattr(utils, "_get_video_data", fake_get_video_data)

    assert utils.get_real_frame_rate("input.webm") == pytest.approx(29.97003)
    assert calls == [("input.webm", "r_frame_rate")]


def test_get_real_frame_rate_returns_error_for_zero_denominator(
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

    assert utils.get_real_frame_rate("input.webm") == utils.VIDEO_DATA_ERROR


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


def test_map_user_quality_inverts_for_backend_quality() -> None:
    encoder = utils.EncoderDefinition(
        codec="libx265",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
    )

    assert utils.map_user_quality(encoder, 100) == 1
    assert utils.map_user_quality(encoder, 60) == 21
    assert utils.map_user_quality(encoder, 1) == 51


def test_map_user_quality_clamps_to_user_range() -> None:
    encoder = utils.EncoderDefinition(
        codec="libsvtav1",
        needs_hwupload=False,
        hwaccel=None,
        quality_options=["crf"],
        quality_max=63,
    )

    assert utils.map_user_quality(encoder, 200) == 1
    assert utils.map_user_quality(encoder, -10) == 63
