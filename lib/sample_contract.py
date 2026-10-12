"""Profile-driven canonical paths for cinematic-fast review samples."""
from __future__ import annotations

from lib.media_profiles import get_profile


SAMPLE_PROFILE_BY_OUTPUT_PROFILE = {
    "social_vertical_3_4_2160p30": "social_vertical_3_4_sample_540p30",
    "social_vertical_3_4_1080p30": "social_vertical_3_4_sample_540p30",
    "social_vertical_3_4_sample_540p30": "social_vertical_3_4_sample_540p30",
    "social_vertical_1080p30": "social_vertical_sample_540p30",
    "social_vertical_sample_540p30": "social_vertical_sample_540p30",
}


def resolve_sample_profile(profile: str) -> str:
    """Map a locked delivery or explicit sample profile to its review profile."""
    try:
        get_profile(profile)
    except ValueError as exc:
        raise ValueError(f"Unknown cinematic-fast sample profile {profile!r}") from exc
    try:
        return SAMPLE_PROFILE_BY_OUTPUT_PROFILE[profile]
    except KeyError as exc:
        raise ValueError(
            f"Profile {profile!r} has no cinematic-fast sample profile mapping"
        ) from exc


def canonical_sample_filename(profile: str) -> str:
    """Return the review filename whose dimensions match the sample profile."""
    sample = get_profile(resolve_sample_profile(profile))
    return f"sample-v1-{sample.width}x{sample.height}.mp4"


def canonical_sample_relative_path(profile: str) -> str:
    return f"renders/{canonical_sample_filename(profile)}"
