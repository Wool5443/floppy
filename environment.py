import subprocess
from dataclasses import dataclass, field
from pathlib import Path


OptionValue = str | int | float | bool | None
OutputOptions = dict[str, OptionValue]


@dataclass
class EncoderDefinition:
    codec: str
    needs_hwupload: bool
    hwaccel: str | None
    quality_options: list[str]
    default_options: OutputOptions = field(default_factory=dict)


@dataclass
class EncodeConfiguration:
    name: str
    codec: str
    hwaccel: str | None
    needs_hwupload: bool
    quality_options: list[str]
    default_options: OutputOptions = field(default_factory=dict)
    output_options: OutputOptions = field(default_factory=dict)


ENCODERS: dict[str, EncoderDefinition] = {
    "nvenc": EncoderDefinition(
        codec="hevc_nvenc",
        needs_hwupload=False,
        hwaccel="cuda",
        quality_options=["cq"],
        default_options={"preset": "p7", "tune": "hq", "rc": "vbr"},
    ),
    "qsv": EncoderDefinition(
        codec="hevc_qsv",
        needs_hwupload=False,
        hwaccel="qsv",
        quality_options=["global_quality"],
        default_options={"preset": "veryslow"},
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
        default_options={"usage": "high_quality", "quality": "quality"},
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
        default_options={"preset": "veryslow"},
    ),
}

ENCODER_PRIORITIES: list[str] = [
    "nvenc",
    "qsv",
    "vaapi",
    "amf",
    "vulkan",
    "libx265",
]
VAAPI_DEVICE = Path("/dev/dri/renderD128")


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


def _get_hevc_codecs() -> list[str]:
    try:
        result = _run_ffmpeg(["-encoders"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    hevc_encoders = []

    for line in result.stdout.splitlines():
        line = line.strip()

        if "hevc" not in line.lower() and "265" not in line.lower():
            continue

        parts = line.split()
        if len(parts) >= 2:
            hevc_encoders.append(parts[1])

    return hevc_encoders


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


def _can_encode_hevc(encoder: EncoderDefinition) -> bool:
    try:
        _run_ffmpeg(_probe_args(encoder), timeout=10)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return False

    return True


def _video_filter(encoder: EncoderDefinition, resolution: int | None) -> str | None:
    filters: list[str] = []

    if resolution is not None:
        filters.append(f"scale={resolution}:-1")

    if encoder.needs_hwupload:
        filters.extend(["format=nv12", "hwupload"])

    if not filters:
        return None

    return ",".join(filters)


def _output_options(
    encoder: EncoderDefinition,
    resolution: int | None,
    quality: int | None,
) -> OutputOptions:
    options: OutputOptions = {
        "codec:v": encoder.codec,
    }
    options.update(encoder.default_options)
    video_filter = _video_filter(encoder, resolution)

    if video_filter is not None:
        options["vf"] = video_filter

    if quality is not None:
        for option in encoder.quality_options:
            options[option] = quality

    return options


def _base_configuration(
    name: str,
    encoder: EncoderDefinition,
) -> EncodeConfiguration:
    return EncodeConfiguration(
        name=name,
        codec=encoder.codec,
        hwaccel=encoder.hwaccel,
        needs_hwupload=encoder.needs_hwupload,
        quality_options=encoder.quality_options,
        default_options=encoder.default_options,
    )


def _get_video_data(
    filename: str | Path,
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


def get_frame_count(filename: str | Path) -> int:
    try:
        result = int(_get_video_data(filename, "nb_frames").stdout)
        return result
    except (FileNotFoundError, subprocess.CalledProcessError):
        return -1


def get_frame_rate(filename: str | Path) -> float:
    try:
        result = _get_video_data(filename, "r_frame_rate").stdout.split("/")
        return int(result[0]) / int(result[1])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return -1


def get_encode_configuration() -> EncodeConfiguration:
    codecs = set(_get_hevc_codecs())

    for name in ENCODER_PRIORITIES:
        encoder = ENCODERS[name]
        if encoder.codec in codecs and _can_encode_hevc(encoder):
            return _base_configuration(name, encoder)

    raise RuntimeError("No usable HEVC encoder found in ffmpeg.")


def append_encode_options(
    encode_configuration: EncodeConfiguration,
    resolution: int | None,
    quality: int | None,
) -> EncodeConfiguration:
    encoder = EncoderDefinition(
        codec=encode_configuration.codec,
        needs_hwupload=encode_configuration.needs_hwupload,
        hwaccel=encode_configuration.hwaccel,
        quality_options=encode_configuration.quality_options,
        default_options=encode_configuration.default_options,
    )
    return EncodeConfiguration(
        name=encode_configuration.name,
        codec=encode_configuration.codec,
        hwaccel=encode_configuration.hwaccel,
        needs_hwupload=encode_configuration.needs_hwupload,
        quality_options=encode_configuration.quality_options,
        default_options=encode_configuration.default_options,
        output_options=_output_options(
            encoder,
            resolution=resolution,
            quality=quality,
        ),
    )
