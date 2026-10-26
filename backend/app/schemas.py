# =============================================================================
# schemas.py
# Purpose : Defines the data shapes used by the backend.
# Logic   : Two groups of models:
#           1) Llm*  -> what we EXPECT from the model (lenient: wrong types are
#                       cleaned instead of crashing, e.g. a number sent as text).
#           2) Report/LabResult/RadiologyResult -> what we SEND to the frontend.
#                       Field names match exactly what tahlili.html reads.
# =============================================================================
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Status = Literal["green", "yellow", "red"]


def _to_text(value: Any) -> str:
    """Turn any value (None, number, text) into a clean string."""
    return "" if value is None else str(value).strip()


def _to_float(value: Any) -> float | None:
    """Turn a value into a finite float, or None if it is not a number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _to_list(value: Any) -> list:
    """Return the value if it is a list, otherwise an empty list."""
    return value if isinstance(value, list) else []


# ---------- What the model returns (lenient) ----------

class LlmLab(BaseModel):
    """One lab test as extracted by the model."""

    name: str = ""
    value: str = ""
    unit: str = ""
    ref_low: float | None = None   # lower bound printed on the paper
    ref_high: float | None = None  # upper bound printed on the paper
    status: str = "yellow"
    explanation: str = ""

    @field_validator("name", "value", "unit", "status", "explanation", mode="before")
    @classmethod
    def _clean_text(cls, v: Any) -> str:
        """Convert numbers/None to clean text."""
        return _to_text(v)

    @field_validator("ref_low", "ref_high", mode="before")
    @classmethod
    def _clean_number(cls, v: Any) -> float | None:
        """Convert to float or None."""
        return _to_float(v)


class LlmRadiology(BaseModel):
    """One radiology report as extracted by the model."""

    type: str = ""
    findings: str = ""       # short Arabic summary shown to the patient
    original_text: str = ""  # exact wording from the paper (used for urgent-word scan)
    status: str = "yellow"
    explanation: str = ""

    @field_validator("type", "findings", "original_text", "status", "explanation", mode="before")
    @classmethod
    def _clean_text(cls, v: Any) -> str:
        """Convert numbers/None to clean text."""
        return _to_text(v)


class LlmOutput(BaseModel):
    """The full JSON object the model must return."""

    summary: str = ""
    labs: list[LlmLab] = Field(default_factory=list)
    radiology: list[LlmRadiology] = Field(default_factory=list)
    doctor: str = ""
    questions: list[str] = Field(default_factory=list)

    @field_validator("summary", "doctor", mode="before")
    @classmethod
    def _clean_text(cls, v: Any) -> str:
        """Convert numbers/None to clean text."""
        return _to_text(v)

    @field_validator("labs", "radiology", mode="before")
    @classmethod
    def _clean_list(cls, v: Any) -> list:
        """Make sure list fields are lists."""
        return _to_list(v)

    @field_validator("questions", mode="before")
    @classmethod
    def _clean_questions(cls, v: Any) -> list[str]:
        """Keep only non-empty question strings."""
        return [q for q in (_to_text(x) for x in _to_list(v)) if q]


# ---------- What the frontend receives ----------

class LabResult(BaseModel):
    """One lab card in the report."""

    name: str
    value: str = ""
    unit: str = ""
    status: Status
    explanation: str = ""


class RadiologyResult(BaseModel):
    """One radiology card in the report."""

    type: str
    findings: str = ""
    status: Status
    explanation: str = ""


class Report(BaseModel):
    """The final report returned by POST /analyze."""

    overall: Status
    summary: str = ""
    results: list[LabResult] = Field(default_factory=list)
    radiology: list[RadiologyResult] = Field(default_factory=list)
    doctor: str = ""
    questions: list[str] = Field(default_factory=list)
