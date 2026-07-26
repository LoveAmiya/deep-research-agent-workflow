import re
from typing import Dict, List, Optional

from core.schema import Citation, EvidenceSpan, ResearchReport


class CitationRegistry:
    def __init__(self) -> None:
        self._evidence: Dict[str, EvidenceSpan] = {}
        self._citations: Dict[str, Citation] = {}
        self._evidence_keys: Dict[tuple[str, str], str] = {}
        self._citation_keys: Dict[tuple[str, Optional[str]], str] = {}

    def add_evidence(
        self,
        source_url: str,
        text: str,
        source_title: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> EvidenceSpan:
        normalized_text = text.strip()
        key = (source_url, normalized_text)
        existing_id = self._evidence_keys.get(key)
        if existing_id is not None:
            return self._evidence[existing_id]

        evidence_id = f"E{len(self._evidence) + 1}"
        evidence = EvidenceSpan(
            evidence_id=evidence_id,
            source_url=source_url,
            source_title=source_title,
            text=normalized_text,
            start_char=0 if normalized_text else None,
            end_char=len(normalized_text) if normalized_text else None,
            metadata=metadata or {},
        )
        self._evidence[evidence_id] = evidence
        self._evidence_keys[key] = evidence_id
        return evidence

    def add_citation(
        self,
        source_url: str,
        evidence_id: Optional[str] = None,
        source_title: Optional[str] = None,
        quote: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Citation:
        key = (source_url, evidence_id)
        existing_id = self._citation_keys.get(key)
        if existing_id is not None:
            return self._citations[existing_id]

        citation_id = f"C{len(self._citations) + 1}"
        citation = Citation(
            citation_id=citation_id,
            source_url=source_url,
            source_title=source_title,
            evidence_id=evidence_id,
            quote=quote,
            metadata=metadata or {},
        )
        self._citations[citation_id] = citation
        self._citation_keys[key] = citation_id
        return citation

    def get_evidence(self, evidence_id: str) -> EvidenceSpan | None:
        return self._evidence.get(evidence_id)

    def get_citation(self, citation_id: str) -> Citation | None:
        return self._citations.get(citation_id)

    def list_evidence(self) -> List[EvidenceSpan]:
        return list(self._evidence.values())

    def list_citations(self) -> List[Citation]:
        return list(self._citations.values())

    def to_references_markdown(self, citation_ids: Optional[List[str]] = None) -> str:
        lines = []
        allowed = set(citation_ids) if citation_ids is not None else None
        for citation in self.list_citations():
            if allowed is not None and citation.citation_id not in allowed:
                continue
            title = citation.source_title or "Untitled source"
            lines.append(f"[{citation.citation_id}] {title} - {citation.source_url}")
        return "\n".join(lines)


class CitationValidator:
    CITATION_MARKER_PATTERN = re.compile(r"\[(C\d+)\]")

    def validate_report_citations(self, report: ResearchReport, registry: CitationRegistry) -> dict:
        markdown = report.markdown or ""
        citation_ids = self._extract_report_citation_ids(report)
        marker_ids = set(self.CITATION_MARKER_PATTERN.findall(markdown))
        body_marker_ids = set(self.CITATION_MARKER_PATTERN.findall(self._body_before_references(markdown)))
        issues = []

        if not citation_ids:
            issues.append("Report citations are empty.")
        if not marker_ids:
            issues.append("Report markdown does not contain citation markers.")

        missing_citations = [
            citation_id for citation_id in citation_ids if registry.get_citation(citation_id) is None
        ]
        if missing_citations:
            issues.append("Report contains citation IDs not present in the registry.")

        citations_without_markers = [citation_id for citation_id in citation_ids if citation_id not in body_marker_ids]
        if citations_without_markers:
            issues.append("Some report citations are missing from markdown markers.")

        missing_reference_urls = []
        for citation_id in citation_ids:
            citation = registry.get_citation(citation_id)
            if citation is not None and citation.source_url not in markdown:
                missing_reference_urls.append(citation.source_url)
        if missing_reference_urls:
            issues.append("References section is missing citation URLs.")

        sources = []
        for citation_id in citation_ids:
            citation = registry.get_citation(citation_id)
            if citation is None:
                continue
            evidence = registry.get_evidence(citation.evidence_id) if citation.evidence_id else None
            sources.append(
                {
                    "citationId": citation.citation_id,
                    "evidenceId": citation.evidence_id,
                    "sourceTitle": citation.source_title or getattr(evidence, "source_title", None),
                    "sourceUrl": citation.source_url,
                    "evidenceText": getattr(evidence, "text", "") or citation.quote or "",
                    "quote": citation.quote or "",
                    "startChar": getattr(evidence, "start_char", None),
                    "endChar": getattr(evidence, "end_char", None),
                    "status": "linked" if evidence is not None else "missing_evidence",
                    "isMock": citation.source_url.startswith("mock://"),
                }
            )

        grounded_count = len(sources)
        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "citation_count": len(citation_ids),
            "grounded_citation_count": grounded_count,
            "missing_citations": missing_citations,
            "sources": sources,
        }

    @staticmethod
    def _extract_report_citation_ids(report: ResearchReport) -> List[str]:
        citation_ids = []
        for citation in report.citations:
            normalized = citation.strip()
            if normalized.startswith("C") and normalized[1:].isdigit() and normalized not in citation_ids:
                citation_ids.append(normalized)
        return citation_ids

    @staticmethod
    def _body_before_references(markdown: str) -> str:
        references_index = markdown.find("## References")
        if references_index == -1:
            return markdown
        return markdown[:references_index]
