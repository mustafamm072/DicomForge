import json
import unittest

from dicomforge import DicomDataset, Tag
from dicomforge.dicomweb import (
    DicomwebClient,
    DicomwebError,
    DicomwebResponse,
    QidoQuery,
    build_multipart_related,
    dataset_from_dicom_json,
    dataset_to_dicom_json,
    datasets_from_dicom_json,
    parse_multipart_related,
)
from dicomforge.errors import DicomValidationError


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def request(self, method, url, headers, body=None):
        self.requests.append((method, url, headers, body))
        return self.response


class DicomwebQueryTests(unittest.TestCase):
    def test_qido_query_encodes_common_matching_parameters(self):
        query = (
            QidoQuery()
            .patient_id("123")
            .modality("CT")
            .study_date("20260101-20260131")
            .include_field(Tag.StudyInstanceUID)
            .include_field("all")
            .limit(25)
            .offset(5)
        )

        self.assertEqual(
            query.to_query_string(),
            (
                "PatientID=123&Modality=CT&StudyDate=20260101-20260131"
                "&includefield=StudyInstanceUID&includefield=all&limit=25&offset=5"
            ),
        )

    def test_qido_query_rejects_negative_paging_values(self):
        with self.assertRaises(DicomValidationError):
            QidoQuery().limit(-1)
        with self.assertRaises(DicomValidationError):
            QidoQuery().offset(-1)


class DicomJsonTests(unittest.TestCase):
    def test_dataset_from_dicom_json_handles_person_names_sequences_and_binary(self):
        payload = {
            "00100010": {"vr": "PN", "Value": [{"Alphabetic": "Doe^Jane"}]},
            "00081115": {
                "vr": "SQ",
                "Value": [{"00080018": {"vr": "UI", "Value": ["1.2.3"]}}],
            },
            "7FE00010": {"vr": "OB", "InlineBinary": "AAE="},
        }

        dataset = dataset_from_dicom_json(payload)

        self.assertEqual(dataset.get(Tag.PatientName), "Doe^Jane")
        self.assertEqual(dataset.get(Tag(0x0008, 0x1115))[0].get(Tag.SOPInstanceUID), "1.2.3")
        self.assertEqual(dataset.get(Tag.PixelData), b"\x00\x01")

    def test_dataset_to_dicom_json_uses_dicom_json_model_shape(self):
        dataset = DicomDataset(
            {
                Tag.PatientName: "Doe^Jane",
                Tag.PixelData: b"\x00\x01",
                Tag(0x0008, 0x1115): [DicomDataset({Tag.SOPInstanceUID: "1.2.3"})],
            }
        )

        encoded = dataset_to_dicom_json(dataset)

        self.assertEqual(encoded["00100010"]["vr"], "PN")
        self.assertEqual(encoded["00100010"]["Value"], [{"Alphabetic": "Doe^Jane"}])
        self.assertEqual(encoded["7FE00010"]["InlineBinary"], "AAE=")
        self.assertEqual(encoded["00081115"]["vr"], "SQ")

    def test_datasets_from_dicom_json_accepts_single_object_or_array(self):
        body = json.dumps({"00100020": {"vr": "LO", "Value": ["123"]}})

        datasets = datasets_from_dicom_json(body)

        self.assertEqual(len(datasets), 1)
        self.assertEqual(datasets[0].get(Tag.PatientID), "123")


