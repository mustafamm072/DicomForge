"""Production-hardened DICOMweb HTTP transport implementations.

The module provides three composable transport classes:

- :class:`RequestsDicomwebTransport` — ``requests``-backed transport with
  connection pooling, configurable timeouts, TLS client-certificate support,
  and a streaming response API for WADO-RS without full-body buffering.
- :class:`RetryTransport` — decorator that wraps any :class:`DicomwebTransport`
  with automatic retry, exponential back-off, and per-attempt jitter.
- :class:`BearerTokenTransport` — decorator that injects an
  ``Authorization: Bearer <token>`` header so you can separate auth concerns
  from the core transport.

All classes implement the :class:`~dicomforge.dicomweb.DicomwebTransport`
protocol, so they are drop-in replacements for the stdlib
:class:`~dicomforge.dicomweb.UrllibDicomwebTransport`.

Example
-------
Compose a production-grade DICOMweb client in three lines::

    from dicomforge.transport import BearerTokenTransport, RequestsDicomwebTransport, RetryTransport
    from dicomforge.dicomweb import DicomwebClient

    transport = BearerTokenTransport(
        RetryTransport(RequestsDicomwebTransport(timeout=30)),
        token="<your-oauth-token>",
    )
    client = DicomwebClient("https://healthcare.googleapis.com/v1/...", transport)

    # Stream a study without buffering the full response body:
    for part in client.iter_retrieve_study_parts("1.2.3.4"):
        process(part.body)

Requires ``pip install dicomforge[transport]`` (installs ``requests>=2.28``).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple, Union

from dicomforge.dicomweb import DicomwebResponse, Headers, MutableHeaders
from dicomforge.errors import MissingBackendError

Body = Union[bytes, bytearray, str, None]

_DEFAULT_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Streaming response
# ---------------------------------------------------------------------------


@dataclass
class StreamingDicomwebResponse:
    """HTTP response whose body is consumed lazily from a byte-chunk iterator.

    Returned by :meth:`RequestsDicomwebTransport.stream`.  The ``body_iter``
    attribute must be consumed **exactly once**; call :meth:`drain` to discard
    the body if you only need the headers.

    Parameters
    ----------
    status_code:
        HTTP status code.
    headers:
        Response headers (case-insensitive lookup via :meth:`header`).
    body_iter:
        An iterator that yields raw bytes chunks.  The underlying connection is
        held open until the iterator is exhausted or garbage-collected.
    """

    status_code: int
    headers: Headers
    body_iter: Iterator[bytes]

    def header(self, name: str, default: str = "") -> str:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def drain(self) -> None:
        """Consume and discard the body iterator, releasing the connection."""
        for _ in self.body_iter:
            pass


# ---------------------------------------------------------------------------
# requests-backed transport
# ---------------------------------------------------------------------------


class RequestsDicomwebTransport:
    """Production DICOMweb transport backed by ``requests``.

    Compared to :class:`~dicomforge.dicomweb.UrllibDicomwebTransport`, this
    transport provides:

    - **Connection pooling** — a single :class:`requests.Session` is reused
      across requests, avoiding per-request TCP hand-shakes.
    - **TLS client certificates** — pass a cert/key pair for mutual TLS
      authentication required by some PACS systems.
    - **Streaming response** — :meth:`stream` yields body bytes as they arrive
      so large WADO-RS study responses do not need to be fully buffered.

    Parameters
    ----------
    timeout:
        Seconds to wait for the server to send response headers (not the
        entire body).  ``None`` means wait forever.
    cert:
        TLS client certificate.  Pass a single path to a PEM file that
        contains both certificate and private key, or a ``(cert, key)`` tuple
        where each element is a path to a separate PEM file.
    verify:
        Server certificate verification.  ``True`` (default) uses the system
        CA bundle.  Pass a path to a CA bundle file to use a custom CA.
        ``False`` disables verification — only for testing.
    pool_connections:
        Number of HTTP adapters (one per host prefix).  Increase when
        connecting to many different DICOMweb hosts.
    pool_maxsize:
        Maximum number of keep-alive connections per host adapter.

    Raises
    ------
    MissingBackendError
        When ``requests`` is not installed.
    """

    def __init__(
        self,
        *,
        timeout: Optional[float] = 30.0,
        cert: Optional[Union[str, Tuple[str, str]]] = None,
        verify: Union[bool, str] = True,
        pool_connections: int = 10,
        pool_maxsize: int = 10,
    ) -> None:
        try:
            import requests
            import requests.adapters
        except ImportError as exc:
            raise MissingBackendError(
                "RequestsDicomwebTransport requires the requests library. "
                "Install with `pip install dicomforge[transport]`."
            ) from exc

        self._requests = requests
        self.timeout = timeout
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        if cert is not None:
            session.cert = cert
        session.verify = verify
        self._session = session

    def request(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Body = None,
    ) -> DicomwebResponse:
        """Send a request and buffer the full response body."""
        data = _encode_body(body)
        resp = self._session.request(
            method,
            url,
            headers=dict(headers),
            data=data,
            timeout=self.timeout,
        )
        return DicomwebResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body=resp.content,
        )

    def stream(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Body = None,
        *,
        chunk_size: int = 65536,
    ) -> StreamingDicomwebResponse:
        """Send a request and return a :class:`StreamingDicomwebResponse`.

        The body is *not* buffered; the caller iterates over
        :attr:`~StreamingDicomwebResponse.body_iter` to consume it in chunks
        of at most *chunk_size* bytes.

        Parameters
        ----------
        method:
            HTTP method (``"GET"``, ``"POST"``, etc.).
        url:
            Full request URL.
        headers:
            Request headers.
        body:
            Optional request body.
        chunk_size:
            Maximum bytes per yielded chunk.

        Returns
        -------
        StreamingDicomwebResponse
            Response with status, headers, and a lazy body iterator.
        """
        data = _encode_body(body)
        resp = self._session.request(
            method,
            url,
            headers=dict(headers),
            data=data,
            timeout=self.timeout,
            stream=True,
        )
        return StreamingDicomwebResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body_iter=resp.iter_content(chunk_size=chunk_size),
        )

    def close(self) -> None:
        """Release all pooled connections."""
        self._session.close()

    def __enter__(self) -> "RequestsDicomwebTransport":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------


class RetryTransport:
    """Transport decorator that retries failed requests with exponential back-off.

    Wraps any transport that implements the
    :class:`~dicomforge.dicomweb.DicomwebTransport` protocol.  If the wrapped
    transport also exposes a ``stream()`` method, :meth:`stream` delegates to
    it **without retry** — re-issuing a streaming request would require
    replaying the original body, which is not generally safe.

    Parameters
    ----------
    transport:
        The underlying transport to decorate.
    max_retries:
        Maximum number of retry attempts *after* the first failure.
        ``0`` means no retries (same as not using this decorator).
    backoff_base:
        Base delay in seconds for the first retry.  Subsequent delays are
        multiplied by ``2 ** attempt`` up to *backoff_max*.
    backoff_max:
        Maximum delay in seconds between retries.
    jitter:
        Fraction of the computed delay to add as random noise, reducing
        thundering-herd effects when many clients retry simultaneously.
        ``0.1`` means ±10 % of the delay.
    retryable_status_codes:
        HTTP status codes that trigger a retry.  Defaults to the set of
        transient error codes: 429, 500, 502, 503, 504.

    Example
    -------
    ::

        from dicomforge.transport import RequestsDicomwebTransport, RetryTransport

        transport = RetryTransport(
            RequestsDicomwebTransport(timeout=30),
            max_retries=4,
            backoff_base=0.5,
            backoff_max=30.0,
        )
    """

    def __init__(
        self,
        transport: Any,
        *,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_max: float = 60.0,
        jitter: float = 0.1,
        retryable_status_codes: Iterable[int] = _DEFAULT_RETRYABLE_STATUSES,
    ) -> None:
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries}.")
        if backoff_base < 0:
            raise ValueError(f"backoff_base must be >= 0, got {backoff_base}.")
        if not 0.0 <= jitter <= 1.0:
            raise ValueError(f"jitter must be in [0, 1], got {jitter}.")
        self._transport = transport
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.jitter = jitter
        self._retryable = frozenset(retryable_status_codes)

    def request(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Body = None,
    ) -> DicomwebResponse:
        """Send a request, retrying on transient errors."""
        response: DicomwebResponse
        for attempt in range(self.max_retries + 1):
            response = self._transport.request(method, url, headers, body)
            if response.status_code not in self._retryable or attempt == self.max_retries:
                return response
            delay = min(self.backoff_base * (2.0 ** attempt), self.backoff_max)
            noise = delay * self.jitter * random.random()
            time.sleep(delay + noise)
        return response  # satisfies type checker; loop always returns above

    def stream(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Body = None,
        **kwargs: Any,
    ) -> "StreamingDicomwebResponse":
        """Delegate streaming to the wrapped transport (no retry on streams)."""
        if not hasattr(self._transport, "stream"):
            raise AttributeError(
                f"{type(self._transport).__name__!r} does not support streaming. "
                "Use RequestsDicomwebTransport or another streaming-capable transport."
            )
        return self._transport.stream(method, url, headers, body, **kwargs)


# ---------------------------------------------------------------------------
# Bearer token auth decorator
# ---------------------------------------------------------------------------


class BearerTokenTransport:
    """Transport decorator that injects an OAuth 2.0 Bearer token header.

    Wraps any transport and adds ``Authorization: Bearer <token>`` to every
    request.  Use this with :class:`RetryTransport` and
    :class:`RequestsDicomwebTransport` to build a full production stack.

    Parameters
    ----------
    transport:
        The underlying transport to decorate.
    token:
        Bearer token string (without the ``Bearer`` prefix).

    Example
    -------
    ::

        from dicomforge.transport import (
            BearerTokenTransport,
            RequestsDicomwebTransport,
            RetryTransport,
        )
        from dicomforge.dicomweb import DicomwebClient

        client = DicomwebClient(
            "https://dicom.example/wado",
            BearerTokenTransport(
                RetryTransport(RequestsDicomwebTransport()),
                token=get_access_token(),
            ),
        )
    """

    def __init__(self, transport: Any, token: str) -> None:
        self._transport = transport
        self.token = token

    def request(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Body = None,
    ) -> DicomwebResponse:
        """Send a request with the Bearer token injected."""
        merged: MutableHeaders = dict(headers)
        merged["Authorization"] = f"Bearer {self.token}"
        return self._transport.request(method, url, merged, body)

    def stream(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Body = None,
        **kwargs: Any,
    ) -> "StreamingDicomwebResponse":
        """Send a streaming request with the Bearer token injected."""
        if not hasattr(self._transport, "stream"):
            raise AttributeError(
                f"{type(self._transport).__name__!r} does not support streaming."
            )
        merged: MutableHeaders = dict(headers)
        merged["Authorization"] = f"Bearer {self.token}"
        return self._transport.stream(method, url, merged, body, **kwargs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _encode_body(body: Body) -> Optional[bytes]:
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    return body.encode("utf-8")
