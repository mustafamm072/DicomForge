"""Synthetic diagnostics for the October 25, 2026 review of DicomForge 0.11.0.

Run from the repository root in a temporary environment with pydicom 3.0.2,
NumPy, and Pillow installed::

    PYTHONPATH=src python docs/review_probes_2026_10_25.py

Each JSON line records observed behavior, including expected exceptions on the
reviewed version. This is a diagnostic, not a pass/fail test suite: observations
should change when bugs are fixed. It creates synthetic files only inside a
TemporaryDirectory, removes those files afterward, and makes no network calls.
"""
import io as stdio
import json
import struct
import tempfile
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from dicomforge import AnonymizationPlan, DicomDataset, Tag, part10
from dicomforge.anonymize import UidRemapper
from dicomforge import io
from dicomforge.adapt import pixel_array, to_pil_image, to_pydicom
from dicomforge.api import batch_anonymize, validate_for_sop_class_detailed
from dicomforge.dicomweb import dataset_from_dicom_json, dataset_to_dicom_json
from dicomforge.dicomweb import parse_multipart_related_streaming
from dicomforge.transcode import compress_pixel_data, decompress_pixel_data
from dicomforge.uids import SopClassUID, TransferSyntaxUID as TS
from dicomforge.uids import is_valid_uid
from dicomforge.transport import RetryTransport
from dicomforge.dicomweb import DicomwebResponse


def image(**overrides):
    ds = DicomDataset({
        Tag.SOPClassUID: SopClassUID.CTImageStorage,
        Tag.SOPInstanceUID: "1.2.3.4.5",
        Tag.TransferSyntaxUID: TS.ExplicitVRLittleEndian,
        Tag.PatientName: "SYNTHETIC^PATIENT",
        Tag.PatientID: "SYNTHETIC-ID",
        Tag.Modality: "CT", Tag.Rows: 1, Tag.Columns: 2,
        Tag.SamplesPerPixel: 1, Tag.PhotometricInterpretation: "MONOCHROME2",
        Tag.BitsAllocated: 16, Tag.BitsStored: 16, Tag.HighBit: 15,
        Tag.PixelRepresentation: 0, Tag.PixelData: struct.pack("<HH", 258, 1024),
    })
    for key, value in overrides.items():
        ds[key] = value
    return ds


def run(name, probe):
    try:
        print(json.dumps({"probe": name, "result": probe()}, default=str))
    except Exception as exc:
        print(json.dumps({"probe": name, "exception": type(exc).__name__,
                          "message": str(exc).splitlines()[0]}))