class DicomwebClientTests(unittest.TestCase):
    def test_search_studies_uses_qido_endpoint_and_accept_header(self):
        response = DicomwebResponse(
            status_code=200,
            headers={"content-type": "application/dicom+json"},
            body=b'[{"00100020":{"vr":"LO","Value":["123"]}}]',
        )
        transport = FakeTransport(response)
        client = DicomwebClient("https://dicom.example/dicomweb/", transport)

        results = client.search_studies(QidoQuery().patient_id("123"))

        self.assertEqual(results[0].get(Tag.PatientID), "123")
        method, url, headers, body = transport.requests[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://dicom.example/dicomweb/studies?PatientID=123")
        self.assertEqual(headers["Accept"], "application/dicom+json")
        self.assertIsNone(body)

    def test_retrieve_instance_builds_wado_path(self):
        transport = FakeTransport(
            DicomwebResponse(200, {"content-type": "application/dicom"}, b"DICM")
        )
        client = DicomwebClient("https://dicom.example", transport)

        body = client.retrieve_instance("1.2.3", "4.5.6", "7.8.9")

        self.assertEqual(body, b"DICM")
        self.assertEqual(
            transport.requests[0][1],
            "https://dicom.example/studies/1.2.3/series/4.5.6/instances/7.8.9",
        )

    def test_retrieve_study_parts_parses_wado_multipart_response(self):
        body, content_type = build_multipart_related(
            [b"DICM"],
            content_type="application/dicom",
            boundary="study-boundary",
        )
        transport = FakeTransport(DicomwebResponse(200, {"content-type": content_type}, body))
        client = DicomwebClient("https://dicom.example", transport)

        parts = client.retrieve_study_parts("1.2.3")

        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].body, b"DICM")

    def test_store_instances_posts_stow_multipart_body(self):
        transport = FakeTransport(
            DicomwebResponse(200, {"content-type": "application/dicom+json"}, b"{}")
        )
        client = DicomwebClient("https://dicom.example", transport)

        client.store_instances([b"DICM"])

        method, url, headers, body = transport.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://dicom.example/studies")
        self.assertIn('type="application/dicom"', headers["Content-Type"])
        self.assertIn(b"DICM", body)

    def test_client_raises_for_http_errors(self):
        transport = FakeTransport(DicomwebResponse(500, {}, b"error"))
        client = DicomwebClient("https://dicom.example", transport)

        with self.assertRaises(DicomwebError):
            client.search_studies()


class PathUidTests(unittest.TestCase):
    """Tests for the _path_uid UID validation used in DICOMweb URL building."""

    def _path_uid(self, uid: str) -> str:
        from dicomforge.dicomweb import _path_uid
        return _path_uid(uid)

    def test_standard_uid_is_returned_unchanged(self):
        self.assertEqual(self._path_uid("1.2.840.10008.5.1.4.1.1.2"), "1.2.840.10008.5.1.4.1.1.2")

    def test_empty_string_raises(self):
        with self.assertRaisesRegex(DicomValidationError, "empty"):
            self._path_uid("")

    def test_whitespace_only_raises(self):
        with self.assertRaisesRegex(DicomValidationError, "empty"):
            self._path_uid("   ")

    def test_leading_whitespace_raises(self):
        with self.assertRaisesRegex(DicomValidationError, "whitespace"):
            self._path_uid(" 1.2.3")

    def test_trailing_whitespace_raises(self):
        with self.assertRaisesRegex(DicomValidationError, "whitespace"):
            self._path_uid("1.2.3 ")

    def test_internal_whitespace_raises(self):
        with self.assertRaisesRegex(DicomValidationError, "alphabet"):
            self._path_uid("1.2. 3")

    def test_slash_in_uid_raises(self):
        # A slash would split the path segment and reach the wrong endpoint.
        with self.assertRaisesRegex(DicomValidationError, "alphabet"):
            self._path_uid("1.2.3/4")

    def test_invalid_characters_raise(self):
        for bad in ["1.2.3#4", "1.2.3?q=1", "1.2.3\x004"]:
            with self.subTest(uid=bad):
                with self.assertRaises(DicomValidationError):
                    self._path_uid(bad)

    def test_client_url_contains_unencoded_dots(self):
        """Verify the full client path uses readable dot-separated UIDs."""
        transport = FakeTransport(
            DicomwebResponse(
                status_code=200,
                headers={"content-type": "application/dicom+json"},
                body=b"[]",
            )
        )
        client = DicomwebClient("https://dicom.example", transport)
        client.search_series("1.2.840.10008.5.1")
        _, url, _, _ = transport.requests[0]
        self.assertIn("1.2.840.10008.5.1", url)
        self.assertNotIn("%2E", url)


class MultipartTests(unittest.TestCase):
    def test_build_and_parse_multipart_related(self):
        body, content_type = build_multipart_related(
            [b"first\r\n", b"second"],
            content_type="application/dicom",
            boundary="boundary",
        )

        parts = list(parse_multipart_related(content_type, body))

        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].content_type, "application/dicom")
        self.assertEqual(parts[0].body, b"first\r\n")
        self.assertEqual(parts[1].body, b"second")

    def test_build_multipart_rejects_empty_upload(self):
        with self.assertRaises(DicomValidationError):
            build_multipart_related([], content_type="application/dicom")

    def test_build_multipart_rejects_invalid_boundary(self):
        with self.assertRaises(DicomValidationError):
            build_multipart_related(
                [b"DICM"],
                content_type="application/dicom",
                boundary="bad\r\nboundary",
            )

    def test_parse_multipart_requires_boundary(self):
        with self.assertRaises(DicomwebError):
            list(parse_multipart_related("multipart/related", b""))


if __name__ == "__main__":
    unittest.main()
