"""A small typed dataset wrapper."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union

from dicomforge.tags import Tag, TagInput


@dataclass(frozen=True)
class DataElement:
    """An element's declared VR and value; repr deliberately excludes values."""

    tag: Tag
    vr: str
    value: Any = field(repr=False)


@dataclass(frozen=True)
class BulkDataReference:
    """An unresolved DICOM JSON bulk reference. Never fetched implicitly."""

    uri: str = field(repr=False)


class DicomDataset(MutableMapping[Tag, Any]):
    """Dictionary-like DICOM dataset with typed tag normalization."""

    def __init__(self, values: Optional[Mapping[Any, Any]] = None) -> None:
        self._values: Dict[Tag, Any] = {}
        self._vrs: Dict[Tag, str] = {}
        self._lexical: Dict[Tag, Tuple[bytes, Any]] = {}
        self.source_transfer_syntax: Optional[str] = None
        self.source_path: Optional[str] = None
        self.is_partial = False
        if values:
            for tag, value in values.items():
                self.set(tag, value)

    def set(self, tag: TagInput, value: Any, *, vr: Optional[str] = None) -> None:
        parsed = Tag.parse(tag)
        if vr is not None:
            from dicomforge.dictionary import ALL_VRS

            if vr not in ALL_VRS:
                raise ValueError("Unknown DICOM Value Representation")
            self._vrs[parsed] = vr
        self._lexical.pop(parsed, None)
        self._values[parsed] = value

    def vr(self, tag: TagInput) -> str:
        """Return the preserved VR, or resolve it from the standard dictionary."""
        from dicomforge.dictionary import vr_for_tag

        parsed = Tag.parse(tag)
        return self._vrs.get(parsed) or vr_for_tag(
            parsed, bits_allocated=self.get(Tag.BitsAllocated),
            pixel_representation=self.get(Tag.PixelRepresentation),
        )

    def elements(self) -> Iterator[DataElement]:
        for tag, value in self.items():
            yield DataElement(tag, self.vr(tag), value)

    def iter_paths(self) -> Iterator[Tuple[Tuple[Union[Tag, int], ...], DataElement]]:
        """Yield unambiguous paths including sequence item indices."""
        for element in self.elements():
            yield (element.tag,), element
            values = element.value
            if isinstance(values, DicomDataset):
                values = [values]
            if isinstance(values, (list, tuple)):
                for index, item in enumerate(values):
                    if isinstance(item, DicomDataset):
                        for path, child in item.iter_paths():
                            yield (element.tag, index) + path, child

    def get(self, tag: TagInput, default: Any = None) -> Any:
        return self._values.get(Tag.parse(tag), default)

    def require(self, tag: TagInput) -> Any:
        parsed = Tag.parse(tag)
        if parsed not in self._values:
            raise KeyError(f"Required DICOM tag {parsed} is missing")
        return self._values[parsed]

    def iter_nested(self) -> Iterable[Tuple[Tuple[Tag, ...], Tag, Any]]:
        """Yield all elements, including nested datasets in sequence-like values."""

        yield from self._iter_nested(())

    def _iter_nested(self, path: Tuple[Tag, ...]) -> Iterable[Tuple[Tuple[Tag, ...], Tag, Any]]:
        for tag, value in self._values.items():
            yield path, tag, value
            for child in _iter_child_datasets(value):
                yield from child._iter_nested(path + (tag,))

    def remove_private_tags(self, *, recursive: bool = True) -> int:
        private_tags = [tag for tag in self._values if tag.is_private]
        for tag in private_tags:
            del self[tag]
        removed = len(private_tags)
        if recursive:
            for value in self._values.values():
                for child in _iter_child_datasets(value):
                    removed += child.remove_private_tags(recursive=True)
        return removed

    def __getitem__(self, key: TagInput) -> Any:
        return self._values[Tag.parse(key)]

    def __setitem__(self, key: TagInput, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: TagInput) -> None:
        tag = Tag.parse(key)
        del self._values[tag]
        self._vrs.pop(tag, None)
        self._lexical.pop(tag, None)

    def __iter__(self) -> Iterator[Tag]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def copy(self, *, deep: bool = False) -> "DicomDataset":
        """Return a copy of this dataset.

        By default the copy is shallow: top-level tag values are copied by
        reference, so mutating a nested sequence item will also affect the
        original.  Pass ``deep=True`` to recursively copy all nested
        :class:`DicomDataset` instances so the returned dataset is fully
        independent.
        """

        copied = DicomDataset({
            tag: _deep_copy_value(value) if deep else value for tag, value in self.items()
        })
        copied._vrs = self._vrs.copy()
        copied._lexical = {tag: (raw, _deep_copy_value(value))
                           for tag, (raw, value) in self._lexical.items()}
        copied.source_transfer_syntax = self.source_transfer_syntax
        copied.source_path = self.source_path
        copied.is_partial = self.is_partial
        return copied

    def __repr__(self) -> str:
        count = len(self._values)
        sample_tags = sorted(self._values.keys())[:3]
        sample = ", ".join(str(t) for t in sample_tags)
        if count > 3:
            sample += ", ..."
        return f"DicomDataset({{{sample}}}, count={count})"

    def to_plain_dict(self) -> Dict[str, Any]:
        """Return a serializable dictionary keyed by canonical tag strings."""

        return {str(tag): value for tag, value in sorted(self._values.items())}


