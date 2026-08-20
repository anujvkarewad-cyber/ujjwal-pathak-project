"""Pydantic request models for content review, analytics and consent APIs.
Mirrors the canonical content model defined in
docs/integration-design.md §4 and content-pipeline/src/lib/schemas.mjs.
"""
from datetime import date
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class StudentTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studentId: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256, repr=False)


class McqPracticeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: str = Field(default="Combined", max_length=32)
    subject: str = Field(default="All Subjects", max_length=80)
    chapter: str = Field(default="All Chapters", max_length=240)
    mode: str = Field(default="Mixed", max_length=32)
    difficulty: str = Field(default="Mixed", max_length=32)
    requestedCount: int = Field(default=10, ge=1, le=50)


class McqReviewItem(BaseModel):
    """Snapshot of one question after submit — lets students reopen wrong answers."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=80)
    prompt: str = Field(default="", max_length=4000)
    options: List[str] = Field(default_factory=list, max_length=4)
    answer: int = Field(default=0, ge=0, le=3)
    selected: Optional[int] = Field(default=None)
    explanation: str = Field(default="", max_length=4000)
    subject: str = Field(default="", max_length=80)
    chapter: str = Field(default="", max_length=240)
    difficulty: str = Field(default="", max_length=32)
    kind: str = Field(default="", max_length=32)
    correct: bool = False


class StudentMcqAttempt(BaseModel):
    """A completed attempt safe to restore on another student device."""

    model_config = ConfigDict(extra="ignore")

    attemptId: str = Field(min_length=1, max_length=180)
    kind: Literal["daily", "practice"]
    bankRevision: str = Field(default="unknown", max_length=120)
    date: Optional[str] = Field(default=None, max_length=16)
    group: Optional[str] = Field(default=None, max_length=32)
    config: Optional[McqPracticeConfig] = None
    questionIds: List[str] = Field(default_factory=list, min_length=1, max_length=50)
    answers: Dict[str, int] = Field(default_factory=dict)
    startedAt: int = Field(ge=0)
    completedAt: int = Field(ge=0)
    score: int = Field(ge=0, le=50)
    total: int = Field(ge=1, le=50)
    durationSeconds: int = Field(ge=0, le=24 * 60 * 60)
    review: Optional[List[McqReviewItem]] = Field(default=None, max_length=50)

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, answers: Dict[str, int]):
        if len(answers) > 50:
            raise ValueError("at most 50 answers are allowed")
        if any(not isinstance(choice, int) or choice < 0 or choice > 3 for choice in answers.values()):
            raise ValueError("answer choices must be integers from 0 to 3")
        return answers

    @model_validator(mode="after")
    def validate_attempt(self):
        question_ids = set(self.questionIds)
        if len(question_ids) != len(self.questionIds):
            raise ValueError("questionIds must be unique")
        if any(question_id not in question_ids for question_id in self.answers):
            raise ValueError("answers contain an unknown questionId")
        if self.score > self.total or self.total != len(self.questionIds):
            raise ValueError("score/total does not match the question list")
        if self.kind == "daily" and (not self.date or not self.group):
            raise ValueError("daily attempts require date and group")
        if self.kind == "practice" and self.config is None:
            raise ValueError("practice attempts require config")
        return self


class StudentMcqSyncRequest(StudentTokenRequest):
    attempts: List[StudentMcqAttempt] = Field(default_factory=list, max_length=330)


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
    model_config = ConfigDict(extra="forbid")

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
    priority: str = "medium"
    rule: Optional[str] = None


class FollowupUpdate(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None
