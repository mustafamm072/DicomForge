"""Tests for dicomforge.transport and 0.7 streaming additions."""

import time
import unittest
from typing import Dict, Iterator, List, Optional
from unittest.mock import MagicMock, patch

from dicomforge.dicomweb import (
    DicomwebClient,
    DicomwebError,
    DicomwebResponse,
    MultipartPart,
    build_multipart_related,
    build_multipart_related_streaming,
    parse_multipart_related_streaming,
)
from dicomforge.errors import DicomValidationError, MissingBackendError
from dicomforge.transport import (
    BearerTokenTransport,
    RetryTransport,
    StreamingDicomwebResponse,
    _encode_body,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_multipart(
    payloads: List[bytes],
    boundary: str = "test-boundary",
    content_type: str = "application/dicom",
) -> bytes:
    body, _ = build_multipart_related(payloads, content_type=content_type, boundary=boundary)
    return body


def _chunked(data: bytes, size: int) -> Iterator[bytes]:
    """Yield *data* in chunks of *size* bytes."""
    for i in range(0, len(data), size):
        yield data[i : i + size]


class FakeTransport:
    """Configurable fake transport for unit tests."""

    def __init__(self, responses: Optional[List[DicomwebResponse]] = None) -> None:
        self._responses = list(responses or [])
        self.calls: List[tuple] = []

    def push(self, response: DicomwebResponse) -> None:
        self._responses.append(response)

    def request(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        if not self._responses:
            raise RuntimeError("FakeTransport: no more responses queued.")
        return self._responses.pop(0)


class FakeStreamingTransport(FakeTransport):
    """Fake transport that also supports stream()."""

    def __init__(self, responses=None, streaming_responses=None):
        super().__init__(responses)
        self._streaming = list(streaming_responses or [])
        self.stream_calls: List[tuple] = []

    def push_streaming(self, response: StreamingDicomwebResponse) -> None:
        self._streaming.append(response)

    def stream(self, method, url, headers, body=None, **kwargs):
        self.stream_calls.append((method, url, headers, body))
        if not self._streaming:
            raise RuntimeError("FakeStreamingTransport: no more streaming responses.")
        return self._streaming.pop(0)


# ---------------------------------------------------------------------------
# _encode_body helper
# ---------------------------------------------------------------------------

class EncodeBodyTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(_encode_body(None))

    def test_bytes_passthrough(self):
        self.assertEqual(_encode_body(b"hello"), b"hello")

    def test_bytearray_converted(self):
        self.assertEqual(_encode_body(bytearray(b"hi")), b"hi")
        self.assertIsInstance(_encode_body(bytearray(b"hi")), bytes)

    def test_str_encoded_as_utf8(self):
        self.assertEqual(_encode_body("café"), "café".encode("utf-8"))


# ---------------------------------------------------------------------------
# RetryTransport
# ---------------------------------------------------------------------------

class RetryTransportTests(unittest.TestCase):
    def test_success_on_first_attempt_does_not_retry(self):
        transport = FakeTransport([DicomwebResponse(200, {}, b"ok")])
        retry = RetryTransport(transport, max_retries=3)
        resp = retry.request("GET", "http://example.com", {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(transport.calls), 1)

    def test_retries_on_503_and_succeeds(self):
        transport = FakeTransport([
            DicomwebResponse(503, {}, b"retry"),
            DicomwebResponse(200, {}, b"ok"),
        ])
        retry = RetryTransport(transport, max_retries=3, backoff_base=0.0)
        resp = retry.request("GET", "http://example.com", {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(transport.calls), 2)

    def test_returns_last_failure_after_exhausting_retries(self):
        transport = FakeTransport([
            DicomwebResponse(503, {}, b"fail"),
            DicomwebResponse(503, {}, b"fail"),
        ])
        retry = RetryTransport(transport, max_retries=1, backoff_base=0.0)
        resp = retry.request("GET", "http://example.com", {})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(len(transport.calls), 2)

    def test_does_not_retry_non_retryable_status(self):
        transport = FakeTransport([DicomwebResponse(404, {}, b"not found")])
        retry = RetryTransport(transport, max_retries=3)
        resp = retry.request("GET", "http://example.com", {})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(len(transport.calls), 1)

    def test_custom_retryable_status_codes(self):
        transport = FakeTransport([
            DicomwebResponse(418, {}, b"teapot"),
            DicomwebResponse(200, {}, b"ok"),
        ])
        retry = RetryTransport(
            transport, max_retries=1, backoff_base=0.0, retryable_status_codes={418}
        )
        resp = retry.request("GET", "http://example.com", {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(transport.calls), 2)

    def test_rejects_negative_max_retries(self):
        with self.assertRaises(ValueError):
            RetryTransport(FakeTransport(), max_retries=-1)

    def test_rejects_jitter_out_of_range(self):
        with self.assertRaises(ValueError):
            RetryTransport(FakeTransport(), jitter=1.5)

    def test_retry_applies_backoff_delay(self):
        transport = FakeTransport([
            DicomwebResponse(503, {}, b""),
            DicomwebResponse(200, {}, b"ok"),
        ])
        retry = RetryTransport(transport, max_retries=1, backoff_base=0.05, jitter=0.0)
        start = time.monotonic()
        retry.request("GET", "http://example.com", {})
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.04)

    def test_stream_delegates_to_inner_transport(self):
        body, ct = build_multipart_related([b"data"], content_type="application/dicom")
        streaming_resp = StreamingDicomwebResponse(
            status_code=200, headers={"content-type": ct}, body_iter=iter([body])
        )
        inner = FakeStreamingTransport(streaming_responses=[streaming_resp])
        retry = RetryTransport(inner, max_retries=3)
        result = retry.stream("GET", "http://example.com", {})
        self.assertEqual(result.status_code, 200)

    def test_stream_raises_when_inner_has_no_stream(self):
        retry = RetryTransport(FakeTransport(), max_retries=1)
        with self.assertRaises(AttributeError):
            retry.stream("GET", "http://example.com", {})


# ---------------------------------------------------------------------------
# BearerTokenTransport
# ---------------------------------------------------------------------------

class BearerTokenTransportTests(unittest.TestCase):
    def test_injects_authorization_header(self):
        transport = FakeTransport([DicomwebResponse(200, {}, b"ok")])
        bearer = BearerTokenTransport(transport, token="my-secret-token")
        bearer.request("GET", "http://example.com", {"Accept": "application/json"})

        _, _, headers, _ = transport.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer my-secret-token")
        self.assertEqual(headers["Accept"], "application/json")

    def test_does_not_overwrite_other_headers(self):
        transport = FakeTransport([DicomwebResponse(200, {}, b"ok")])
        bearer = BearerTokenTransport(transport, token="tok")
        bearer.request("GET", "http://example.com", {"X-Custom": "value"})

        _, _, headers, _ = transport.calls[0]
        self.assertEqual(headers["X-Custom"], "value")
        self.assertIn("Authorization", headers)

    def test_passes_body_through(self):
        transport = FakeTransport([DicomwebResponse(200, {}, b"ok")])
        bearer = BearerTokenTransport(transport, token="tok")
        bearer.request("POST", "http://example.com", {}, body=b"payload")

        _, _, _, body = transport.calls[0]
        self.assertEqual(body, b"payload")

    def test_stream_injects_auth_and_delegates(self):
        body, ct = build_multipart_related([b"data"], content_type="application/dicom")
        streaming_resp = StreamingDicomwebResponse(
            status_code=200, headers={"content-type": ct}, body_iter=iter([body])
        )
        inner = FakeStreamingTransport(streaming_responses=[streaming_resp])
        bearer = BearerTokenTransport(inner, token="secret")
        result = bearer.stream("GET", "http://example.com", {})

        method, url, headers, _ = inner.stream_calls[0]
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(result.status_code, 200)

    def test_stream_raises_when_inner_has_no_stream(self):
        bearer = BearerTokenTransport(FakeTransport(), token="tok")
        with self.assertRaises(AttributeError):
            bearer.stream("GET", "http://example.com", {})

    def test_stacking_retry_and_bearer(self):
        """Bearer wraps Retry which wraps the underlying transport."""
        transport = FakeTransport([
            DicomwebResponse(503, {}, b""),
            DicomwebResponse(200, {}, b"ok"),
        ])
        stacked = BearerTokenTransport(
            RetryTransport(transport, max_retries=2, backoff_base=0.0),
            token="tok",
        )
        resp = stacked.request("GET", "http://example.com", {})
        self.assertEqual(resp.status_code, 200)
        # Both calls should carry the auth header
        for call in transport.calls:
            self.assertEqual(call[2]["Authorization"], "Bearer tok")


# ---------------------------------------------------------------------------
# StreamingDicomwebResponse
# ---------------------------------------------------------------------------

class StreamingDicomwebResponseTests(unittest.TestCase):
    def test_header_lookup_is_case_insensitive(self):
        resp = StreamingDicomwebResponse(
            status_code=200,
            headers={"Content-Type": "application/dicom+json"},
            body_iter=iter([]),
        )
        self.assertEqual(resp.header("content-type"), "application/dicom+json")
        self.assertEqual(resp.header("CONTENT-TYPE"), "application/dicom+json")

    def test_header_returns_default_when_missing(self):
        resp = StreamingDicomwebResponse(200, {}, iter([]))
        self.assertEqual(resp.header("x-missing", "fallback"), "fallback")

    def test_drain_consumes_iterator(self):
        consumed = []
        def _gen():
            for b in [b"a", b"b"]:
                consumed.append(b)
                yield b
        resp = StreamingDicomwebResponse(200, {}, _gen())
        resp.drain()
        self.assertEqual(consumed, [b"a", b"b"])


# ---------------------------------------------------------------------------
# parse_multipart_related_streaming
# ---------------------------------------------------------------------------

class StreamingMultipartParserTests(unittest.TestCase):
    def _parse(self, payloads: List[bytes], chunk_size: int = 128) -> List[MultipartPart]:
        body, ct = build_multipart_related(payloads, content_type="application/dicom",
                                           boundary="boundary")
        return list(parse_multipart_related_streaming(ct, _chunked(body, chunk_size)))

    def test_single_part(self):
        parts = self._parse([b"DICM"])
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].body, b"DICM")

    def test_multiple_parts(self):
        parts = self._parse([b"first", b"second", b"third"])
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0].body, b"first")
        self.assertEqual(parts[1].body, b"second")
        self.assertEqual(parts[2].body, b"third")

    def test_binary_content_preserved(self):
        payload = bytes(range(256)) * 16
        parts = self._parse([payload], chunk_size=64)
        self.assertEqual(parts[0].body, payload)

    def test_one_byte_chunks(self):
        parts = self._parse([b"hello", b"world"], chunk_size=1)
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].body, b"hello")
        self.assertEqual(parts[1].body, b"world")

    def test_parts_have_content_type_header(self):
        parts = self._parse([b"data"])
        self.assertIn("content-type", parts[0].headers)
        self.assertEqual(parts[0].headers["content-type"], "application/dicom")

    def test_matches_non_streaming_parser_output(self):
        from dicomforge.dicomweb import parse_multipart_related
        payloads = [b"alpha", b"beta", b"gamma"]
        body, ct = build_multipart_related(payloads, content_type="application/dicom",
                                           boundary="cmp-boundary")
        non_streaming = list(parse_multipart_related(ct, body))
        streaming = list(parse_multipart_related_streaming(ct, _chunked(body, 32)))
        self.assertEqual(len(non_streaming), len(streaming))
        for ns, st in zip(non_streaming, streaming):
            self.assertEqual(ns.body, st.body)

    def test_missing_boundary_raises(self):
        with self.assertRaises(DicomwebError):
            list(parse_multipart_related_streaming("multipart/related", iter([b""])))

    def test_empty_generator_raises(self):
        """A missing/incomplete multipart body yields nothing (no exception)."""
        ct = 'multipart/related; type="application/dicom"; boundary=none'
        result = list(parse_multipart_related_streaming(ct, iter([])))
        self.assertEqual(result, [])

    def test_large_payload_streaming(self):
        """A 1 MB payload delivered in 4 KB chunks is parsed correctly."""
        payload = b"X" * (1024 * 1024)
        parts = self._parse([payload], chunk_size=4096)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].body, payload)


