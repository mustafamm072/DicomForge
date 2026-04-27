"""Pixel metadata, safety checks, and lightweight pixel value helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Optional, Union

from dicomforge.codecs import CodecRegistry, default_registry
from dicomforge.dataset import DicomDataset
from dicomforge.errors import DicomForgeError, UnsupportedTransferSyntaxError
from dicomforge.tags import Tag
from dicomforge.transfer_syntax import TransferSyntax

Number = Union[int, float]
PixelBytes = Union[bytes, bytearray]

_TAG_NAMES = {
    Tag.TransferSyntaxUID: "TransferSyntaxUID",
    Tag.SamplesPerPixel: "SamplesPerPixel",
    Tag.PhotometricInterpretation: "PhotometricInterpretation",
    Tag.PlanarConfiguration: "PlanarConfiguration",
    Tag.NumberOfFrames: "NumberOfFrames",
    Tag.Rows: "Rows",
    Tag.Columns: "Columns",
    Tag.BitsAllocated: "BitsAllocated",
    Tag.BitsStored: "BitsStored",
    Tag.HighBit: "HighBit",
    Tag.PixelRepresentation: "PixelRepresentation",
    Tag.PixelData: "PixelData",
}


class PixelMetadataError(DicomForgeError, ValueError):
    """Raised when pixel metadata is missing or inconsistent."""


def _first_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        if not value:
            raise PixelMetadataError("Expected at least one value, got an empty sequence.")
        return value[0]
    return value


def _tag_label(tag: Tag) -> str:
    return f"{_TAG_NAMES.get(tag, 'DICOM tag')} {tag}"


def _int_value(dataset: DicomDataset, tag: Tag, *, default: Optional[int] = None) -> int:
    value = dataset.get(tag, default)
    if value is None:
        raise PixelMetadataError(f"Required pixel metadata tag {_tag_label(tag)} is missing.")
    try:
        return int(_first_value(value))
    except (TypeError, ValueError) as exc:
        message = f"Pixel metadata tag {tag} must be an integer, got {value!r}."
        raise PixelMetadataError(message) from exc


def _float_value(dataset: DicomDataset, tag: Tag, *, default: float) -> float:
    value = dataset.get(tag, default)
    try:
        return float(_first_value(value))
    except (TypeError, ValueError) as exc:
        message = f"Pixel metadata tag {tag} must be numeric, got {value!r}."
        raise PixelMetadataError(message) from exc


def _str_value(dataset: DicomDataset, tag: Tag) -> str:
    value = dataset.get(tag)
    if value is None:
        raise PixelMetadataError(f"Required pixel metadata tag {_tag_label(tag)} is missing.")
    text = str(_first_value(value)).strip().upper()
    if not text:
        raise PixelMetadataError(f"Required pixel metadata tag {_tag_label(tag)} is empty.")
    return text


@dataclass(frozen=True)
class FrameMetadata:
    """Shape and encoding details needed before touching pixel bytes."""

    rows: int
    columns: int
    samples_per_pixel: int
    bits_allocated: int
    bits_stored: int
    high_bit: int
    pixel_representation: int
    photometric_interpretation: str
    number_of_frames: int = 1
    planar_configuration: Optional[int] = None

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_dataset(cls, dataset: DicomDataset) -> "FrameMetadata":
        samples_per_pixel = _int_value(dataset, Tag.SamplesPerPixel)
        planar_configuration = None
        if samples_per_pixel > 1:
            planar_configuration = _int_value(dataset, Tag.PlanarConfiguration)

        metadata = cls(
            rows=_int_value(dataset, Tag.Rows),
            columns=_int_value(dataset, Tag.Columns),
            samples_per_pixel=samples_per_pixel,
            bits_allocated=_int_value(dataset, Tag.BitsAllocated),
            bits_stored=_int_value(dataset, Tag.BitsStored),
            high_bit=_int_value(dataset, Tag.HighBit),
            pixel_representation=_int_value(dataset, Tag.PixelRepresentation),
            photometric_interpretation=_str_value(dataset, Tag.PhotometricInterpretation),
            number_of_frames=_int_value(dataset, Tag.NumberOfFrames, default=1),
            planar_configuration=planar_configuration,
        )
        return metadata

    @property
    def frame_pixels(self) -> int:
        return self.rows * self.columns

    @property
    def frame_values(self) -> int:
        return self.frame_pixels * self.samples_per_pixel

    @property
    def bytes_per_sample(self) -> int:
        return self.bits_allocated // 8

    @property
    def expected_frame_bytes(self) -> int:
        return self.frame_values * self.bytes_per_sample

    @property
    def expected_pixel_bytes(self) -> int:
        return self.expected_frame_bytes * self.number_of_frames

    @property
    def is_signed(self) -> bool:
        return self.pixel_representation == 1

    def validate(self) -> None:
        positive_fields = {
            "Rows": self.rows,
            "Columns": self.columns,
            "SamplesPerPixel": self.samples_per_pixel,
            "BitsAllocated": self.bits_allocated,
            "BitsStored": self.bits_stored,
            "NumberOfFrames": self.number_of_frames,
        }
        for name, value in positive_fields.items():
            if value <= 0:
                raise PixelMetadataError(f"{name} must be positive, got {value}.")
        if self.bits_allocated % 8 != 0:
            raise PixelMetadataError(
                "BitsAllocated must be byte-aligned for safe core handling, "
                f"got {self.bits_allocated}."
            )
        if self.bits_stored > self.bits_allocated:
            raise PixelMetadataError(
                f"BitsStored ({self.bits_stored}) cannot exceed "
                f"BitsAllocated ({self.bits_allocated})."
            )
        if self.high_bit != self.bits_stored - 1:
            raise PixelMetadataError(
                f"HighBit ({self.high_bit}) should equal BitsStored - 1 ({self.bits_stored - 1})."
            )
        if self.pixel_representation not in {0, 1}:
            raise PixelMetadataError(
                "PixelRepresentation must be 0 (unsigned) or 1 (signed), "
                f"got {self.pixel_representation}."
            )
        expected_samples = expected_samples_per_pixel(self.photometric_interpretation)
        if self.samples_per_pixel != expected_samples:
            raise PixelMetadataError(
                f"{self.photometric_interpretation} usually requires "
                f"SamplesPerPixel {expected_samples}, got {self.samples_per_pixel}."
            )
        if self.samples_per_pixel > 1 and self.planar_configuration not in {0, 1}:
            raise PixelMetadataError(
                "PlanarConfiguration must be 0 or 1 when SamplesPerPixel is greater than 1."
            )


@dataclass(frozen=True)
class PixelCapability:
    """Result of checking whether the core can safely access pixel bytes."""

    transfer_syntax: TransferSyntax
    frame_metadata: FrameMetadata
    can_decode: bool
    codec_name: Optional[str]
    reason: str = ""


@dataclass(frozen=True)
class VoiLut:
    """A lightweight VOI LUT table with DICOM descriptor semantics."""

    first_mapped_value: int
    bits_per_entry: int
    values: tuple[int, ...]

    @classmethod
    def from_descriptor(cls, descriptor: Sequence[int], values: Sequence[int]) -> "VoiLut":
        if len(descriptor) != 3:
            raise PixelMetadataError("VOI LUT descriptor must contain exactly three values.")
        entry_count = int(descriptor[0]) or 65536
        if entry_count != len(values):
            raise PixelMetadataError(
                f"VOI LUT descriptor declares {entry_count} entries, got {len(values)}."
            )
        bits_per_entry = int(descriptor[2])
        if bits_per_entry <= 0:
            raise PixelMetadataError(
                f"VOI LUT bits per entry must be positive, got {bits_per_entry}."
            )
        return cls(
            first_mapped_value=int(descriptor[1]),
            bits_per_entry=bits_per_entry,
            values=tuple(int(value) for value in values),
        )

    def apply(self, value: Number) -> int:
        index = int(value) - self.first_mapped_value
        if index < 0:
            return self.values[0]
        if index >= len(self.values):
            return self.values[-1]
        return self.values[index]


def check_pixel_capability(
    dataset: DicomDataset,
    *,
    registry: Optional[CodecRegistry] = None,
    transfer_syntax: Optional[TransferSyntax] = None,
    require_pixel_data: bool = True,
) -> PixelCapability:
    """Validate pixel metadata and ensure a codec is registered for the syntax."""

    syntax_uid = dataset.get(Tag.TransferSyntaxUID)
    if transfer_syntax is None and syntax_uid is None:
        raise PixelMetadataError(
            f"Required pixel metadata tag {_tag_label(Tag.TransferSyntaxUID)} is missing."
        )
    syntax = transfer_syntax or TransferSyntax.from_uid(str(syntax_uid))
    metadata = FrameMetadata.from_dataset(dataset)
    pixel_data = dataset.get(Tag.PixelData)
    if require_pixel_data and pixel_data is None:
        raise PixelMetadataError(f"Required pixel data tag {Tag.PixelData} is missing.")

    active_registry = registry or default_registry()
    try:
        codec = active_registry.find(syntax)
    except UnsupportedTransferSyntaxError as exc:
        if syntax.is_compressed:
            raise UnsupportedTransferSyntaxError(
                f"{syntax.name} ({syntax.uid}) is compressed and no decoder is registered. "
                "Install or register a codec before reading PixelData."
            ) from exc
        raise

    if isinstance(pixel_data, (bytes, bytearray)) and not syntax.is_compressed:
        assert_pixel_data_length(pixel_data, metadata)

    return PixelCapability(
        transfer_syntax=syntax,
        frame_metadata=metadata,
        can_decode=True,
        codec_name=codec.name,
    )


def assert_pixel_data_length(pixel_data: PixelBytes, metadata: FrameMetadata) -> None:
    """Check native uncompressed PixelData length against frame metadata."""

    actual = len(pixel_data)
    expected = metadata.expected_pixel_bytes
    padded_expected = expected + 1 if expected % 2 == 1 else expected
    if actual not in {expected, padded_expected}:
        raise PixelMetadataError(
            "PixelData length mismatch: "
            f"expected {expected} bytes from frame metadata, got {actual}."
        )
    if actual == padded_expected and pixel_data[-1:] != b"\x00":
        raise PixelMetadataError("PixelData odd-length padding byte must be zero.")


def rescale_value(value: Number, *, slope: Number = 1, intercept: Number = 0) -> float:
    """Apply DICOM modality rescale to one stored pixel value."""

    return float(value) * float(slope) + float(intercept)


def rescale_values(
    values: Iterable[Number],
    *,
    slope: Number = 1,
    intercept: Number = 0,
) -> list[float]:
    """Apply DICOM modality rescale to stored pixel values."""

    return [rescale_value(value, slope=slope, intercept=intercept) for value in values]


def rescale_from_dataset(value: Number, dataset: DicomDataset) -> float:
    """Apply RescaleSlope and RescaleIntercept from a dataset."""

    return rescale_value(
        value,
        slope=_float_value(dataset, Tag.RescaleSlope, default=1.0),
        intercept=_float_value(dataset, Tag.RescaleIntercept, default=0.0),
    )


def voi_window_bounds(center: Number, width: Number) -> tuple[float, float]:
    """Return inclusive VOI window lower and upper bounds."""

    width_value = float(width)
    if width_value <= 0:
        raise PixelMetadataError(f"WindowWidth must be positive, got {width}.")
    center_value = float(center)
    lower = center_value - 0.5 - (width_value - 1) / 2
    upper = center_value - 0.5 + (width_value - 1) / 2
    return lower, upper


def apply_voi_window(
    value: Number,
    *,
    center: Number,
    width: Number,
    output_min: Number = 0,
    output_max: Number = 255,
) -> float:
    """Apply a linear VOI window to a single value."""

    lower, upper = voi_window_bounds(center, width)
    value_float = float(value)
    min_float = float(output_min)
    max_float = float(output_max)
    if value_float <= lower:
        return min_float
    if value_float > upper:
        return max_float
    return ((value_float - (float(center) - 0.5)) / (float(width) - 1) + 0.5) * (
        max_float - min_float
    ) + min_float


def apply_voi_window_from_dataset(value: Number, dataset: DicomDataset) -> float:
    """Apply the first WindowCenter and WindowWidth values from a dataset."""

    center = _float_value(dataset, Tag.WindowCenter, default=0.0)
    width = _float_value(dataset, Tag.WindowWidth, default=1.0)
    return apply_voi_window(value, center=center, width=width)


def normalize_photometric_interpretation(value: str) -> str:
    """Normalize a photometric interpretation keyword."""

    return value.strip().upper()


def is_monochrome(value: str) -> bool:
    """Return whether the photometric interpretation is MONOCHROME1 or MONOCHROME2."""

    return normalize_photometric_interpretation(value) in {"MONOCHROME1", "MONOCHROME2"}


def needs_inversion(value: str) -> bool:
    """Return whether display values should be inverted for MONOCHROME1."""

    return normalize_photometric_interpretation(value) == "MONOCHROME1"


def expected_samples_per_pixel(value: str) -> int:
    """Return the usual SamplesPerPixel for common photometric interpretations."""

    normalized = normalize_photometric_interpretation(value)
    if normalized in {"MONOCHROME1", "MONOCHROME2", "PALETTE COLOR"}:
        return 1
    if normalized in {"RGB", "YBR_FULL", "YBR_FULL_422", "YBR_PARTIAL_422", "YBR_RCT", "YBR_ICT"}:
        return 3
    raise PixelMetadataError(f"Unsupported photometric interpretation {value!r}.")
