"""
Pydantic models describing the structured shape returned by the AI layer
and served to the frontend.
"""

from typing import List, Literal
from pydantic import BaseModel, Field


Severity = Literal["LOW", "MEDIUM", "HIGH"]
Classification = Literal["LEGAL", "NON_LEGAL", "UNCERTAIN"]


class RiskItem(BaseModel):
    issue: str
    explanation: str
    severity: Severity = "LOW"


class TimelineItem(BaseModel):
    date_or_deadline: str
    action: str
    responsible_party: str
    consequence: str = ""


class TermItem(BaseModel):
    term: str
    what_it_says: str = Field(default="", alias="whatItSays")
    simple_meaning: str = Field(default="", alias="simpleMeaning")
    why_it_matters: str = Field(default="", alias="whyItMatters")

    class Config:
        populate_by_name = True


class ClauseItem(BaseModel):
    title: str
    explanation: str


class AnalysisResult(BaseModel):
    """Full structured result for a LEGAL document."""

    status: Literal["ANALYZED"] = "ANALYZED"
    classification: Classification = "LEGAL"

    document_type: str = ""
    parties: List[str] = []
    duration: str = ""
    purpose: str = ""
    summary: str = ""

    important_terms: List[TermItem] = []
    timeline: List[TimelineItem] = []

    user_responsibilities: List[str] = []
    other_party_responsibilities: List[str] = []

    risks: List[RiskItem] = []
    important_clauses: List[ClauseItem] = []

    recommended_actions: List[str] = []
    lawyer_questions: List[str] = []
    key_takeaways: List[str] = []

    disclaimer: str = (
        "This tool helps you understand a document in plain English. "
        "It is not a lawyer and does not provide legal advice. For decisions "
        "with real consequences, please consult a qualified lawyer."
    )


class OutOfContextResult(BaseModel):
    """Returned when the document is NON_LEGAL or UNCERTAIN."""

    status: Literal["OUT_OF_CONTEXT"] = "OUT_OF_CONTEXT"

    classification: Classification = "NON_LEGAL"

    message: str = (
        "The uploaded document does not appear to be a legal document or "
        "contain sufficient legal information for this tool to analyze it. "
        "Please upload a relevant legal document."
    )

    @classmethod
    def for_classification(
        cls,
        classification: Classification
    ) -> "OutOfContextResult":

        if classification == "UNCERTAIN":
            return cls(
                classification="UNCERTAIN",
                message=(
                    "We couldn't confidently determine whether this document "
                    "is legal in nature. Please upload a document containing "
                    "clear legal information."
                ),
            )

        return cls(
            classification="NON_LEGAL",
            message=(
                "The uploaded document does not appear to be a legal document "
                "or contain sufficient legal information for this tool to "
                "analyze it. Please upload a relevant legal document."
            ),
        )


class ErrorResult(BaseModel):
    message: str