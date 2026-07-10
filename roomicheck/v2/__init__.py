"""Version 2 adaptive-questionnaire domain contracts.

This package intentionally does not replace the v1 CLI models. Stage 0 builds
the Demo Day domain foundation alongside the existing prototype.
"""

from .config import DIMENSION_IDS, PROFILE_SCHEMA_VERSION, QUESTIONNAIRE_VERSION
from .controller import AdaptiveController, CompletionDecision
from .models import (
    Contradiction,
    CoverageStatus,
    DimensionState,
    EvidenceKind,
    EvidenceReference,
    ProfileStatus,
    ProfileV2,
)

__all__ = [
    "AdaptiveController",
    "CompletionDecision",
    "Contradiction",
    "CoverageStatus",
    "DIMENSION_IDS",
    "DimensionState",
    "EvidenceKind",
    "EvidenceReference",
    "PROFILE_SCHEMA_VERSION",
    "ProfileStatus",
    "ProfileV2",
    "QUESTIONNAIRE_VERSION",
]
