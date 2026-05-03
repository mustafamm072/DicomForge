"""Codec capability registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from dicomforge.errors import UnsupportedTransferSyntaxError
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.uids import TransferSyntaxUID


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


def default_registry() -> CodecRegistry:
    """Return support for uncompressed syntaxes available in the lightweight core."""

    return CodecRegistry(
        [
            Codec(
                name="native-uncompressed",
                transfer_syntax_uids=frozenset(
                    {
                        TransferSyntaxUID.ImplicitVRLittleEndian,
                        TransferSyntaxUID.ExplicitVRLittleEndian,
                        TransferSyntaxUID.ExplicitVRBigEndian,
                    }
                ),
                can_decode=True,
                can_encode=True,
            )
        ]
    )
