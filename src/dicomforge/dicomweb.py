"""Dependency-free DICOMweb client primitives.

The module covers the API mechanics for QIDO-RS, WADO-RS, and STOW-RS without
owning authentication, retries, or a heavyweight HTTP stack. Applications can
inject any transport with a small request method, while tests can use an
in-memory transport.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Union,
)
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from dicomforge.dataset import DicomDataset
from dicomforge.errors import DicomForgeError, DicomValidationError
from dicomforge.tags import Tag, TagInput

Headers = Mapping[str, str]
MutableHeaders = Dict[str, str]
Body = Union[bytes, bytearray, str, None]

_DEFAULT_QIDO_ACCEPT = "application/dicom+json"
_DEFAULT_WADO_ACCEPT = 'multipart/related; type="application/dicom"'
_BOUNDARY_PATTERN = re.compile(r"^[A-Za-z0-9'()+_,./:=?-]{1,70}$")
_DICOM_JSON_VR = {
    Tag.PatientName: "PN",
    Tag.PatientID: "LO",
    Tag.PatientBirthDate: "DA",
    Tag.PatientSex: "CS",
    Tag.AccessionNumber: "SH",
    Tag.StudyDate: "DA",
    Tag.SeriesDate: "DA",
    Tag.AcquisitionDate: "DA",
    Tag.ContentDate: "DA",
    Tag.StudyTime: "TM",
    Tag.SeriesTime: "TM",
    Tag.AcquisitionTime: "TM",
    Tag.ContentTime: "TM",
    Tag.InstitutionName: "LO",
    Tag.ReferringPhysicianName: "PN",
    Tag.StudyID: "SH",
    Tag.StudyInstanceUID: "UI",
    Tag.SeriesInstanceUID: "UI",
    Tag.SOPInstanceUID: "UI",
    Tag.SOPClassUID: "UI",
    Tag.Modality: "CS",
    Tag.Rows: "US",
    Tag.Columns: "US",
    Tag.BitsAllocated: "US",
    Tag.BitsStored: "US",
    Tag.HighBit: "US",
    Tag.PixelRepresentation: "US",
    Tag.PixelData: "OB",
}


class DicomwebError(DicomForgeError):
    """Raised when a DICOMweb request, response, or payload is invalid."""


@dataclass(frozen=True)
class DicomwebResponse:
    """HTTP response returned by a DICOMweb transport."""

    status_code: int
    headers: Headers
    body: bytes = b""

    def header(self, name: str, default_value: str = "") -> str:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default_value


class DicomwebTransport(Protocol):
    """Minimal transport protocol used by `DicomwebClient`."""

    def request(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Body = None,
    ) -> DicomwebResponse:
        """Send one HTTP request."""


class UrllibDicomwebTransport:
    """Standard-library HTTP transport for simple DICOMweb use."""

    def __init__(self, *, timeout: Optional[float] = None) -> None:
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Body = None,
    ) -> DicomwebResponse:
        data: Optional[bytes]
        if body is None:
            data = None
        elif isinstance(body, bytes):
            data = body
        elif isinstance(body, bytearray):
            data = bytes(body)
        else:
            data = body.encode("utf-8")
        request = Request(url, data=data, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return DicomwebResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except Exception as exc:
            status = getattr(exc, "code", None)
            headers_obj = getattr(exc, "headers", {})
            body_obj = getattr(exc, "read", lambda: b"")()
            if status is not None:
                return DicomwebResponse(
                    status_code=int(status),
                    headers=dict(headers_obj.items()),
                    body=body_obj,
                )
            raise


@dataclass(frozen=True)
class MultipartPart:
    """One multipart/related part."""

    headers: Headers
    body: bytes

    @property
    def content_type(self) -> str:
        return _header(self.headers, "content-type")


class QidoQuery:
    """Builder for QIDO-RS query parameters."""

    def __init__(self) -> None:
        self._params: List[Tuple[str, str]] = []

    def match(self, tag: TagInput, value: object) -> "QidoQuery":
        self._params.append((_query_key(tag), str(value)))
        return self

    def patient_id(self, value: object) -> "QidoQuery":
        return self.match(Tag.PatientID, value)

    def patient_name(self, value: object) -> "QidoQuery":
        return self.match(Tag.PatientName, value)

    def modality(self, value: object) -> "QidoQuery":
        return self.match(Tag.Modality, value)

    def study_date(self, value: object) -> "QidoQuery":
        return self.match(Tag.StudyDate, value)

    def include_field(self, tag: Union[TagInput, str]) -> "QidoQuery":
        if isinstance(tag, str) and tag.lower() == "all":
            value = "all"
        else:
            value = _query_key(tag)
        self._params.append(("includefield", value))
        return self

    def limit(self, value: int) -> "QidoQuery":
        if value < 0:
            raise DicomValidationError("QIDO-RS limit must be zero or greater.")
        self._set_single("limit", str(value))
        return self

    def offset(self, value: int) -> "QidoQuery":
        if value < 0:
            raise DicomValidationError("QIDO-RS offset must be zero or greater.")
        self._set_single("offset", str(value))
        return self

    def to_params(self) -> List[Tuple[str, str]]:
        return list(self._params)

    def to_query_string(self) -> str:
        return urlencode(self._params)

    def _set_single(self, key: str, value: str) -> None:
        self._params = [
            (existing_key, item) for existing_key, item in self._params if existing_key != key
        ]
        self._params.append((key, value))


class DicomwebClient:
    """Small QIDO-RS, WADO-RS, and STOW-RS client with injectable transport."""

    def __init__(
        self,
        base_url: str,
        transport: DicomwebTransport,
        *,
        headers: Optional[Headers] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.headers = dict(headers or {})

    def search_studies(self, query: Optional[QidoQuery] = None) -> List[DicomDataset]:
        return self._qido("studies", query)

    def search_series(
        self,
        study_uid: str,
        query: Optional[QidoQuery] = None,
    ) -> List[DicomDataset]:
        return self._qido(f"studies/{_path_uid(study_uid)}/series", query)

    def search_instances(
        self,
        study_uid: str,
        series_uid: str,
        query: Optional[QidoQuery] = None,
    ) -> List[DicomDataset]:
        path = f"studies/{_path_uid(study_uid)}/series/{_path_uid(series_uid)}/instances"
        return self._qido(path, query)

    def retrieve_study(self, study_uid: str, *, accept: str = _DEFAULT_WADO_ACCEPT) -> bytes:
        return self._wado(f"studies/{_path_uid(study_uid)}", accept=accept).body

    def retrieve_study_parts(
        self,
        study_uid: str,
        *,
        accept: str = _DEFAULT_WADO_ACCEPT,
    ) -> List[MultipartPart]:
        response = self._wado(f"studies/{_path_uid(study_uid)}", accept=accept)
        return list(parse_multipart_related(response.header("content-type"), response.body))

    def retrieve_series(
        self,
        study_uid: str,
        series_uid: str,
        *,
        accept: str = _DEFAULT_WADO_ACCEPT,
    ) -> bytes:
        path = f"studies/{_path_uid(study_uid)}/series/{_path_uid(series_uid)}"
        return self._wado(path, accept=accept).body

    def retrieve_series_parts(
        self,
        study_uid: str,
        series_uid: str,
        *,
        accept: str = _DEFAULT_WADO_ACCEPT,
    ) -> List[MultipartPart]:
        path = f"studies/{_path_uid(study_uid)}/series/{_path_uid(series_uid)}"
        response = self._wado(path, accept=accept)
        return list(parse_multipart_related(response.header("content-type"), response.body))

    def retrieve_instance(
        self,
        study_uid: str,
        series_uid: str,
        sop_instance_uid: str,
        *,
        accept: str = _DEFAULT_WADO_ACCEPT,
    ) -> bytes:
        path = (
            f"studies/{_path_uid(study_uid)}/series/{_path_uid(series_uid)}"
            f"/instances/{_path_uid(sop_instance_uid)}"
        )
        return self._wado(path, accept=accept).body

    def retrieve_instance_parts(
        self,
        study_uid: str,
        series_uid: str,
        sop_instance_uid: str,
        *,
        accept: str = _DEFAULT_WADO_ACCEPT,
    ) -> List[MultipartPart]:
        path = (
            f"studies/{_path_uid(study_uid)}/series/{_path_uid(series_uid)}"
            f"/instances/{_path_uid(sop_instance_uid)}"
        )
        response = self._wado(path, accept=accept)
        return list(parse_multipart_related(response.header("content-type"), response.body))

    def retrieve_study_metadata(self, study_uid: str) -> List[DicomDataset]:
        response = self._wado(
            f"studies/{_path_uid(study_uid)}/metadata",
            accept=_DEFAULT_QIDO_ACCEPT,
        )
        return datasets_from_dicom_json(response.body)

    def store_instances(
        self,
        instances: Iterable[Union[bytes, bytearray]],
        *,
        content_type: str = "application/dicom",
    ) -> DicomwebResponse:
        body, body_content_type = build_multipart_related(
            [bytes(instance) for instance in instances],
            content_type=content_type,
        )
        response = self._request(
            "POST",
            "studies",
            headers={
                "Accept": "application/dicom+json",
                "Content-Type": body_content_type,
            },
            body=body,
        )
        _raise_for_status(response)
        return response

    def _qido(self, path: str, query: Optional[QidoQuery]) -> List[DicomDataset]:
        suffix = path
        if query is not None and query.to_params():
            suffix = f"{path}?{query.to_query_string()}"
        response = self._request("GET", suffix, headers={"Accept": _DEFAULT_QIDO_ACCEPT})
        _raise_for_status(response)
        return datasets_from_dicom_json(response.body)

    def _wado(self, path: str, *, accept: str) -> DicomwebResponse:
        response = self._request("GET", path, headers={"Accept": accept})
        _raise_for_status(response)
        return response

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Headers,
        body: Body = None,
    ) -> DicomwebResponse:
        merged_headers: MutableHeaders = dict(self.headers)
        merged_headers.update(headers)
        return self.transport.request(method, f"{self.base_url}/{path}", merged_headers, body)


def dataset_from_dicom_json(item: Mapping[str, Any]) -> DicomDataset:
    """Convert one DICOM JSON Model object into `DicomDataset`."""

    dataset = DicomDataset()
    for key, element in item.items():
        if not isinstance(element, Mapping):
            raise DicomwebError(f"DICOM JSON element {key!r} must be an object.")
        tag = Tag.parse(key)
        dataset.set(tag, _element_value_from_json(element))
    return dataset


def datasets_from_dicom_json(
    payload: Union[bytes, str, Sequence[Mapping[str, Any]]],
) -> List[DicomDataset]:
    """Convert a DICOM JSON Model response into datasets."""

    if isinstance(payload, bytes):
        decoded = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        decoded = json.loads(payload)
    else:
        decoded = payload
    if isinstance(decoded, Mapping):
        decoded = [decoded]
    if not isinstance(decoded, Sequence):
        raise DicomwebError("DICOM JSON response must be an object or array of objects.")
    datasets = []
    for item in decoded:
        if not isinstance(item, Mapping):
            raise DicomwebError("DICOM JSON response items must be objects.")
        datasets.append(dataset_from_dicom_json(item))
    return datasets


def dataset_to_dicom_json(dataset: DicomDataset) -> Dict[str, Dict[str, Any]]:
    """Convert `DicomDataset` into a minimal DICOM JSON Model object."""

    encoded: Dict[str, Dict[str, Any]] = {}
    for tag, value in dataset.items():
        vr = _vr_for_tag(tag, value)
        element: Dict[str, Any] = {"vr": vr}
        if isinstance(value, (bytes, bytearray)):
            element["InlineBinary"] = base64.b64encode(bytes(value)).decode("ascii")
        elif value not in (None, ""):
            element["Value"] = _value_to_json(vr, value)
        elif value == "":
            element["Value"] = [""]
        encoded[f"{tag.group:04X}{tag.element:04X}"] = element
    return encoded


def build_multipart_related(
    parts: Iterable[bytes],
    *,
    content_type: str,
    boundary: Optional[str] = None,
) -> Tuple[bytes, str]:
    """Build a multipart/related body for STOW-RS uploads."""

    active_boundary = boundary or f"dicomforge-{uuid.uuid4().hex}"
    if not _BOUNDARY_PATTERN.match(active_boundary):
        raise DicomValidationError("Multipart boundary contains invalid characters.")
    body = bytearray()
    count = 0
    for part in parts:
        count += 1
        body.extend(f"--{active_boundary}\r\n".encode("ascii"))
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("ascii"))
        body.extend(part)
        body.extend(b"\r\n")
    if count == 0:
        raise DicomValidationError("STOW-RS upload requires at least one instance.")
    body.extend(f"--{active_boundary}--\r\n".encode("ascii"))
    return bytes(body), f'multipart/related; type="{content_type}"; boundary={active_boundary}'


def parse_multipart_related(content_type: str, body: bytes) -> Iterator[MultipartPart]:
    """Parse a multipart/related body into parts.

    The parser works on a bytes object today but exposes an iterator API so the
    public contract can grow into chunked streaming without changing callers.
    """

    _boundary_from_content_type(content_type)
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: "
        + content_type.encode("ascii")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    if not message.is_multipart():
        raise DicomwebError("Multipart body does not contain the declared boundary.")
    for part in message.iter_parts():
        payload = part.get_payload(decode=True)
        yield MultipartPart(
            headers={key.lower(): value for key, value in part.items()},
            body=payload or b"",
        )


def _query_key(tag: Union[TagInput, str]) -> str:
    if isinstance(tag, str):
        stripped = tag.strip()
        if stripped in Tag._KEYWORDS:
            return stripped
    parsed = Tag.parse(tag)
    keyword = _keyword_for_tag(parsed)
    return keyword or f"{parsed.group:04X}{parsed.element:04X}"


def _keyword_for_tag(tag: Tag) -> Optional[str]:
    for keyword, known in Tag._KEYWORDS.items():
        if known == tag:
            return keyword
    return None


def _path_uid(uid: str) -> str:
    """Validate and percent-encode a UID for use as a URL path segment.

    DICOM UIDs (PS3.5 §9.1) may only contain digits (0-9) and dots (.).
    Passing an empty, whitespace-only, or structurally invalid UID would
    produce a silently broken URL that fails at the network layer with no
    useful error message.  We raise early instead.
    """
    stripped = uid.strip()
    if not stripped:
        raise DicomValidationError(
            "UID must not be empty or whitespace."
        )
    if stripped != uid:
        raise DicomValidationError(
            f"UID must not have leading or trailing whitespace: {uid!r}"
        )
    # Internal whitespace or characters outside the DICOM UID alphabet
    # would produce a %xx-encoded path that no server will match.
    if not re.fullmatch(r"[0-9.]+", stripped):
        raise DicomValidationError(
            f"UID contains characters outside the DICOM UID alphabet "
            f"([0-9.]): {uid!r}"
        )
    return quote(stripped, safe=".")


def _raise_for_status(response: DicomwebResponse) -> None:
    if 200 <= response.status_code < 300:
        return
    raise DicomwebError(f"DICOMweb request failed with HTTP status {response.status_code}.")


def _element_value_from_json(element: Mapping[str, Any]) -> Any:
    vr = str(element.get("vr", "UN"))
    if "Value" in element:
        values = element["Value"]
        if not isinstance(values, list):
            raise DicomwebError("DICOM JSON Value must be an array.")
        converted = [_json_value_to_python(vr, value) for value in values]
        if vr == "SQ":
            return converted
        return converted[0] if len(converted) == 1 else converted
    if "InlineBinary" in element:
        return base64.b64decode(str(element["InlineBinary"]).encode("ascii"))
    if "BulkDataURI" in element:
        return str(element["BulkDataURI"])
    return ""


def _json_value_to_python(vr: str, value: Any) -> Any:
    if vr == "PN" and isinstance(value, Mapping):
        return value.get("Alphabetic", "")
    if vr == "SQ" and isinstance(value, Mapping):
        return dataset_from_dicom_json(value)
    return value


def _value_to_json(vr: str, value: Any) -> List[Any]:
    values = value if isinstance(value, list) else [value]
    if vr == "PN":
        return [{"Alphabetic": str(item)} for item in values]
    if vr == "SQ":
        return [
            dataset_to_dicom_json(item) if isinstance(item, DicomDataset) else item
            for item in values
        ]
    return list(values)


def _vr_for_tag(tag: Tag, value: Any) -> str:
    if isinstance(value, DicomDataset):
        return "SQ"
    if isinstance(value, list) and value and isinstance(value[0], DicomDataset):
        return "SQ"
    return _DICOM_JSON_VR.get(tag, "UN")


def _boundary_from_content_type(content_type: str) -> bytes:
    for item in content_type.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator and key.lower() == "boundary":
            return value.strip('"').encode("ascii")
    raise DicomwebError("Multipart Content-Type is missing a boundary parameter.")


def _header(headers: Headers, name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""
