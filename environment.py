import subprocess
from pathlib import Path

ENCODERS = {
    "nvenc": {
        "codec": "hevc_nvenc",
        "needs_hwupload": False,
        "hwaccel": "cuda",
        "quality_options": ["cq"],
        "default_options": {"preset": "p7", "tune": "hq", "rc": "vbr"},
    },
    "qsv": {
        "codec": "hevc_qsv",
        "needs_hwupload": False,
        "hwaccel": "qsv",
        "quality_options": ["global_quality"],
        "default_options": {"preset": "veryslow"},
    },
    "vaapi": {
        "codec": "hevc_vaapi",
        "needs_hwupload": True,
        "hwaccel": "vaapi",
        "quality_options": ["qp"],
        "default_options": {"rc_mode": "CQP"},
    },
    "amf": {
        "codec": "hevc_amf",
        "needs_hwupload": False,
        "hwaccel": "amf",
        "quality_options": ["qp_i", "qp_p"],
        "default_options": {"usage": "high_quality", "quality": "quality"},
    },
    "vulkan": {
        "codec": "hevc_vulkan",
        "needs_hwupload": False,
        "hwaccel": "vulkan",
        "quality_options": ["qp"],
        "default_options": {"rc_mode": "cqp", "tune": "hq", "usage": "transcode"},
    },
    "libx265": {
        "codec": "libx265",
        "needs_hwupload": False,
        "hwaccel": None,
        "quality_options": ["crf"],
        "default_options": {"preset": "veryslow"},
    },
}

ENCODER_PRIORITIES = [
    "nvenc",
    "qsv",
    "vaapi",
    "amf",
    "vulkan",
    "libx265",
]
VAAPI_DEVICE = Path("/dev/dri/renderD128")


def _run_ffmpeg(args, timeout=None):
    return subprocess.run(
        ["ffmpeg", "-hide_banner", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )


def _get_hevc_codecs():
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


def _probe_args(encoder):
    args = [
        "-loglevel",
        "error",
    ]

    if encoder["hwaccel"] == "vaapi" and VAAPI_DEVICE.exists():
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
            encoder["codec"],
            "-f",
            "null",
            "-",
        ]
    )
    return args


def can_encode_hevc(encoder):
    try:
        _run_ffmpeg(_probe_args(encoder), timeout=10)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return False

    return True


def _video_filter(encoder, resolution):
    filters = []

    if resolution is not None:
        filters.append(f"scale={resolution}:-1")

    if encoder["needs_hwupload"]:
        filters.extend(["format=nv12", "hwupload"])

    if not filters:
        return None

    return ",".join(filters)


def _output_options(encoder, resolution, quality):
    options = {
        "codec:v": encoder["codec"],
    }
    options.update(encoder.get("default_options", {}))
    video_filter = _video_filter(encoder, resolution)

    if video_filter is not None:
        options["vf"] = video_filter

    if quality is not None:
        for option in encoder["quality_options"]:
            options[option] = quality

    return options


def _base_configuration(name, encoder):
    return {
        "name": name,
        "codec": encoder["codec"],
        "hwaccel": encoder["hwaccel"],
        "needs_hwupload": encoder["needs_hwupload"],
        "quality_options": encoder["quality_options"],
        "default_options": encoder.get("default_options", {}),
    }


def get_encode_configuration():
    codecs = set(_get_hevc_codecs())

    for name in ENCODER_PRIORITIES:
        encoder = ENCODERS[name]
        if encoder["codec"] in codecs and can_encode_hevc(encoder):
            return _base_configuration(name, encoder)

    raise RuntimeError("No usable HEVC encoder found in ffmpeg.")


def append_encode_options(encode_configuration, resolution, quality):
    encoder = {
        "codec": encode_configuration["codec"],
        "needs_hwupload": encode_configuration["needs_hwupload"],
        "quality_options": encode_configuration["quality_options"],
        "default_options": encode_configuration["default_options"],
    }
    configuration = encode_configuration.copy()
    configuration["output_options"] = _output_options(
        encoder,
        resolution=resolution,
        quality=quality,
    )

    return configuration
