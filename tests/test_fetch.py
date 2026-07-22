import socket
from collections.abc import Iterator

import httpx
import pytest

from reciper.errors import FetchError, UnsafeURLError
from reciper.fetch import WebFetcher, validate_public_url

PUBLIC_ADDRESS = "93.184.216.34"


def _public_resolver(
    host: str,
    port: int,
    *,
    type: socket.SocketKind,
) -> list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]]:
    del host, type
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_ADDRESS, port))]


def _validate_public_test_url(url: str) -> str:
    return validate_public_url(url, resolver=_public_resolver)


class _ChunkedBody(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b"abc"
        yield b"def"


def test_validate_public_url_rejects_mixed_public_and_private_dns_answers() -> None:
    def mixed_resolver(
        host: str,
        port: int,
        *,
        type: socket.SocketKind,
    ) -> list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]]:
        del host, type
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_ADDRESS, port)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.8", port)),
        ]

    with pytest.raises(UnsafeURLError, match="private or non-public"):
        validate_public_url("https://recipes.example/bread", resolver=mixed_resolver)


def test_fetch_follows_relative_redirect_and_redacts_final_url() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"location": "/recipes/bread?utm_source=test#method"},
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body>recipe</body></html>",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        page = WebFetcher(
            client=client,
            url_validator=_validate_public_test_url,
            retries=0,
        ).fetch("https://recipes.example/start#top")

    assert seen_urls == [
        "https://recipes.example/start",
        "https://recipes.example/recipes/bread?utm_source=test",
    ]
    assert page.requested_url == "https://recipes.example/start"
    assert page.final_url == "https://recipes.example/recipes/bread"
    assert page.html == "<html><body>recipe</body></html>"


def test_fetch_validates_redirect_destination_before_requesting_it() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.url.host == "recipes.example"
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = WebFetcher(
            client=client,
            url_validator=_validate_public_test_url,
            retries=0,
        )
        with pytest.raises(UnsafeURLError, match="private or non-public"):
            fetcher.fetch("https://recipes.example/start")

    assert request_count == 1


def test_fetch_enforces_redirect_limit() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(302, headers={"location": "/again"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = WebFetcher(
            client=client,
            url_validator=_validate_public_test_url,
            max_redirects=1,
            retries=0,
        )
        with pytest.raises(FetchError, match="exceeded 1 redirects"):
            fetcher.fetch("https://recipes.example/start")

    assert request_count == 2


@pytest.mark.parametrize(
    ("content_type", "expected_label"),
    [("application/json", "application/json"), (None, "missing")],
)
def test_fetch_rejects_non_html_content_types(
    content_type: str | None,
    expected_label: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        headers = {"content-type": content_type} if content_type else {}
        return httpx.Response(200, headers=headers, content=b"not html")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = WebFetcher(
            client=client,
            url_validator=_validate_public_test_url,
            retries=0,
        )
        with pytest.raises(FetchError, match=f"Content-Type: {expected_label}"):
            fetcher.fetch("https://recipes.example/not-html")


def test_fetch_rejects_declared_content_length_over_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": "6"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = WebFetcher(
            client=client,
            url_validator=_validate_public_test_url,
            max_bytes=5,
            retries=0,
        )
        with pytest.raises(FetchError, match="5-byte limit"):
            fetcher.fetch("https://recipes.example/too-large")


def test_fetch_stops_when_streamed_body_crosses_size_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            stream=_ChunkedBody(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = WebFetcher(
            client=client,
            url_validator=_validate_public_test_url,
            max_bytes=5,
            retries=0,
        )
        with pytest.raises(FetchError, match="5-byte limit"):
            fetcher.fetch("https://recipes.example/streamed")


def test_fetch_wraps_protocol_errors_as_fetch_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("invalid response", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = WebFetcher(
            client=client,
            url_validator=_validate_public_test_url,
            retries=0,
        )
        with pytest.raises(FetchError, match="could not be reached"):
            fetcher.fetch("https://recipes.example/broken")
