"""Episode Engine - segment a VEX coding session into episodes + pauses.

Public API:
    segment_session(events) -> (episodes, pauses)
"""
from .segmenter import segment_session, segment_episodes, boundary_kind

__all__ = ["segment_session", "segment_episodes", "boundary_kind"]