with tempfile.TemporaryDirectory(prefix="dicomforge-review-") as temp:
    root = Path(temp)

    def nested_phi():
        raw = pydicom.dcmread(stdio.BytesIO(part10.dumps(image())))
        child = Dataset()
        child.PatientName = "SYNTHETIC^NESTED"
        child.add_new((0x0011, 0x1010), "LO", "SYNTHETIC PRIVATE")
        raw.ReferencedStudySequence = Sequence([child])
        path = root / "nested.dcm"
        pydicom.dcmwrite(path, raw, enforce_file_format=True)
        ds = io.read(path)
        AnonymizationPlan.starter_profile().apply(ds)
        child = ds[Tag.ReferencedStudySequence][0]
        return {"nested_type": type(child).__name__, "nested_name": str(child.PatientName),
                "nested_private_survived": (0x0011, 0x1010) in child,
                "identity_removed_marker": ds[Tag.PatientIdentityRemoved]}
    run("nested-phi-default-backend", nested_phi)

    def audit_phi():
        report = AnonymizationPlan.starter_profile().apply_with_report(image())
        return next(event.to_dict() for event in report.events if event.tag == Tag.PatientName)
    run("audit-original-values", audit_phi)

    def vr_loss():
        raw = pydicom.dcmread(stdio.BytesIO(part10.dumps(image())))
        raw.ConvolutionKernel = "BONE"
        buffer = stdio.BytesIO()
        pydicom.dcmwrite(buffer, raw, enforce_file_format=True)
        restored = part10.loads(buffer.getvalue())
        output_bytes = part10.dumps(restored)
        marker = struct.pack("<HH", 0x0018, 0x1210)
        offset = output_bytes.index(marker)
        return {"before_vr": raw[0x00181210].VR,
                "emitted_vr": output_bytes[offset + 4:offset + 6].decode(),
                "reader_value_type": type(restored[(0x0018, 0x1210)]).__name__}
    run("explicit-vr-loss", vr_loss)

    def endian_change():
        ds = part10.loads(part10.dumps(image(), transfer_syntax=TS.ExplicitVRBigEndian))
        return {"source_values": [258, 1024], "after_write_values": pixel_array(ds).tolist()}
    run("native-endian-change", endian_change)

    def truncated():
        blob = part10.dumps(image())
        ds = part10.loads(blob[:-2])
        return {"original_pixel_bytes": 4, "accepted_pixel_bytes": len(ds[Tag.PixelData])}
    run("truncated-pixel-value", truncated)

    def signed_stored_bits():
        ds = image(BitsStored=12, HighBit=11, PixelRepresentation=1,
                   PixelData=struct.pack("<HH", 0x0FFF, 0x0800))
        raw = pydicom.dcmread(stdio.BytesIO(part10.dumps(ds)))
        return {"forge": pixel_array(ds).tolist(), "pydicom": raw.pixel_array.tolist()}
    run("signed-12-bit-values", signed_stored_bits)

    def preview_rescale():
        ds = image(PixelData=struct.pack("<HH", 0, 1024), RescaleSlope=1,
                   RescaleIntercept=-1024, WindowCenter=0, WindowWidth=400)
        return {"preview_pixels": np.asarray(to_pil_image(ds)).tolist(),
                "modality_values": pixel_array(ds, apply_rescale=True).tolist()}
    run("preview-missing-modality-rescale", preview_rescale)

    def rle_write():
        ds = compress_pixel_data(image())
        io.write(root / "rle.dcm", ds)
        raw = pydicom.dcmread(root / "rle.dcm", force=True)
        return raw.pixel_array.tolist()
    run("native-rle-default-write", rle_write)

    def rle_read():
        ds = compress_pixel_data(image())
        part10.write_file(root / "rle-native.dcm", ds)
        restored = io.read(root / "rle-native.dcm")
        decompress_pixel_data(restored)
        return {"decoded_bytes": restored[Tag.PixelData].hex()}
    run("default-read-native-rle-decompress", rle_read)

    def pydicom_sequence():
        return str(to_pydicom(DicomDataset({Tag.ReferencedStudySequence: [image()]})))
    run("nested-to-pydicom", pydicom_sequence)

    def json_loss():
        source = {"7FE00010": {"vr": "OW", "BulkDataURI": "https://example.invalid/bulk"},
                  "00100010": {"vr": "PN", "Value": [{"Alphabetic": "Synthetic",
                                                       "Ideographic": "SYNTHETIC"}]}}
        return dataset_to_dicom_json(dataset_from_dicom_json(source))
    run("dicom-json-roundtrip", json_loss)

    def multipart_truncation():
        parts = list(parse_multipart_related_streaming(
            "multipart/related; boundary=abc", [b"--abc\r\nContent-Type: application/dicom\r\n\r\nTRUNCATED"]))
        return {"accepted_parts": len(parts), "payload": parts[0].body.decode()}
    run("truncated-multipart", multipart_truncation)

    def empty_type1():
        ds = image(PixelData=b"")
        return {"pixel_data_issues": [str(i) for i in validate_for_sop_class_detailed(ds)
                                     if i.tag == Tag.PixelData]}
    run("empty-type1-pixeldata", empty_type1)

    def basename_collision():
        paths = []
        for folder in ["a", "b"]:
            (root / folder).mkdir()
            path = root / folder / "image.dcm"
            part10.write_file(path, image())
            paths.append(path)
        (root / "output").mkdir()
        results = batch_anonymize(paths, root / "output")
        return {"reported_successes": sum(not isinstance(v, Exception) for v in results.values()),
                "output_files": len(list((root / "output").glob("*.dcm")))}
    run("batch-basename-collision", basename_collision)

    def unknown_sequence():
        raw = pydicom.dcmread(stdio.BytesIO(part10.dumps(image())))
        child = Dataset()
        child.PatientID = "SYNTHETIC"
        raw.ContentSequence = Sequence([child])
        buffer = stdio.BytesIO()
        pydicom.dcmwrite(buffer, raw, enforce_file_format=True)
        return len(part10.dumps(part10.loads(buffer.getvalue())))
    run("unregistered-standard-sequence-write", unknown_sequence)

    def uid_collisions():
        mapper = UidRemapper(root="1." + "2" * 58)
        mapped = [mapper.remap(f"1.2.3.{n}") for n in range(1000)]
        return {"inputs": len(mapped), "unique_outputs": len(set(mapped))}
    run("long-uid-root-collisions", uid_collisions)
    run("unicode-uid-grammar", lambda: {"accepted": is_valid_uid("1.2.\u0663")})

    def rle_32():
        ds = compress_pixel_data(image(BitsAllocated=32, BitsStored=32, HighBit=31,
                                       PixelData=struct.pack("<II", 1, 2)))
        return {"bits_allocated": ds[Tag.BitsAllocated], "transfer_syntax": ds[Tag.TransferSyntaxUID]}
    run("rle-32bit-standard-image", rle_32)

    def retry_consumed_body():
        class Transport:
            def __init__(self):
                self.bodies = []
            def request(self, method, url, headers, body):
                self.bodies.append(b"".join(body).decode())
                return DicomwebResponse(503 if len(self.bodies) == 1 else 200, {}, b"")
        transport = Transport()
        RetryTransport(transport, backoff_base=0).request(
            "POST", "https://example.invalid/studies", {}, iter([b"SYNTHETIC_UPLOAD"]))
        return transport.bodies
    run("retry-consumed-upload", retry_consumed_body)
