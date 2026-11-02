"""Strict bounded-buffer multipart parsing for binary DICOMweb responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping


@dataclass(frozen=True)
class MultipartChunk:
    headers: Mapping[str, str]
    data: bytes
    final: bool = False


def iter_multipart_chunks(
    content_type: str, chunks: Iterable[bytes], *, max_header_bytes: int = 65536,
    max_part_bytes: int = 2 * 1024 ** 3,
) -> Iterator[MultipartChunk]:
    """Yield part chunks without holding an entire instance in memory.

    Every part ends in a final=True event after its delimiter is verified.
    EOF before a closing delimiter raises; consumers must stage partial output.
    Limits are configurable, and incoming transport chunks bound buffer growth.
    """
    from dicomforge.dicomweb import DicomwebError, _boundary_from_content_type, _parse_part_headers

    if max_header_bytes <= 0 or max_part_bytes <= 0:
        raise ValueError("Multipart limits must be positive")
    boundary = _boundary_from_content_type(content_type)
    if not boundary or len(boundary) > 70 or b"\r" in boundary or b"\n" in boundary:
        raise DicomwebError("Invalid multipart boundary")
    source = iter(chunks)
    buffer = bytearray()

    def fill() -> bool:
        try:
            value = next(source)
        except StopIteration:
            return False
        buffer.extend(value)
        return True

    first = b"--" + boundary + b"\r\n"
    while True:
        position = buffer.find(first)
        if position >= 0:
            del buffer[:position + len(first)]
            break
        if len(buffer) > max_header_bytes or not fill():
            raise DicomwebError("Missing initial multipart delimiter")

    marker = b"\r\n--" + boundary
    while True:
        while True:
            position = buffer.find(b"\r\n\r\n")
            if position >= 0:
                if position > max_header_bytes:
                    raise DicomwebError("Multipart headers exceed configured limit")
                headers = _parse_part_headers(bytes(buffer[:position]))
                del buffer[:position + 4]
                break
            if len(buffer) > max_header_bytes or not fill():
                raise DicomwebError("Truncated or oversized multipart headers")
        size = 0
        while True:
            position = buffer.find(marker)
            if position >= 0:
                needed = position + len(marker) + 2
                while len(buffer) < needed:
                    if not fill():
                        raise DicomwebError("Truncated multipart delimiter")
                suffix = bytes(buffer[position + len(marker):needed])
                if suffix == b"--":
                    while len(buffer) < needed + 2 and fill():
                        pass
                    if len(buffer) > needed and buffer[needed:needed + 2] != b"\r\n":
                        suffix = b"invalid"  # Closing-prefix bytes inside binary payload.
                if suffix in (b"--", b"\r\n"):
                    data = bytes(buffer[:position])
                    size += len(data)
                    if size > max_part_bytes:
                        raise DicomwebError("Multipart part exceeds configured byte limit")
                    yield MultipartChunk(headers, data, final=True)
                    del buffer[:needed]
                    if suffix == b"--":
                        return
                    break
                # A delimiter prefix inside binary content is ordinary payload.
                amount = position + 2
            else:
                amount = max(0, len(buffer) - len(marker) - 2)
            if amount:
                size += amount
                if size > max_part_bytes:
                    raise DicomwebError("Multipart part exceeds configured byte limit")
                yield MultipartChunk(headers, bytes(buffer[:amount]))
                del buffer[:amount]
            elif not fill():
                raise DicomwebError("Truncated multipart body: closing delimiter missing")
