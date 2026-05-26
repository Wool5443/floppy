import logging
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

OptionValue = str | int | float | bool | None
OutputOptions = dict[str, OptionValue]
PathLike = str | Path
logger = logging.getLogger(__name__)


@dataclass
class EncoderDefinition:
    codec: str
    needs_hwupload: bool
    hwaccel: str | None
    quality_options: list[str]
    quality_min: int = 1
    quality_max: int = 51
    speed_options: dict[str, OutputOptions] = field(default_factory=dict)
    default_options: OutputOptions = field(default_factory=dict)


@dataclass
class EncodeConfiguration:
    name: str
    encoder: EncoderDefinition
    output_options: OutputOptions = field(default_factory=dict)


VIDEO_CODEC_HEVC = "hevc"
VIDEO_CODEC_AV1 = "av1"
VIDEO_CODEC_LABELS = {
    VIDEO_CODEC_HEVC: "HEVC",
    VIDEO_CODEC_AV1: "AV1",
}
DEFAULT_VIDEO_CODEC = VIDEO_CODEC_HEVC
ENCODE_SPEED_FAST = "fast"
ENCODE_SPEED_BALANCED = "balanced"
ENCODE_SPEED_BEST_COMPRESSION = "best_compression"
DEFAULT_ENCODE_SPEED = ENCODE_SPEED_BALANCED
ENCODE_SPEED_LABELS = {
    ENCODE_SPEED_FAST: "Fast",
    ENCODE_SPEED_BALANCED: "Balanced",
    ENCODE_SPEED_BEST_COMPRESSION: "Best compression",
}
USER_QUALITY_MIN = 1
USER_QUALITY_MAX = 100
DEFAULT_USER_QUALITY = 60
HARDWARE_ACCELERATION_LABELS = {
    "cuda": "CUDA",
    "qsv": "QSV",
    "vaapi": "VAAPI",
    "amf": "AMF",
    "vulkan": "Vulkan",
}


