import re


_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?|[^\sA-Za-z0-9\u4e00-\u9fff]")


def estimate_tokens(text: str) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return 0
    return len(_TOKEN_PATTERN.findall(normalized))
