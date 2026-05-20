from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ResearchQuestion:
    question: str
    topic: Optional[str] = None
    question_id: str = ""
    query: str = ""
    context: str = ""

    def __post_init__(self) -> None:
        if not self.question and self.query:
            self.question = self.query
        if not self.query:
            self.query = self.question
        if self.topic is None:
            normalized = self.question.strip()
            self.topic = normalized if normalized else None


@dataclass
class ResearchPlan:
    question: str
    sub_questions: List[str] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    expected_sections: List[str] = field(default_factory=list)
    question_id: str = ""
    objective: str = ""
    steps: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.objective and self.question:
            self.objective = f"Research question: {self.question}"
        if not self.steps and self.sub_questions:
            self.steps = list(self.sub_questions)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "mock"


@dataclass
class Finding:
    claim: str
    evidence: str
    source_url: str
    confidence: float = 1.0
    finding_id: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.summary:
            self.summary = self.claim


@dataclass
class ResearchReport:
    title: str
    question: str
    sections: List[Dict[str, str]] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    markdown: str = ""
    question_id: str = ""
    summary: str = ""
    findings: List[Finding] = field(default_factory=list)
    references: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.references and self.citations:
            self.references = list(self.citations)
        if not self.citations and self.references:
            self.citations = list(self.references)