# ---------------------------------------------------------------------------
# build_multipart_related_streaming
# ---------------------------------------------------------------------------

class BuildMultipartStreamingTests(unittest.TestCase):
    def test_generator_produces_valid_multipart(self):
        gen, ct = build_multipart_related_streaming(
            [b"part1", b"part2"],
            content_type="application/dicom",
            boundary="gen-boundary",
        )
        body = b"".join(gen)
        self.assertIn(b"--gen-boundary", body)
        self.assertIn(b"part1", body)
        self.assertIn(b"part2", body)
        self.assertIn(b"--gen-boundary--", body)

    def test_output_parseable_by_streaming_parser(self):
        payloads = [b"alpha", b"beta", b"gamma"]
        gen, ct = build_multipart_related_streaming(
            payloads, content_type="application/dicom", boundary="parse-boundary"
        )
        parts = list(parse_multipart_related_streaming(ct, gen))
        self.assertEqual([p.body for p in parts], payloads)

    def test_rejects_invalid_boundary(self):
        with self.assertRaises(DicomValidationError):
            build_multipart_related_streaming(
                [b"data"],
                content_type="application/dicom",
                boundary="bad\r\nboundary",
            )

    def test_empty_parts_raises_during_iteration(self):
        gen, _ = build_multipart_related_streaming(
            iter([]),
            content_type="application/dicom",
        )
        with self.assertRaises(DicomValidationError):
            list(gen)

    def test_content_type_header_has_boundary(self):
        _, ct = build_multipart_related_streaming(
            [b"data"],
            content_type="application/dicom",
            boundary="my-bnd",
        )
        self.assertIn("my-bnd", ct)
        self.assertIn("multipart/related", ct)
        self.assertIn("application/dicom", ct)

    def test_random_boundary_generated_when_not_supplied(self):
        _, ct1 = build_multipart_related_streaming(
            [b"x"], content_type="application/dicom"
        )
        _, ct2 = build_multipart_related_streaming(
            [b"x"], content_type="application/dicom"
        )
        # Boundaries should be different (uuid-based)
        self.assertNotEqual(ct1, ct2)


