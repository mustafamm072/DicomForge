"""Codec capability registry."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from dicomforge.errors import UnsupportedTransferSyntaxError
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.uids import TransferSyntaxUID

PYDICOM_PIXEL_TRANSFER_SYNTAX_UIDS = frozenset(
    {
        TransferSyntaxUID.JPEGBaselineProcess1,
        TransferSyntaxUID.JPEGExtendedProcess2and4,
        TransferSyntaxUID.JPEGLossless,
        TransferSyntaxUID.JPEGLSLossless,
        TransferSyntaxUID.JPEGLSNearLossless,
        TransferSyntaxUID.JPEG2000Lossless,
        TransferSyntaxUID.JPEG2000,
        TransferSyntaxUID.RLELossless,
    }
)


@dataclass(frozen=True)
class Codec:
    """Describes a codec implementation and its supported syntaxes."""

    name: str
    transfer_syntax_uids: frozenset[str]
    can_decode: bool = True
    can_encode: bool = False

    def supports(self, transfer_syntax_uid: str, *, encode: bool = False) -> bool:
        if transfer_syntax_uid not in self.transfer_syntax_uids:
            return False
        return self.can_encode if encode else self.can_decode


class CodecRegistry:
    """Registry used to check support before pixel or transcoding work starts."""

    def __init__(self, codecs: Optional[Iterable[Codec]] = None) -> None:
        self._codecs: Dict[str, Codec] = {}
        if codecs:
            for codec in codecs:
                self.register(codec)

    def register(self, codec: Codec) -> None:
        self._codecs[codec.name] = codec

    def find(self, syntax: TransferSyntax, *, encode: bool = False) -> Codec:
        for codec in self._codecs.values():
            if codec.supports(syntax.uid, encode=encode):
                return codec
        action = "encode" if encode else "decode"
        raise UnsupportedTransferSyntaxError(
            f"No codec is registered to {action} {syntax.name} ({syntax.uid}). "
            "Install or register a codec package before processing pixel data."
        )

    def supports(self, syntax: TransferSyntax, *, encode: bool = False) -> bool:
        try:
            self.find(syntax, encode=encode)
        except UnsupportedTransferSyntaxError:
            return False
        return True


_DEFAULT_REGISTRY: Optional[CodecRegistry] = None


def default_registry() -> CodecRegistry:
    """Return cached codec support detected in the current environment.

    The lightweight core always registers native uncompressed syntaxes.  When
    pydicom is installed, a pydicom pixel bridge is also registered for common
    encapsulated transfer syntaxes.  Actual compressed decoding still depends
    on whichever pydicom pixel plugins are installed in the caller's
    environment.
    """

    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = CodecRegistry([_native_uncompressed_codec()])
    _register_optional_codecs(_DEFAULT_REGISTRY)
    return _DEFAULT_REGISTRY


def _native_uncompressed_codec() -> Codec:
    return Codec(
        name="native-uncompressed",
        transfer_syntax_uids=frozenset(
            {
                TransferSyntaxUID.ImplicitVRLittleEndian,
                TransferSyntaxUID.ExplicitVRLittleEndian,
                TransferSyntaxUID.DeflatedExplicitVRLittleEndian,
                TransferSyntaxUID.ExplicitVRBigEndian,
            }
        ),
        can_decode=True,
        can_encode=True,
    )


def _register_optional_codecs(registry: CodecRegistry) -> None:
    pydicom_codec = pydicom_pixel_codec()
    if pydicom_codec is not None and pydicom_codec.name not in registry._codecs:
        registry.register(pydicom_codec)


def pydicom_pixel_codec() -> Optional[Codec]:
    """Return the optional pydicom pixel bridge when pydicom is importable."""

    try:
        importlib.import_module("pydicom")
    except ImportError:
        return None
    return Codec(
        name="pydicom-pixels",
        transfer_syntax_uids=PYDICOM_PIXEL_TRANSFER_SYNTAX_UIDS,
        can_decode=True,
        can_encode=False,
    )


def pydicom_pixel_registry() -> CodecRegistry:
    """Return a registry containing only the optional pydicom pixel bridge.

    This is useful for callers that want to compose their own registry without
    mutating the cached default registry.  When pydicom is unavailable, the
    returned registry is empty.
    """

    codec = pydicom_pixel_codec()
    return CodecRegistry([] if codec is None else [codec])
