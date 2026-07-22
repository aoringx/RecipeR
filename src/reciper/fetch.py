"""Bounded webpage fetching with URL and redirect validation."""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from reciper.errors import FetchError, UnsafeURLError

DEFAULT_MAX_BYTES = 3 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_REDIRECTS = 5
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
USER_AGENT = "RecipeR/0.1 (+local recipe extraction; one page per invocation)"

Resolver = Callable[..., Iterable[tuple[Any, ...]]]
URLValidator = Callable[[str], str]


@dataclass(frozen=True)
class FetchedPage:
    requested_url: str
    final_url: str
    html: str


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeURLError(f"The website resolved to an invalid IP address: {address}") from exc
    return ip.is_global


def validate_public_url(url: str, *, resolver: Resolver = socket.getaddrinfo) -> str:
    """Validate an HTTP(S) URL and reject hosts resolving to non-public addresses."""

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("The website URL contains an invalid port.") from exc

    if parts.scheme.lower() not in {"http", "https"}:
        raise UnsafeURLError("Only http:// and https:// website URLs are supported.")
    if not parts.hostname:
        raise UnsafeURLError("The website URL must include a hostname.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("Website URLs containing usernames or passwords are not supported.")

    host = parts.hostname
    addresses: set[str] = set()
    try:
        literal_ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        try:
            records = resolver(
                host,
                port or (443 if parts.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise FetchError(f"Could not resolve the website hostname: {host}") from exc
        addresses.update(record[4][0] for record in records)
    else:
        addresses.add(str(literal_ip))

    if not addresses:
        raise FetchError(f"The website hostname did not resolve to an address: {host}")
    if any(not _is_public_address(address) for address in addresses):
        raise UnsafeURLError("The website URL resolves to a private or non-public network address.")

    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, ""))


def redact_url(url: str) -> str:
    """Remove query parameters and fragments before displaying or persisting a source URL."""

    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class WebFetcher:
    """Fetch exactly one bounded HTML document, validating every redirect hop."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        url_validator: URLValidator = validate_public_url,
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            trust_env=False,
        )
        self._validate_url = url_validator
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._retries = retries
        self._sleep = sleep

    def __enter__(self) -> WebFetcher:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch(self, url: str) -> FetchedPage:
        requested_url = self._validate_url(url)
        current_url = requested_url

        for redirect_count in range(self._max_redirects + 1):
            current_url = self._validate_url(current_url)
            status_code, headers, body, encoding = self._request(current_url)

            if status_code in REDIRECT_STATUS_CODES:
                location = headers.get("location")
                if not location:
                    raise FetchError("The website returned a redirect without a destination.")
                if redirect_count >= self._max_redirects:
                    raise FetchError(f"The website exceeded {self._max_redirects} redirects.")
                current_url = urljoin(current_url, location)
                continue

            try:
                html = body.decode(encoding or "utf-8", errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")
            return FetchedPage(
                requested_url=requested_url,
                final_url=redact_url(current_url),
                html=html,
            )

        raise FetchError("The website redirect chain could not be completed.")

    def _request(self, url: str) -> tuple[int, httpx.Headers, bytes, str | None]:
        for attempt in range(self._retries + 1):
            should_retry = False
            try:
                with self._client.stream("GET", url) as response:
                    if response.status_code in TRANSIENT_STATUS_CODES and attempt < self._retries:
                        should_retry = True
                    elif response.status_code in REDIRECT_STATUS_CODES:
                        return response.status_code, response.headers, b"", None
                    else:
                        response.raise_for_status()
                        content_type = (
                            response.headers.get("content-type", "").split(";", 1)[0].lower()
                        )
                        if content_type not in HTML_CONTENT_TYPES:
                            shown_type = content_type or "missing"
                            raise FetchError(
                                f"The website did not return HTML (Content-Type: {shown_type})."
                            )

                        content_length = response.headers.get("content-length")
                        if content_length:
                            try:
                                declared_size = int(content_length)
                            except ValueError:
                                declared_size = 0
                            if declared_size > self._max_bytes:
                                raise FetchError(
                                    "The webpage is larger than the "
                                    f"{self._max_bytes:,}-byte limit."
                                )

                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > self._max_bytes:
                                raise FetchError(
                                    "The webpage is larger than the "
                                    f"{self._max_bytes:,}-byte limit."
                                )
                        return (
                            response.status_code,
                            response.headers,
                            bytes(body),
                            response.encoding,
                        )
            except FetchError:
                raise
            except httpx.RequestError as exc:
                if attempt >= self._retries:
                    raise FetchError(
                        "The website could not be reached after multiple attempts."
                    ) from exc
                should_retry = True
            except httpx.HTTPStatusError as exc:
                raise FetchError(f"The website returned HTTP {exc.response.status_code}.") from exc

            if should_retry:
                self._sleep(0.5 * (2**attempt))

        raise FetchError("The website could not be fetched.")
