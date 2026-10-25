"""Phase 5: Timeline Reconstruction Module.

Exports:
- TimelineReconstructor: Core engine for chronological event aggregation and state resolution.
- ActivityIndex: In-memory index of global system activity events.
- TimelineEvent: Dataclass representing a normalized timeline event.
- ResourceTimeline: Dataclass representing a resource's chronological lifecycle and cutoff state.
- TimelineReconstructionResult: Complete case-level timeline reconstruction result.
"""

from .reconstructor import (
    TimelineReconstructor,
    ActivityIndex,
    TimelineEvent,
    ResourceTimeline,
    TimelineReconstructionResult,
)

__all__ = [
    "TimelineReconstructor",
    "ActivityIndex",
    "TimelineEvent",
    "ResourceTimeline",
    "TimelineReconstructionResult",
]