ENCODERS_BY_VIDEO_CODEC: dict[str, dict[str, EncoderDefinition]] = {
    VIDEO_CODEC_HEVC: {
        "nvenc": EncoderDefinition(
            codec="hevc_nvenc",
            needs_hwupload=False,
            hwaccel="cuda",
            quality_options=["cq"],
            speed_options={
                ENCODE_SPEED_FAST: {"preset": "p4"},
                ENCODE_SPEED_BALANCED: {"preset": "p6"},
                ENCODE_SPEED_BEST_COMPRESSION: {"preset": "p7"},
            },
            default_options={"tune": "hq", "rc": "vbr"},
        ),
        "qsv": EncoderDefinition(
            codec="hevc_qsv",
            needs_hwupload=False,
            hwaccel="qsv",
            quality_options=["global_quality"],
            speed_options={
                ENCODE_SPEED_FAST: {"preset": "fast"},
                ENCODE_SPEED_BALANCED: {"preset": "slow"},
                ENCODE_SPEED_BEST_COMPRESSION: {"preset": "veryslow"},
            },
        ),
        "vaapi": EncoderDefinition(
            codec="hevc_vaapi",
            needs_hwupload=True,
            hwaccel="vaapi",
            quality_options=["qp"],
            default_options={"rc_mode": "CQP"},
        ),
        "amf": EncoderDefinition(
            codec="hevc_amf",
            needs_hwupload=False,
            hwaccel="amf",
            quality_options=["qp_i", "qp_p"],
            speed_options={
                ENCODE_SPEED_FAST: {"quality": "speed"},
                ENCODE_SPEED_BALANCED: {"quality": "balanced"},
                ENCODE_SPEED_BEST_COMPRESSION: {"quality": "quality"},
            },
            default_options={"usage": "high_quality"},
        ),
        "vulkan": EncoderDefinition(
            codec="hevc_vulkan",
            needs_hwupload=False,
            hwaccel="vulkan",
            quality_options=["qp"],
            default_options={"rc_mode": "cqp", "tune": "hq", "usage": "transcode"},
        ),
        "libx265": EncoderDefinition(
            codec="libx265",
            needs_hwupload=False,
            hwaccel=None,
            quality_options=["crf"],
            speed_options={
                ENCODE_SPEED_FAST: {"preset": "fast"},
                ENCODE_SPEED_BALANCED: {"preset": "medium"},
                ENCODE_SPEED_BEST_COMPRESSION: {"preset": "slow"},
            },
        ),
    },
    VIDEO_CODEC_AV1: {
        "nvenc": EncoderDefinition(
            codec="av1_nvenc",
            needs_hwupload=False,
            hwaccel="cuda",
            quality_options=["cq"],
            speed_options={
                ENCODE_SPEED_FAST: {"preset": "p4"},
                ENCODE_SPEED_BALANCED: {"preset": "p6"},
                ENCODE_SPEED_BEST_COMPRESSION: {"preset": "p7"},
            },
            default_options={"tune": "hq", "rc": "vbr"},
        ),
        "qsv": EncoderDefinition(
            codec="av1_qsv",
            needs_hwupload=False,
            hwaccel="qsv",
            quality_options=["global_quality"],
            speed_options={
                ENCODE_SPEED_FAST: {"preset": "fast"},
                ENCODE_SPEED_BALANCED: {"preset": "slow"},
                ENCODE_SPEED_BEST_COMPRESSION: {"preset": "veryslow"},
            },
        ),
        "vaapi": EncoderDefinition(
            codec="av1_vaapi",
            needs_hwupload=True,
            hwaccel="vaapi",
            quality_options=["global_quality"],
            default_options={"rc_mode": "CQP"},
        ),
        "amf": EncoderDefinition(
            codec="av1_amf",
            needs_hwupload=False,
            hwaccel="amf",
            quality_options=["qp_i", "qp_p"],
            speed_options={
                ENCODE_SPEED_FAST: {"quality": "speed"},
                ENCODE_SPEED_BALANCED: {"quality": "balanced"},
                ENCODE_SPEED_BEST_COMPRESSION: {"quality": "quality"},
            },
            default_options={"usage": "high_quality"},
        ),
        "libsvtav1": EncoderDefinition(
            codec="libsvtav1",
            needs_hwupload=False,
            hwaccel=None,
            quality_options=["crf"],
            quality_max=63,
            speed_options={
                ENCODE_SPEED_FAST: {"preset": "10"},
                ENCODE_SPEED_BALANCED: {"preset": "7"},
                ENCODE_SPEED_BEST_COMPRESSION: {"preset": "4"},
            },
        ),
        "libaom-av1": EncoderDefinition(
            codec="libaom-av1",
            needs_hwupload=False,
            hwaccel=None,
            quality_options=["crf"],
            quality_max=63,
            speed_options={
                ENCODE_SPEED_FAST: {"cpu-used": 6},
                ENCODE_SPEED_BALANCED: {"cpu-used": 4},
                ENCODE_SPEED_BEST_COMPRESSION: {"cpu-used": 2},
            },
            default_options={"b:v": 0},
        ),
        "librav1e": EncoderDefinition(
            codec="librav1e",
            needs_hwupload=False,
            hwaccel=None,
            quality_options=["qp"],
            quality_max=63,
            speed_options={
                ENCODE_SPEED_FAST: {"speed": 8},
                ENCODE_SPEED_BALANCED: {"speed": 6},
                ENCODE_SPEED_BEST_COMPRESSION: {"speed": 4},
            },
        ),
    },
}

ENCODERS = ENCODERS_BY_VIDEO_CODEC[VIDEO_CODEC_HEVC]
ENCODER_PRIORITIES_BY_VIDEO_CODEC: dict[str, list[str]] = {
    VIDEO_CODEC_HEVC: [
        "nvenc",
        "qsv",
        "vaapi",
        "amf",
        "vulkan",
        "libx265",
    ],
    VIDEO_CODEC_AV1: [
        "nvenc",
        "qsv",
        "vaapi",
        "amf",
        "libsvtav1",
        "libaom-av1",
        "librav1e",
    ],
}
ENCODER_PRIORITIES = ENCODER_PRIORITIES_BY_VIDEO_CODEC[VIDEO_CODEC_HEVC]
VAAPI_DEVICE = Path("/dev/dri/renderD128")
PROBE_TIMEOUT_SECONDS = 10
VIDEO_DATA_ERROR = -1
EXIFTOOL_METADATA_COPY_ERROR = "Could not copy metadata with exiftool."
EXIFTOOL_UNAVAILABLE_ERROR = "ExifTool is required to copy metadata."
VIDEO_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".webm",
}


