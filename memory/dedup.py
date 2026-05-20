import hashlib


def normalize_text_for_fingerprint(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def build_memory_fingerprint(
    memory_type: str,
    text: str,
    source_url: str | None = None,
    citation: str | None = None,
    run_id: str | None = None,
) -> str:
    parts = [
        run_id or "",
        memory_type or "",
        normalize_text_for_fingerprint(text),
        source_url or "",
        citation or "",
    ]
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