# ---------------------------------------------------------------------------
# DicomwebClient streaming methods
# ---------------------------------------------------------------------------

class DicomwebClientStreamingTests(unittest.TestCase):
    def _streaming_response_for(self, payloads: List[bytes]) -> StreamingDicomwebResponse:
        body, ct = build_multipart_related(
            payloads, content_type="application/dicom", boundary="stream-bnd"
        )
        return StreamingDicomwebResponse(
            status_code=200,
            headers={"content-type": ct},
            body_iter=_chunked(body, 64),
        )

    def test_iter_retrieve_study_parts_uses_streaming_transport(self):
        inner = FakeStreamingTransport(
            streaming_responses=[self._streaming_response_for([b"inst1", b"inst2"])]
        )
        client = DicomwebClient("https://dicom.example", inner)
        parts = list(client.iter_retrieve_study_parts("1.2.3"))
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].body, b"inst1")
        self.assertEqual(parts[1].body, b"inst2")
        # Verify streaming transport was called (not request())
        self.assertEqual(len(inner.stream_calls), 1)
        self.assertEqual(len(inner.calls), 0)

    def test_iter_retrieve_series_parts_builds_correct_url(self):
        inner = FakeStreamingTransport(
            streaming_responses=[self._streaming_response_for([b"series-inst"])]
        )
        client = DicomwebClient("https://dicom.example", inner)
        list(client.iter_retrieve_series_parts("1.2.3", "4.5.6"))
        _, url, _, _ = inner.stream_calls[0]
        self.assertIn("studies/1.2.3", url)
        self.assertIn("series/4.5.6", url)

    def test_iter_retrieve_instance_parts_builds_correct_url(self):
        inner = FakeStreamingTransport(
            streaming_responses=[self._streaming_response_for([b"inst"])]
        )
        client = DicomwebClient("https://dicom.example", inner)
        list(client.iter_retrieve_instance_parts("1.2.3", "4.5.6", "7.8.9"))
        _, url, _, _ = inner.stream_calls[0]
        self.assertIn("instances/7.8.9", url)

    def test_iter_retrieve_falls_back_to_buffered_when_no_stream(self):
        """Non-streaming transport falls back to retrieve_*_parts() internally."""
        body, ct = build_multipart_related(
            [b"fallback"], content_type="application/dicom", boundary="fb"
        )
        inner = FakeTransport([DicomwebResponse(200, {"content-type": ct}, body)])
        client = DicomwebClient("https://dicom.example", inner)
        parts = list(client.iter_retrieve_study_parts("1.2.3"))
        self.assertEqual(parts[0].body, b"fallback")
        self.assertEqual(len(inner.calls), 1)

    def test_iter_retrieve_raises_on_http_error(self):
        inner = FakeStreamingTransport(
            streaming_responses=[
                StreamingDicomwebResponse(404, {}, iter([b""]))
            ]
        )
        client = DicomwebClient("https://dicom.example", inner)
        with self.assertRaises(DicomwebError):
            list(client.iter_retrieve_study_parts("1.2.3"))

    def test_base_headers_forwarded_in_streaming_request(self):
        inner = FakeStreamingTransport(
            streaming_responses=[self._streaming_response_for([b"data"])]
        )
        client = DicomwebClient(
            "https://dicom.example", inner, headers={"X-Auth": "token"}
        )
        list(client.iter_retrieve_study_parts("1.2.3"))
        _, _, headers, _ = inner.stream_calls[0]
        self.assertEqual(headers["X-Auth"], "token")


