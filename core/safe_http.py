from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class UnsafeURL(ValueError):
    pass


class ResponseTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class BoundedHTTPResult:
    body: bytes
    content_type: str
    charset: str | None
    status_code: int | None
    final_url: str


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_RejectRedirects())


def validate_public_http_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURL("URL scheme is not allowed")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise UnsafeURL("URL authority is not allowed")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeURL("URL port is not allowed") from exc

    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeURL("URL host could not be resolved") from exc
    if not addresses:
        raise UnsafeURL("URL host could not be resolved")

    for address in addresses:
        candidate = ipaddress.ip_address(address[4][0])
        if not candidate.is_global:
            raise UnsafeURL("URL host is not allowed")
    return parsed


def read_public_url(
    url: str,
    *,
    timeout_seconds: float,
    user_agent: str,
    max_response_bytes: int,
) -> BoundedHTTPResult:
    if max_response_bytes < 1:
        raise ValueError("max_response_bytes must be positive")
    validate_public_http_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        response = _OPENER.open(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            exc.close()
            raise UnsafeURL("HTTP redirects are not allowed") from exc
        raise

    with response:
        final_url = response.geturl()
        if final_url != url:
            validate_public_http_url(final_url)
            raise UnsafeURL("HTTP redirects are not allowed")
        content_length = _content_length(response.headers)
        if content_length is not None and content_length > max_response_bytes:
            raise ResponseTooLarge("HTTP response exceeds the configured byte limit")
        body = response.read(max_response_bytes + 1)
        if len(body) > max_response_bytes:
            raise ResponseTooLarge("HTTP response exceeds the configured byte limit")
        content_type = response.headers.get("Content-Type", "")
        return BoundedHTTPResult(
            body=body,
            content_type=content_type,
            charset=_content_charset(response.headers),
            status_code=response.getcode(),
            final_url=final_url,
        )


def _content_length(headers: Any) -> int | None:
    raw_value = headers.get("Content-Length")
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Content-Length header") from exc
    if value < 0:
        raise ValueError("invalid Content-Length header")
    return value


def _content_charset(headers: Any) -> str | None:
    getter = getattr(headers, "get_content_charset", None)
    return getter() if callable(getter) else None
