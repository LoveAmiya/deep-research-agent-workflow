# Phase 11: Evidence Grounding + Citation

## Goal

Add a lightweight evidence and citation chain so findings, reports, review, revision, and evaluation can refer to grounded source records.

## Data Structures

- `EvidenceSpan`: stores evidence text, source URL, optional source title, and character bounds.
- `Citation`: stores citation ID, source URL, optional source title, linked evidence ID, and quote.
- `GroundedFinding`: mirrors a finding with optional evidence and citation IDs.

The existing `Finding` dataclass remains compatible and now carries optional `evidence_id`, `citation_id`, and `source_title` fields.

## CitationRegistry

`CitationRegistry` is an in-memory registry for the current pipeline run. It:

- creates evidence IDs like `E1`
- creates citation IDs like `C1`
- deduplicates identical `source_url + text` evidence
- deduplicates identical `source_url + evidence_id` citations
- renders references as `[C1] Title - URL`

## CitationValidator

`CitationValidator` checks a report against the registry:

- report citations are non-empty
- markdown contains `[C1]` style markers
- report citation IDs exist in the registry
- References include the citation URLs

The validator is rule-based. It does not perform semantic fact verification.

## Agent Integration

- `ReaderAgent` creates evidence and citations when a registry is present.
- `WriterAgent` writes citation markers in Key Findings and references from the registry.
- `CriticAgent` adds grounded citation checks to its review dictionary.
- `RedAgent` raises citation/evidence issues for missing markers or ungrounded citations.
- `BlueAgent` can repair missing citation markers or References using findings and the registry.

## Current Boundaries

This phase is not production-grade citation grounding. It does not implement embedding, vector search, semantic verification, LLM-as-Judge, complex webpage extraction, async DAG execution, persistent memory, or multi-round Red/Blue review.

## Acceptance Criteria

- mock search and mock fetch still work
- Reader-generated findings can carry `evidence_id` and `citation_id`
- reports include `[C1]` style citation markers
- References can be generated from `CitationRegistry`
- Critic/Red/Blue can inspect or repair basic citation grounding issues
- evaluation includes a citation grounding score
- all tests, eval, and demo commands pass without real network or real LLM calls
