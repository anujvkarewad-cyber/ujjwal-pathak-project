"""Pydantic request models for content review, analytics and consent APIs.
Mirrors the canonical content model defined in
docs/integration-design.md §4 and content-pipeline/src/lib/schemas.mjs."""
from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Decision(str, Enum):
    approve = "approve"
    reject = "reject"
    request_changes = "request_changes"


class OptionUpdate(BaseModel):
    id: str = Field(min_length=1, max_length=4)
    text: str = Field(min_length=1)


class QuestionUpdate(BaseModel):
    prompt: Optional[str] = Field(default=None, min_length=10)
    options: Optional[List[OptionUpdate]] = Field(default=None, min_length=4, max_length=4)
    correctOptionId: Optional[str] = None
    explanation: Optional[str] = Field(default=None, min_length=10)
    difficulty: Optional[str] = None
    conceptTags: Optional[List[str]] = None
    attemptSpecificRiskConfirmed: Optional[bool] = None
    warningsAcknowledged: Optional[bool] = None


class DecisionRequest(BaseModel):
    decision: Decision
    comment: str = Field(default="", max_length=2000)
    warningsAcknowledged: bool = False
    attemptSpecificRiskConfirmed: bool = False


class ChapterPublishRequest(BaseModel):
    warningsAcknowledged: bool = True


class LoginRequest(BaseModel):
    email: str
    password: str


class MasteryBand(str, Enum):
    not_assessed = "Not assessed"
    weak = "Weak"
    medium = "Medium"
    strong = "Strong"
    mastered = "Mastered"


class AccuracyRange(str, Enum):
    r0_49 = "0-49"
    r50_69 = "50-69"
    r70_84 = "70-84"
    r85_100 = "85-100"


class ChapterSummary(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    studentId: str = Field(min_length=1, max_length=64)
    chapterId: str = Field(min_length=1, max_length=64)
    masteryBand: MasteryBand
    attemptCount: int = Field(ge=0, le=100000)
    accuracyRange: AccuracyRange
    lastActivityDate: date
    weakConceptTags: List[str] = Field(default_factory=list, max_length=8)


class TrendPoint(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    weekStart: date
    chapterId: str = Field(min_length=1, max_length=64)
    masteryBand: MasteryBand
    attemptCount: int = Field(ge=0, le=100000)
    accuracyRange: AccuracyRange


class ProgressSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # raw answers / unknown fields are rejected

    studentId: str = Field(min_length=1, max_length=64)
    consentVersion: int = Field(default=1, ge=1, le=10)
    syncedAt: Optional[str] = None
    summaries: List[ChapterSummary] = Field(default_factory=list, max_length=94)
    trend: List[TrendPoint] = Field(default_factory=list, max_length=94 * 12)


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studentId: str = Field(min_length=1, max_length=64)
    sharing: bool
    device: Optional[str] = None


class FollowupCreate(BaseModel):
    studentId: Optional[str] = None
    title: str = Field(min_length=3, max_length=200)
    priority: str = "medium"  # low | medium | high
    rule: Optional[str] = None


class FollowupUpdate(BaseModel):
    status: Optional[str] = None  # open | in_progress | completed
    note: Optional[str] = None