def _iter_child_datasets(value: Any) -> Iterable[DicomDataset]:
    if isinstance(value, DicomDataset):
        yield value
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, DicomDataset):
                yield item


def _deep_copy_value(value: Any) -> Any:
    """Recursively copy a tag value, deep-copying any nested DicomDatasets."""
    if isinstance(value, DicomDataset):
        return value.copy(deep=True)
    if isinstance(value, list):
        return [_deep_copy_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_deep_copy_value(item) for item in value)
    if isinstance(value, bytearray):
        return value.copy()
    return value


class DatasetView(DicomDataset):
    """Read-only lazy view of a pydicom Dataset; no copied pixel buffers."""

    def __init__(self, source: Any) -> None:
        super().__init__()
        self._source = source

    def get(self, tag: TagInput, default: Any = None) -> Any:
        parsed = Tag.parse(tag)
        source = getattr(self._source, "file_meta", None) if parsed.group == 2 else self._source
        if source is None:
            return default
        element = source.get((parsed.group, parsed.element))
        if element is None:
            return default
        if element.VR == "SQ":
            return [DatasetView(item) for item in element.value]
        return element.value

    def vr(self, tag: TagInput) -> str:
        parsed = Tag.parse(tag)
        source = getattr(self._source, "file_meta", None) if parsed.group == 2 else self._source
        if source is None:
            raise KeyError(parsed)
        return str(source[(parsed.group, parsed.element)].VR)

    def __getitem__(self, key: TagInput) -> Any:
        marker = object()
        result = self.get(key, marker)
        if result is marker:
            raise KeyError(Tag.parse(key))
        return result

    def __iter__(self) -> Iterator[Tag]:
        meta = getattr(self._source, "file_meta", ())
        for element in meta:
            yield Tag(element.tag.group, element.tag.element)
        for element in self._source:
            yield Tag(element.tag.group, element.tag.element)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def set(self, tag: TagInput, value: Any, *, vr: Optional[str] = None) -> None:
        raise TypeError("DatasetView is read-only")

    def __delitem__(self, key: TagInput) -> None:
        raise TypeError("DatasetView is read-only")

    def __repr__(self) -> str:
        return "DatasetView(read_only=True)"


def as_dataset(source: Any) -> DicomDataset:
    """Accept a DicomForge dataset or a pydicom dataset without copying it."""
    return source if isinstance(source, DicomDataset) else DatasetView(source)
