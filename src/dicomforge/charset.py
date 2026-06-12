"""DICOM character-set and person-name helpers.

The core stays dependency-free while covering the character sets most Python
medical-imaging applications need day to day: default ASCII, UTF-8, common
single-byte ISO 8859 sets, GB18030/GBK, and Python-backed ISO 2022 IR 87
Japanese plus ISO 2022 IR 149 Korean text.  Unsupported DICOM terms fail
explicitly instead of silently corrupting patient or physician names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, Union

from dicomforge.dataset import DicomDataset
from dicomforge.errors import CharacterSetError
from dicomforge.tags import Tag

SpecificCharacterSetValue = Union[str, Sequence[str], None]

DEFAULT_CHARACTER_SET = "ISO_IR 6"

_DICOM_TO_PYTHON_CODECS = {
    "": "ascii",
    "ISO_IR 6": "ascii",
    "ISO 2022 IR 6": "ascii",
    "ISO_IR 100": "latin_1",
    "ISO_IR 101": "iso8859_2",
    "ISO_IR 109": "iso8859_3",
    "ISO_IR 110": "iso8859_4",
    "ISO_IR 144": "iso8859_5",
    "ISO_IR 127": "iso8859_6",
    "ISO_IR 126": "iso8859_7",
    "ISO_IR 138": "iso8859_8",
    "ISO_IR 148": "iso8859_9",
    "ISO_IR 166": "iso8859_11",
    "ISO_IR 192": "utf-8",
    "GB18030": "gb18030",
    "GBK": "gbk",
    "ISO 2022 IR 87": "iso2022_jp",
    "ISO 2022 IR 149": "iso2022_kr",
}

_PYTHON_TO_DICOM_TERMS = {
    "ascii": "ISO_IR 6",
    "us-ascii": "ISO_IR 6",
    "latin_1": "ISO_IR 100",
    "latin-1": "ISO_IR 100",
    "iso8859_1": "ISO_IR 100",
    "iso-8859-1": "ISO_IR 100",
    "utf-8": "ISO_IR 192",
    "utf8": "ISO_IR 192",
    "gb18030": "GB18030",
    "gbk": "GBK",
    "iso2022_jp": "ISO 2022 IR 87",
    "iso-2022-jp": "ISO 2022 IR 87",
    "iso2022_kr": "ISO 2022 IR 149",
    "iso-2022-kr": "ISO 2022 IR 149",
}


@dataclass(frozen=True)
class PersonName:
    """Structured DICOM PN value.

    A PN value contains up to three component groups separated by ``=``:
    alphabetic, ideographic, and phonetic.  Each group contains up to five
    ``^``-separated name components: family, given, middle, prefix, suffix.
    """

    family_name: str = ""
    given_name: str = ""
    middle_name: str = ""
    name_prefix: str = ""
    name_suffix: str = ""
    ideographic: str = ""
    phonetic: str = ""

    @classmethod
    def parse(cls, value: Any) -> "PersonName":
        """Parse a DICOM PN string or pydicom-like PersonName object."""

        text = str(value or "")
        groups = text.split("=")
        if len(groups) > 3:
            raise CharacterSetError("DICOM PN values may contain at most three '=' groups.")
        alphabetic = _split_name_group(groups[0] if groups else "")
        return cls(
            family_name=alphabetic[0],
            given_name=alphabetic[1],
            middle_name=alphabetic[2],
            name_prefix=alphabetic[3],
            name_suffix=alphabetic[4],
            ideographic=groups[1] if len(groups) > 1 else "",
            phonetic=groups[2] if len(groups) > 2 else "",
        )

    def to_dicom_string(self) -> str:
        """Return this name in DICOM PN wire-value form."""

        for component in (
            self.family_name,
            self.given_name,
            self.middle_name,
            self.name_prefix,
            self.name_suffix,
        ):
            _reject_separator(component, "^", "alphabetic PN component")
            _reject_separator(component, "=", "alphabetic PN component")
        _reject_separator(self.ideographic, "=", "ideographic PN group")
        _reject_separator(self.phonetic, "=", "phonetic PN group")

        alphabetic = _join_name_components(
            [
                self.family_name,
                self.given_name,
                self.middle_name,
                self.name_prefix,
                self.name_suffix,
            ],
            separator="^",
        )
        groups = [alphabetic, self.ideographic, self.phonetic]
        return _join_name_components(groups, separator="=")

    def display(self) -> str:
        """Return a compact human-readable display name."""

        parts = [self.name_prefix, self.given_name, self.middle_name, self.family_name]
        display = " ".join(part for part in parts if part)
        if self.name_suffix:
            display = f"{display}, {self.name_suffix}" if display else self.name_suffix
        return display or self.ideographic.replace("^", " ") or self.phonetic.replace("^", " ")

    def __str__(self) -> str:
        return self.to_dicom_string()


def normalize_specific_character_set(
    value: SpecificCharacterSetValue,
) -> tuple[str, ...]:
    """Normalize a DICOM Specific Character Set value to canonical terms."""

    if value is None or value == "":
        return (DEFAULT_CHARACTER_SET,)
    if isinstance(value, str):
        raw_terms = value.split("\\")
    else:
        raw_terms = [str(item) for item in value]

    terms = tuple(_normalize_charset_term(term) for term in raw_terms if str(term).strip())
    return terms or (DEFAULT_CHARACTER_SET,)


def python_codecs_for_character_set(value: SpecificCharacterSetValue) -> tuple[str, ...]:
    """Return Python codec names for a DICOM Specific Character Set value."""

    terms = normalize_specific_character_set(value)
    codecs = []
    for term in terms:
        try:
            codecs.append(_DICOM_TO_PYTHON_CODECS[term])
        except KeyError as exc:
            raise CharacterSetError(
                f"SpecificCharacterSet term {term!r} is not supported by DICOMForge. "
                "Use a supported SpecificCharacterSet or transcode text before writing."
            ) from exc
    if any(term.startswith("ISO 2022 ") for term in terms):
        codecs.sort(key=lambda codec: codec == "ascii")
    return tuple(dict.fromkeys(codecs))


def preferred_specific_character_set(encoding: str) -> str:
    """Return the DICOM SpecificCharacterSet term for a common Python encoding."""

    normalized = encoding.strip().lower().replace(" ", "-")
    try:
        return _PYTHON_TO_DICOM_TERMS[normalized]
    except KeyError as exc:
        raise CharacterSetError(f"No DICOM SpecificCharacterSet mapping for {encoding!r}.") from exc


def dataset_character_set(dataset: DicomDataset) -> tuple[str, ...]:
    """Return the normalized Specific Character Set declared by *dataset*."""

    return normalize_specific_character_set(dataset.get(Tag.SpecificCharacterSet))


def decode_text(data: Union[str, bytes, bytearray], specific_character_set: Any = None) -> str:
    """Decode DICOM text bytes with the declared Specific Character Set."""

    if isinstance(data, str):
        return data
    payload = bytes(data)
    errors = []
    for codec in python_codecs_for_character_set(specific_character_set):
        try:
            return payload.decode(codec)
        except UnicodeDecodeError as exc:
            errors.append(f"{codec}: {exc}")
    raise CharacterSetError(
        "Could not decode DICOM text with declared SpecificCharacterSet "
        f"{normalize_specific_character_set(specific_character_set)!r}: {'; '.join(errors)}"
    )


def encode_text(text: Any, specific_character_set: Any = None) -> bytes:
    """Encode DICOM text using the declared Specific Character Set."""

    value = str(text)
    errors = []
    for codec in python_codecs_for_character_set(specific_character_set):
        try:
            return value.encode(codec)
        except UnicodeEncodeError as exc:
            errors.append(f"{codec}: {exc}")
    raise CharacterSetError(
        "Could not encode DICOM text with declared SpecificCharacterSet "
        f"{normalize_specific_character_set(specific_character_set)!r}: {'; '.join(errors)}"
    )


def can_encode_text(text: Any, specific_character_set: Any = None) -> bool:
    """Return whether *text* can be represented by *specific_character_set*."""

    try:
        encode_text(text, specific_character_set)
    except CharacterSetError:
        return False
    return True


def ensure_text_encodable(text: Any, specific_character_set: Any = None) -> None:
    """Raise :class:`CharacterSetError` if *text* cannot be encoded safely."""

    encode_text(text, specific_character_set)


def coerce_person_name(value: Any) -> PersonName:
    """Coerce a PN value to :class:`PersonName`."""

    if isinstance(value, PersonName):
        return value
    return PersonName.parse(value)


def _normalize_charset_term(term: str) -> str:
    compact = " ".join(term.strip().replace("_", " ").split()).upper()
    if compact == "ISO IR 6":
        return DEFAULT_CHARACTER_SET
    if compact.startswith("ISO IR "):
        return compact.replace("ISO IR ", "ISO_IR ", 1)
    if compact.startswith("ISO 2022 IR "):
        return compact
    if compact in {"GB18030", "GBK"}:
        return compact
    if compact in {"UTF-8", "UTF8"}:
        return "ISO_IR 192"
    return compact


def _split_name_group(group: str) -> tuple[str, str, str, str, str]:
    parts = group.split("^")
    if len(parts) > 5:
        raise CharacterSetError("DICOM PN component groups may contain at most five '^' parts.")
    padded = parts[:5] + [""] * max(0, 5 - len(parts))
    return tuple(padded[:5])  # type: ignore[return-value]


def _reject_separator(value: str, separator: str, context: str) -> None:
    if separator in value:
        raise CharacterSetError(f"{context} cannot contain {separator!r}.")


def _join_name_components(parts: Sequence[str], *, separator: str) -> str:
    trimmed = [str(part) for part in parts]
    while trimmed and trimmed[-1] == "":
        trimmed.pop()
    return separator.join(trimmed)
