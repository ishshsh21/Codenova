"""Schema-constrained extraction output shared by the LLM and heuristic extractors (TRD 4.1)."""
from typing import Optional
from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    classification: str
    classification_confidence: float = Field(ge=0, le=1)
    classification_evidence: str = ""

    is_actionable: bool = False
    task_title: Optional[str] = None
    action_type: Optional[str] = None
    task_confidence: float = 0.0

    owner_type: Optional[str] = None       # CURRENT_USER | OTHER_PERSON | TEAM_UNKNOWN
    owner_label: str = ""
    owner_confidence: float = 0.0

    deadline_iso: Optional[str] = None     # resolved ISO datetime, or None if unresolved
    deadline_raw: Optional[str] = None     # raw phrase e.g. "EOD", "Friday"
    deadline_confidence: float = 0.0

    project: Optional[str] = None
    project_confidence: float = 0.0

    is_blocking: bool = False
    estimated_effort_minutes: int = 30
