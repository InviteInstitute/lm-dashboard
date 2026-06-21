"""Episode engine: break a VEX coding session into episodes and pauses.

A small, dependency-free package. The one function you usually need is
segment_session(events) -> (episodes, pauses).
"""
from .segmenter import segment_session, segment_episodes, boundary_kind

__all__ = ["segment_session", "segment_episodes", "boundary_kind"]
