"""
FFmpeg profiles and helpers.
"""

from __future__ import annotations

from typing import Any

PROFILES: dict[str, list[str]] = {
    "prores_proxy_1280": [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-progress",
        "pipe:1",
        "-i",
        "{input}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        "scale='if(gt(iw,ih),1280,-2)':'if(gt(ih,iw),1280,-2)'",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "0",
        "-c:a",
        "copy",
        "-f",
        "mov",
        "{output}",
    ],
    "dji_drone_prores_standard": [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-progress",
        "pipe:1",
        "-i",
        "{input}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "2",
        "-c:a",
        "copy",
        "-f",
        "mov",
        "{output}",
    ],
}

PROFILE_CHOICES = [
    ("prores_proxy_1280", "Proxy 1280 (ProRes Proxy)"),
    ("dji_drone_prores_standard", "DJI Drone ProRes Standard"),
]

PROFILE_SETTINGS: dict[str, dict[str, Any]] = {
    "prores_proxy_1280": {
        "output_subdir": "PROXIES",
        "output_pattern": "{stem}_Proxy.mov",
        "filter_prefix": None,
        "mirror_first_subdir": False,
    },
    "dji_drone_prores_standard": {
        "output_subdir": "dji_drone_prores_standard",
        "output_pattern": "{stem}.mov",
        "filter_prefix": "DJI_",
        "mirror_first_subdir": True,
        "ignore_proxy_suffix": True,
    },
}

OUTPUT_SUBDIRS = {settings["output_subdir"] for settings in PROFILE_SETTINGS.values()}


def build_profile_command(profile: str, input_path: str, output_path: str) -> list[str]:
    """
    Expand templated profile command for FFmpeg invocation.
    """
    try:
        template = PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown profile {profile}") from exc
    return [part.format(input=input_path, output=output_path) for part in template]


def get_profile_settings(profile: str) -> dict[str, Any]:
    """
    Return metadata for the given profile, raising if the profile is unknown.
    """
    try:
        return PROFILE_SETTINGS[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown profile {profile}") from exc
