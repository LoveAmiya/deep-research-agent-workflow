from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_EXPECTED_SECTIONS = ["Background", "Key Findings", "Conclusion", "References"]


@dataclass
class ResearchBenchCase:
    case_id: str
    domain: str
    question: str
    difficulty: str = "medium"
    expected_sections: list[str] = field(default_factory=lambda: list(DEFAULT_EXPECTED_SECTIONS))
    expected_keywords: list[str] = field(default_factory=list)
    expected_evidence_count: int = 3
    expected_citation_count: int = 3
    expected_source_types: list[str] = field(default_factory=list)
    judge_focus: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchBenchCase":
        return cls(
            case_id=str(data.get("case_id") or data.get("id") or ""),
            domain=str(data.get("domain") or data.get("metadata", {}).get("domain") or "general"),
            question=str(data.get("question") or ""),
            difficulty=str(data.get("difficulty") or data.get("metadata", {}).get("difficulty") or "medium"),
            expected_sections=list(data.get("expected_sections") or DEFAULT_EXPECTED_SECTIONS),
            expected_keywords=list(data.get("expected_keywords") or data.get("keywords") or []),
            expected_evidence_count=int(
                data.get("expected_evidence_count", data.get("expected_min_findings", 3))
            ),
            expected_citation_count=int(
                data.get("expected_citation_count", data.get("expected_min_citations", 3))
            ),
            expected_source_types=list(data.get("expected_source_types") or []),
            judge_focus=list(data.get("judge_focus") or []),
            tags=list(data.get("tags") or []),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PLUS_CASES = [
    ResearchBenchCase(
        case_id="plus_ai_001",
        domain="AI / LLM",
        difficulty="medium",
        question="What organizational factors influence enterprise adoption of open-source LLMs?",
        expected_keywords=["enterprise", "open-source", "LLM", "governance"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["adoption", "governance"],
    ),
    ResearchBenchCase(
        case_id="plus_ai_002",
        domain="AI / LLM",
        difficulty="hard",
        question="How should teams compare retrieval-augmented generation and fine-tuning for internal knowledge assistants?",
        expected_keywords=["retrieval", "fine-tuning", "knowledge", "assistants"],
        expected_evidence_count=4,
        expected_citation_count=4,
        tags=["rag", "fine-tuning"],
    ),
    ResearchBenchCase(
        case_id="plus_ai_003",
        domain="AI / LLM",
        difficulty="medium",
        question="What risks should organizations consider when deploying AI coding assistants?",
        expected_keywords=["AI", "coding", "risk", "governance"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["software", "risk"],
    ),
    ResearchBenchCase(
        case_id="plus_health_001",
        domain="Healthcare",
        difficulty="medium",
        question="What operational factors affect hospital adoption of clinical decision support tools?",
        expected_keywords=["hospital", "clinical", "decision", "workflow"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["operations", "clinical"],
    ),
    ResearchBenchCase(
        case_id="plus_health_002",
        domain="Healthcare",
        difficulty="hard",
        question="What governance practices help healthcare teams evaluate AI triage tools safely?",
        expected_keywords=["healthcare", "AI", "triage", "governance"],
        expected_evidence_count=4,
        expected_citation_count=4,
        tags=["safety", "governance"],
    ),
    ResearchBenchCase(
        case_id="plus_finance_001",
        domain="Finance",
        difficulty="medium",
        question="What controls should financial institutions consider when adopting AI for fraud operations?",
        expected_keywords=["financial", "AI", "fraud", "controls"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["fraud", "controls"],
    ),
    ResearchBenchCase(
        case_id="plus_finance_002",
        domain="Finance",
        difficulty="easy",
        question="What factors influence small business adoption of digital payment platforms?",
        expected_keywords=["business", "digital", "payment", "adoption"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["payments", "small-business"],
    ),
    ResearchBenchCase(
        case_id="plus_climate_001",
        domain="Climate",
        difficulty="medium",
        question="What factors affect municipal adoption of climate resilience planning tools?",
        expected_keywords=["climate", "resilience", "municipal", "planning"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["resilience", "cities"],
    ),
    ResearchBenchCase(
        case_id="plus_climate_002",
        domain="Climate",
        difficulty="hard",
        question="How do grid modernization programs support renewable energy integration?",
        expected_keywords=["grid", "renewable", "energy", "integration"],
        expected_evidence_count=4,
        expected_citation_count=4,
        tags=["energy", "infrastructure"],
    ),
    ResearchBenchCase(
        case_id="plus_education_001",
        domain="Education",
        difficulty="medium",
        question="What evidence should schools consider before adopting AI tutoring systems?",
        expected_keywords=["schools", "AI", "tutoring", "evidence"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["tutoring", "schools"],
    ),
    ResearchBenchCase(
        case_id="plus_education_002",
        domain="Education",
        difficulty="easy",
        question="What factors affect teacher adoption of classroom analytics tools?",
        expected_keywords=["teacher", "classroom", "analytics", "adoption"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["analytics", "teachers"],
    ),
    ResearchBenchCase(
        case_id="plus_cyber_001",
        domain="Cybersecurity",
        difficulty="medium",
        question="What organizational practices improve phishing resilience programs?",
        expected_keywords=["phishing", "resilience", "training", "security"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["phishing", "training"],
    ),
    ResearchBenchCase(
        case_id="plus_cyber_002",
        domain="Cybersecurity",
        difficulty="hard",
        question="How should enterprises evaluate zero trust architecture adoption readiness?",
        expected_keywords=["zero", "trust", "enterprise", "readiness"],
        expected_evidence_count=4,
        expected_citation_count=4,
        tags=["zero-trust", "architecture"],
    ),
    ResearchBenchCase(
        case_id="plus_robotics_001",
        domain="Robotics",
        difficulty="medium",
        question="What factors influence warehouse adoption of autonomous mobile robots?",
        expected_keywords=["warehouse", "autonomous", "robots", "adoption"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["warehouse", "robots"],
    ),
    ResearchBenchCase(
        case_id="plus_robotics_002",
        domain="Robotics",
        difficulty="hard",
        question="What safety and operations factors affect collaborative robot deployment in manufacturing?",
        expected_keywords=["collaborative", "robot", "manufacturing", "safety"],
        expected_evidence_count=4,
        expected_citation_count=4,
        tags=["cobots", "manufacturing"],
    ),
    ResearchBenchCase(
        case_id="plus_policy_001",
        domain="Public Policy",
        difficulty="medium",
        question="What factors affect public sector adoption of digital identity systems?",
        expected_keywords=["public", "digital", "identity", "adoption"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["identity", "public-sector"],
    ),
    ResearchBenchCase(
        case_id="plus_policy_002",
        domain="Public Policy",
        difficulty="hard",
        question="How should agencies evaluate automated benefits eligibility systems?",
        expected_keywords=["agencies", "automated", "benefits", "eligibility"],
        expected_evidence_count=4,
        expected_citation_count=4,
        tags=["benefits", "automation"],
    ),
    ResearchBenchCase(
        case_id="plus_supply_001",
        domain="Supply Chain",
        difficulty="medium",
        question="What factors improve supply chain visibility platform adoption?",
        expected_keywords=["supply", "chain", "visibility", "adoption"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["logistics", "visibility"],
    ),
    ResearchBenchCase(
        case_id="plus_agriculture_001",
        domain="Agriculture",
        difficulty="medium",
        question="What factors influence farm adoption of precision agriculture tools?",
        expected_keywords=["farm", "precision", "agriculture", "adoption"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["agriculture", "sensors"],
    ),
    ResearchBenchCase(
        case_id="plus_transport_001",
        domain="Transportation",
        difficulty="medium",
        question="What factors affect transit agency adoption of real-time passenger information systems?",
        expected_keywords=["transit", "real-time", "passenger", "information"],
        expected_evidence_count=3,
        expected_citation_count=3,
        tags=["transit", "operations"],
    ),
]


def load_plus_cases() -> list[ResearchBenchCase]:
    return list(PLUS_CASES)


def plus_cases_as_dicts() -> list[dict[str, Any]]:
    return [case.to_dict() for case in PLUS_CASES]