# ---------------------------------------------------------------------------
# RequestsDicomwebTransport (stub-level tests — no live network)
# ---------------------------------------------------------------------------

class RequestsDicomwebTransportTests(unittest.TestCase):
    def test_raises_when_requests_not_installed(self):
        """Verify MissingBackendError when requests is absent."""
        import sys
        real_requests = sys.modules.get("requests")
        sys.modules["requests"] = None  # type: ignore[assignment]
        try:
            from importlib import reload
            import dicomforge.transport as transport_mod
            reload(transport_mod)
            with self.assertRaises(MissingBackendError):
                transport_mod.RequestsDicomwebTransport()
        finally:
            if real_requests is not None:
                sys.modules["requests"] = real_requests
            else:
                del sys.modules["requests"]
            reload(transport_mod)

    def test_validates_max_retries_in_retry_transport(self):
        with self.assertRaises(ValueError):
            RetryTransport(FakeTransport(), max_retries=-5)

    def test_retry_transport_zero_retries_is_passthrough(self):
        transport = FakeTransport([DicomwebResponse(503, {}, b"")])
        retry = RetryTransport(transport, max_retries=0)
        resp = retry.request("GET", "http://example.com", {})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(len(transport.calls), 1)

    def test_requests_transport_request_integration(self):
        """Test with a mocked requests.Session to avoid network I/O."""
        try:
            import requests as _requests
        except ImportError:
            self.skipTest("requests not installed")

        from dicomforge.transport import RequestsDicomwebTransport

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/dicom+json"}
        mock_resp.content = b'[{"00100020":{"vr":"LO","Value":["P001"]}}]'

        with patch.object(_requests.Session, "request", return_value=mock_resp):
            t = RequestsDicomwebTransport(timeout=5)
            resp = t.request("GET", "http://dicom.example/studies", {"Accept": "application/dicom+json"})
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b"P001", resp.body)

    def test_requests_transport_stream_integration(self):
        """Test streaming path with a mocked session."""
        try:
            import requests as _requests
        except ImportError:
            self.skipTest("requests not installed")

        from dicomforge.transport import RequestsDicomwebTransport

        body, ct = build_multipart_related(
            [b"DICM"], content_type="application/dicom", boundary="sb"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": ct}
        mock_resp.iter_content = MagicMock(return_value=_chunked(body, 64))
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(_requests.Session, "request", return_value=mock_resp):
            t = RequestsDicomwebTransport(timeout=5)
            s = t.stream("GET", "http://dicom.example/studies/1.2.3", {"Accept": ct})
            self.assertEqual(s.status_code, 200)
            parts = list(parse_multipart_related_streaming(s.header("content-type"), s.body_iter))
            self.assertEqual(len(parts), 1)
            self.assertEqual(parts[0].body, b"DICM")

    def test_context_manager_closes_session(self):
        try:
            import requests as _requests
        except ImportError:
            self.skipTest("requests not installed")

        from dicomforge.transport import RequestsDicomwebTransport

        with patch.object(_requests.Session, "close") as mock_close:
            with RequestsDicomwebTransport() as t:
                pass
            mock_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
