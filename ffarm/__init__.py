"""
ffarm package entry point and shared exports.
"""

from .profiles import PROFILES, PROFILE_CHOICES, PROFILE_SETTINGS, get_profile_settings, build_profile_command

__all__ = [
    "PROFILES",
    "PROFILE_CHOICES",
    "PROFILE_SETTINGS",
    "get_profile_settings",
    "build_profile_command",
]
