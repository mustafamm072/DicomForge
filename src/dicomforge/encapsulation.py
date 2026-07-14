"""Encapsulated (compressed) pixel-data value model.

Encapsulated transfer syntaxes store ``PixelData (7FE0,0010)`` as an
undefined-length sequence of fragments: a Basic Offset Table item followed by
one or more items of compressed bytes (DICOM PS3.5 Annex A.4).  Fragment
boundaries matter — for RLE Lossless each frame is exactly one fragment — so
the native reader must not flatten them away.

:class:`EncapsulatedPixelData` is a :class:`bytes` subclass.  Its byte value is
the concatenated fragment payload, which keeps every existing caller that
treats compressed ``PixelData`` as opaque ``bytes`` working unchanged, while
``.fragments`` and ``.basic_offset_table`` preserve the structure needed to
re-write the file faithfully or decode individual frames.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from dicomforge.errors import DicomValidationError

#: Byte size of the (FFFE,E000) item header preceding each fragment.
_ITEM_HEADER_SIZE = 8


class EncapsulatedPixelData(bytes):
    """Compressed ``PixelData`` with fragment boundaries preserved.

    Instances compare equal to (and can be used anywhere in place of) the
    plain concatenated fragment bytes.  Construct one from the compressed
    fragments themselves::

        value = EncapsulatedPixelData([fragment_a, fragment_b])
        value = EncapsulatedPixelData.from_frames(rle_fragments)

    Attributes
    ----------
    fragments:
        The compressed fragments, excluding the Basic Offset Table.
    basic_offset_table:
        Frame byte offsets from the Basic Offset Table, or ``()`` when the
        source file carried an empty table.
    """

    _fragments: Tuple[bytes, ...]
    _basic_offset_table: Tuple[int, ...]

    def __new__(
        cls,
        fragments: Iterable[bytes],
        basic_offset_table: Sequence[int] = (),
    ) -> "EncapsulatedPixelData":
        parts = tuple(bytes(fragment) for fragment in fragments)
        instance = super().__new__(cls, b"".join(parts))
        instance._fragments = parts
        instance._basic_offset_table = tuple(int(v) for v in basic_offset_table)
        return instance

    def __reduce__(self):  # type: ignore[override]
        # The default bytes reduce protocol would rebuild from the joined byte
        # string and lose (or corrupt) the fragment structure under pickle,
        # copy.copy, and copy.deepcopy.
        return (self.__class__, (list(self._fragments), list(self._basic_offset_table)))

    @classmethod
    def from_frames(cls, frames: Iterable[bytes]) -> "EncapsulatedPixelData":
        """Build encapsulated pixel data with one fragment per frame.

        A Basic Offset Table entry is computed for every frame, so multiframe
        objects written natively remain frame-addressable by other toolkits.
        """

        parts = tuple(bytes(frame) for frame in frames)
        offsets: List[int] = []
        position = 0
        for part in parts:
            offsets.append(position)
            padded = len(part) + (len(part) % 2)
            position += _ITEM_HEADER_SIZE + padded
        return cls(parts, offsets)

    @property
    def fragments(self) -> Tuple[bytes, ...]:
        return self._fragments

    @property
    def basic_offset_table(self) -> Tuple[int, ...]:
        return self._basic_offset_table

    def frame_fragments(self, number_of_frames: int) -> List[bytes]:
        """Return one compressed byte string per frame.

        Frames are resolved from the fragment count when it matches
        ``number_of_frames`` exactly (the common case — RLE requires it), or
        from the Basic Offset Table when frames span multiple fragments.
        """

        if number_of_frames <= 0:
            raise DicomValidationError(
                f"number_of_frames must be positive, got {number_of_frames}."
            )
        if number_of_frames == 1:
            return [bytes(self)]
        if len(self._fragments) == number_of_frames:
            return list(self._fragments)
        if len(self._basic_offset_table) == number_of_frames:
            return self._frames_from_offset_table(number_of_frames)
        raise DicomValidationError(
            f"Cannot split {len(self._fragments)} pixel-data fragment(s) into "
            f"{number_of_frames} frames: the fragment count does not match and "
            f"the Basic Offset Table has {len(self._basic_offset_table)} "
            "entries."
        )

    def _frames_from_offset_table(self, number_of_frames: int) -> List[bytes]:
        # Reconstruct each fragment's stream offset (item header + padded
        # payload) and group fragments between consecutive table entries.
        positions: List[int] = []
        position = 0
        for fragment in self._fragments:
            positions.append(position)
            padded = len(fragment) + (len(fragment) % 2)
            position += _ITEM_HEADER_SIZE + padded

        boundaries: List[int] = []
        for offset in self._basic_offset_table:
            try:
                boundaries.append(positions.index(offset))
            except ValueError:
                raise DicomValidationError(
                    f"Basic Offset Table offset {offset} does not point at a "
                    "fragment boundary."
                ) from None
        boundaries.append(len(self._fragments))

        frames: List[bytes] = []
        for index in range(number_of_frames):
            start, end = boundaries[index], boundaries[index + 1]
            if end < start:
                raise DicomValidationError(
                    "Basic Offset Table entries are not in ascending order."
                )
            frames.append(b"".join(self._fragments[start:end]))
        return frames


def as_encapsulated(value: object) -> Optional[EncapsulatedPixelData]:
    """Return *value* as :class:`EncapsulatedPixelData` when structure is known.

    Accepts an existing :class:`EncapsulatedPixelData` or a list/tuple of
    fragment byte strings (one fragment per frame).  Returns ``None`` for
    plain ``bytes`` — the caller must decide how to frame those.
    """

    if isinstance(value, EncapsulatedPixelData):
        return value
    if isinstance(value, (list, tuple)) and value and all(
        isinstance(item, (bytes, bytearray)) for item in value
    ):
        return EncapsulatedPixelData.from_frames(value)
    return None
