"""Transfer syntax classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Dict

from dicomforge.uids import TransferSyntaxUID


@dataclass(frozen=True)
class TransferSyntax:
    """DICOM transfer syntax metadata."""

    uid: str
    name: str
    is_little_endian: bool
    is_explicit_vr: bool
    is_encapsulated: bool = False

    _KNOWN: ClassVar[Dict[str, "TransferSyntax"]] = {}

    @property
    def is_compressed(self) -> bool:
        return self.is_encapsulated

    @classmethod
    def register(
        cls,
        uid: str,
        name: str,
        *,
        is_little_endian: bool,
        is_explicit_vr: bool,
        is_encapsulated: bool = False,
    ) -> "TransferSyntax":
        syntax = cls(uid, name, is_little_endian, is_explicit_vr, is_encapsulated)
        cls._KNOWN[uid] = syntax
        return syntax

    @classmethod
    def from_uid(cls, uid: str) -> "TransferSyntax":
        known = cls._KNOWN.get(uid)
        if known is not None:
            return known
        return cls(
            uid=uid,
            name=f"Unknown Transfer Syntax {uid}",
            is_little_endian=True,
            is_explicit_vr=True,
            is_encapsulated=True,
        )


TransferSyntax.register(
    TransferSyntaxUID.ImplicitVRLittleEndian,
    "Implicit VR Little Endian",
    is_little_endian=True,
    is_explicit_vr=False,
)
TransferSyntax.register(
    TransferSyntaxUID.ExplicitVRLittleEndian,
    "Explicit VR Little Endian",
    is_little_endian=True,
    is_explicit_vr=True,
)
TransferSyntax.register(
    TransferSyntaxUID.DeflatedExplicitVRLittleEndian,
    "Deflated Explicit VR Little Endian",
    is_little_endian=True,
    is_explicit_vr=True,
)
TransferSyntax.register(
    TransferSyntaxUID.ExplicitVRBigEndian,
    "Explicit VR Big Endian",
    is_little_endian=False,
    is_explicit_vr=True,
)
TransferSyntax.register(
    TransferSyntaxUID.JPEGBaselineProcess1,
    "JPEG Baseline Process 1",
    is_little_endian=True,
    is_explicit_vr=True,
    is_encapsulated=True,
)
TransferSyntax.register(
    TransferSyntaxUID.JPEGLossless,
    "JPEG Lossless",
    is_little_endian=True,
    is_explicit_vr=True,
    is_encapsulated=True,
)
TransferSyntax.register(
    TransferSyntaxUID.JPEGLSLossless,
    "JPEG-LS Lossless",
    is_little_endian=True,
    is_explicit_vr=True,
    is_encapsulated=True,
)
TransferSyntax.register(
    TransferSyntaxUID.JPEG2000Lossless,
    "JPEG 2000 Lossless",
    is_little_endian=True,
    is_explicit_vr=True,
    is_encapsulated=True,
)
TransferSyntax.register(
    TransferSyntaxUID.RLELossless,
    "RLE Lossless",
    is_little_endian=True,
    is_explicit_vr=True,
    is_encapsulated=True,
)
