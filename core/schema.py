from dataclasses import dataclass, field
from typing import List


@dataclass
class ResearchQuestion:
    question_id: str
    query: str
    context: str = ""


@dataclass
class ResearchPlan:
    question_id: str
    objective: str
    steps: List[str] = field(default_factory=list)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""


@dataclass
class Finding:
    finding_id: str
    summary: str
    evidence: List[str] = field(default_factory=list)
    confidence: str = "unknown"


@dataclass
class ResearchReport:
    question_id: str
    title: str
    summary: str
    findings: List[Finding] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