def _run(
    executable: str,
    args: list[str],
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )


def _run_ffmpeg(
    args: list[str],
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run("ffmpeg", ["-hide_banner"] + args, timeout)


def _run_ffprobe(
    args: list[str],
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run("ffprobe", args, timeout)


def _run_exiftool(
    args: list[str],
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run("exiftool", args, timeout)


def _get_ffmpeg_video_encoders() -> list[str]:
    try:
        result = _run_ffmpeg(["-encoders"])
    except FileNotFoundError:
        logger.error("FFmpeg executable not found")
        return []
    except subprocess.CalledProcessError as error:
        logger.error("Could not list FFmpeg encoders: %s", error)
        return []

    encoders = []

    for line in result.stdout.splitlines():
        line = line.strip()

        if not line.startswith("V"):
            continue

        parts = line.split()
        if len(parts) >= 2:
            encoders.append(parts[1])

    return encoders


def _probe_args(encoder: EncoderDefinition) -> list[str]:
    args = [
        "-loglevel",
        "error",
    ]

    if encoder.hwaccel == "vaapi" and VAAPI_DEVICE.exists():
        args.extend(
            ["-init_hw_device", f"vaapi=va:{VAAPI_DEVICE}", "-filter_hw_device", "va"]
        )

    args.extend(
        [
            "-f",
            "lavfi",
            "-i",
            "color=size=64x64:rate=1:duration=1",
            "-vf",
            _video_filter(encoder, resolution=64),  # pyright: ignore[reportArgumentType]
            "-c:v",
            encoder.codec,
            "-f",
            "null",
            "-",
        ]
    )
    return args


def _can_encode(encoder: EncoderDefinition) -> bool:
    try:
        _run_ffmpeg(_probe_args(encoder), timeout=PROBE_TIMEOUT_SECONDS)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        logger.info("Encoder probe failed: %s", encoder.codec)
        return False

    logger.info("Encoder probe succeeded: %s", encoder.codec)
    return True


def _video_filter(
    encoder: EncoderDefinition,
    resolution: int | None,
    frame_rate: float | None = None,
) -> str | None:
    filters: list[str] = []

    if frame_rate is not None:
        filters.append(f"fps={frame_rate:g}")

    if resolution is not None:
        filters.append(f"scale=-2:{resolution}")

    if encoder.needs_hwupload:
        filters.extend(["format=nv12", "hwupload"])

    if not filters:
        return None

    return ",".join(filters)


def _output_options(
    encoder: EncoderDefinition,
    resolution: int | None,
    quality: int | None,
    frame_rate: float | None = None,
    copy_metadata: bool = False,
    speed: str = DEFAULT_ENCODE_SPEED,
) -> OutputOptions:
    options: OutputOptions = {
        "codec:v": encoder.codec,
    }
    if copy_metadata:
        options.update({"map_metadata": "0", "map_chapters": "0"})

    options.update(encoder.default_options)
    video_filter = _video_filter(encoder, resolution, frame_rate=frame_rate)

    if video_filter is not None:
        options["vf"] = video_filter

    if speed not in ENCODE_SPEED_LABELS:
        raise ValueError(f"Unsupported encode speed: {speed}")
    options.update(encoder.speed_options.get(speed, {}))

    if quality is not None:
        quality = map_user_quality(encoder, quality)
        for option in encoder.quality_options:
            options[option] = quality

    return options


def _base_configuration(
    name: str,
    encoder: EncoderDefinition,
) -> EncodeConfiguration:
    return EncodeConfiguration(
        name=name,
        encoder=encoder,
    )


def _get_video_data(
    filename: PathLike,
    field: str,
) -> subprocess.CompletedProcess[str]:
    result = _run_ffprobe(
        [
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            f"stream={field}",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(filename),
        ]
    )
    return result


def get_frame_count(filename: PathLike) -> int:
    try:
        result = int(_get_video_data(filename, "nb_frames").stdout.strip())
        return result
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return VIDEO_DATA_ERROR


def get_frame_rate(filename: PathLike) -> float:
    try:
        numerator, denominator = (
            _get_video_data(
                filename,
                "avg_frame_rate",
            )
            .stdout.strip()
            .split("/")
        )
        return int(numerator) / int(denominator)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        ValueError,
        ZeroDivisionError,
    ):
        return VIDEO_DATA_ERROR


def get_resolution(filename: PathLike) -> int:
    try:
        result = _get_video_data(filename, "height").stdout.strip()
        return int(result)
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return VIDEO_DATA_ERROR


def collect_video_files(folder: PathLike) -> list[Path]:
    files = sorted(
        (
            path
            for path in Path(folder).rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ),
        key=lambda path: str(path).lower(),
    )
    logger.info("Collected %s video files from %s", len(files), folder)
    return files


def copy_metadata_with_exiftool(source: PathLike, output: PathLike) -> None:
    try:
        logger.info("Copying metadata with ExifTool: %s -> %s", source, output)
        _run_exiftool(
            [
                "-overwrite_original",
                "-TagsFromFile",
                str(source),
                "-all:all",
                str(output),
            ]
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        logger.error("ExifTool metadata copy failed: %s", error)
        raise RuntimeError(EXIFTOOL_METADATA_COPY_ERROR) from error


def ensure_exiftool_available() -> None:
    try:
        _run_exiftool(["-ver"])
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        logger.error("ExifTool is unavailable: %s", error)
        raise RuntimeError(EXIFTOOL_UNAVAILABLE_ERROR) from error


def get_available_encode_configurations() -> dict[str, list[EncodeConfiguration]]:
    ffmpeg_encoders = set(_get_ffmpeg_video_encoders())
    logger.info("Detected FFmpeg video encoder candidates: %s", sorted(ffmpeg_encoders))
    configurations: dict[str, list[EncodeConfiguration]] = {}

    for video_codec, priorities in ENCODER_PRIORITIES_BY_VIDEO_CODEC.items():
        configurations[video_codec] = []
        encoders = ENCODERS_BY_VIDEO_CODEC[video_codec]

        for name in priorities:
            encoder = encoders[name]
            if encoder.codec in ffmpeg_encoders and _can_encode(encoder):
                logger.info("Usable %s encoder: %s", video_codec, name)
                configurations[video_codec].append(_base_configuration(name, encoder))

    return configurations


def get_encode_configuration(
    video_codec: str = DEFAULT_VIDEO_CODEC,
) -> EncodeConfiguration:
    configurations = get_available_encode_configurations().get(video_codec, [])

    if configurations:
        selected = configurations[0]
        logger.info("Selected %s encoder: %s", video_codec, selected.name)
        return selected

    label = VIDEO_CODEC_LABELS.get(video_codec, video_codec)
    logger.error("No usable %s encoder found in ffmpeg", label)
    raise RuntimeError(f"No usable {label} encoder found in ffmpeg.")


def select_default_video_codec(
    configurations_by_codec: dict[str, list[EncodeConfiguration]],
) -> str | None:
    video_codecs = (VIDEO_CODEC_HEVC, VIDEO_CODEC_AV1)

    for video_codec in video_codecs:
        if any(
            configuration.encoder.hwaccel is not None
            for configuration in configurations_by_codec.get(video_codec, [])
        ):
            return video_codec

    if configurations_by_codec.get(VIDEO_CODEC_AV1):
        return VIDEO_CODEC_AV1
    if configurations_by_codec.get(VIDEO_CODEC_HEVC):
        return VIDEO_CODEC_HEVC

    return None


def map_user_quality(encoder: EncoderDefinition, quality: int) -> int:
    quality = max(USER_QUALITY_MIN, min(USER_QUALITY_MAX, quality))
    user_range = USER_QUALITY_MAX - USER_QUALITY_MIN
    backend_range = encoder.quality_max - encoder.quality_min
    quality_fraction = (quality - USER_QUALITY_MIN) / user_range
    return round(encoder.quality_max - quality_fraction * backend_range)


def append_encode_options(
    encode_configuration: EncodeConfiguration,
    resolution: int | None,
    quality: int | None,
    frame_rate: float | None = None,
    copy_metadata: bool = False,
    speed: str = DEFAULT_ENCODE_SPEED,
) -> EncodeConfiguration:
    return replace(
        encode_configuration,
        output_options=_output_options(
            encode_configuration.encoder,
            resolution=resolution,
            quality=quality,
            frame_rate=frame_rate,
            copy_metadata=copy_metadata,
            speed=speed,
        ),
    )
