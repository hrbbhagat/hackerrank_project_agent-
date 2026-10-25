"""Identity package providing identity resolution and evidence integration."""

from .resolver import IdentityResolver, parse_timestamp, normalize
from .integration import EvidenceIntegrator

__all__ = [
    "IdentityResolver",
    "EvidenceIntegrator",
    "parse_timestamp",
    "normalize",
]
