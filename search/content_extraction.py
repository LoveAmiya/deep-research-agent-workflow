import html
import re


NOISE_BLOCK_PATTERN = re.compile(
    r"<(script|style|nav|footer|header|noscript|svg|form|aside)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


def extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return clean_text(match.group(1))


def strip_html_tags(html_text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", html_text, flags=re.DOTALL)
    text = re.sub(r"</(p|div|section|article|main|li|h[1-6]|br)>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(text)


def clean_text(text: str) -> str:
    unescaped = html.unescape(text or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", unescaped).strip()


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", bool(text)
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip(), True


def extract_main_text(html_text: str, max_chars: int = 8000) -> tuple[str, dict]:
    original_length = len(html_text or "")
    cleaned_html, removed_noise_blocks = NOISE_BLOCK_PATTERN.subn(" ", html_text or "")

    main_match = re.search(
        r"<(main|article)[^>]*>(.*?)</\1>",
        cleaned_html,
        re.IGNORECASE | re.DOTALL,
    )
    if main_match:
        candidate_html = main_match.group(2)
        extraction_method = main_match.group(1).lower()
    else:
        body_match = re.search(r"<body[^>]*>(.*?)</body>", cleaned_html, re.IGNORECASE | re.DOTALL)
        candidate_html = body_match.group(1) if body_match else cleaned_html
        extraction_method = "body" if body_match else "document"

    text = strip_html_tags(candidate_html)
    text, truncated = truncate_text(text, max_chars)
    metadata = {
        "extraction_method": extraction_method,
        "removed_noise_blocks": removed_noise_blocks,
        "truncated": truncated,
        "original_length": original_length,
        "final_length": len(text),
    }
    return text, metadata
