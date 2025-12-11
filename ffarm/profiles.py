"""
FFmpeg profiles and helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


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
    ]
}

OUTPUT_PATTERN = "{stem}_Proxy.mov"


def build_profile_command(profile: str, input_path: str, output_path: str) -> list[str]:
    """
    Expand templated profile command for FFmpeg invocation.
    """
    try:
        template = PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown profile {profile}") from exc
    return [part.format(input=input_path, output=output_path) for part in template]
