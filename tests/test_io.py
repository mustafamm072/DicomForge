import sys
import types
import unittest

from dicomforge import DicomDataset, DicomValidationError, Tag
from dicomforge.io import read, write
from dicomforge.uids import SopClassUID, TransferSyntaxUID


class FakeTag:
    def __init__(self, group: int, element: int) -> None:
        self.group = group
        self.element = element


class FakeElement:
    def __init__(self, group: int, element: int, value: object) -> None:
        self.tag = FakeTag(group, element)
        self.value = value


class FakeDataset:
    def __init__(self) -> None:
        self.file_meta = [
            FakeElement(0x0002, 0x0010, "1.2.840.10008.1.2.1"),
        ]
        self._elements = [
            FakeElement(0x0028, 0x0010, 2),
            FakeElement(0x0028, 0x0011, 2),
        ]

    def __iter__(self):
        return iter(self._elements)


class FakeWritableDataset:
    def __init__(self) -> None:
        self.elements = []
        self.saved_path = None

    def add_new(self, tag, vr, value):
        self.elements.append((tag, vr, value))

    def save_as(self, path):
        self.saved_path = path


class IoTests(unittest.TestCase):
    def test_read_preserves_file_meta_transfer_syntax(self):
        original = sys.modules.get("pydicom")
        fake = types.SimpleNamespace(dcmread=lambda *args, **kwargs: FakeDataset())
        sys.modules["pydicom"] = fake
        try:
            dataset = read("image.dcm")
        finally:
            if original is None:
                del sys.modules["pydicom"]
            else:
                sys.modules["pydicom"] = original

        self.assertEqual(dataset.get("TransferSyntaxUID"), "1.2.840.10008.1.2.1")
        self.assertEqual(dataset.get("Rows"), 2)

    def test_write_uses_standard_vr_for_known_tags(self):
        original = sys.modules.get("pydicom")
        writable = FakeWritableDataset()
        fake = types.SimpleNamespace(Dataset=lambda: writable)
        sys.modules["pydicom"] = fake
        try:
            write(
                "image.dcm",
                DicomDataset(
                    {
                        Tag.PatientName: "Ada",
                        Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                        Tag.SOPInstanceUID: "1.2.3",
                        Tag.BitsAllocated: 16,
                        Tag.PixelData: b"\x00\x01",
                    }
                ),
            )
        finally:
            if original is None:
                del sys.modules["pydicom"]
            else:
                sys.modules["pydicom"] = original

        elements_by_tag = {tag: (vr, value) for tag, vr, value in writable.elements}
        self.assertEqual(elements_by_tag[(0x0010, 0x0010)][0], "PN")
        self.assertEqual(elements_by_tag[(0x0008, 0x0018)][0], "UI")
        self.assertEqual(elements_by_tag[(0x7FE0, 0x0010)][0], "OW")
        self.assertEqual(
            elements_by_tag[(0x0002, 0x0010)][1],
            TransferSyntaxUID.ExplicitVRLittleEndian,
        )
        self.assertEqual(writable.saved_path, "image.dcm")

    def test_write_requires_sop_identity_for_file_meta(self):
        original = sys.modules.get("pydicom")
        fake = types.SimpleNamespace(Dataset=FakeWritableDataset)
        sys.modules["pydicom"] = fake
        try:
            with self.assertRaisesRegex(DicomValidationError, "File Meta Information"):
                write("image.dcm", DicomDataset({Tag.PatientName: "Ada"}))
        finally:
            if original is None:
                del sys.modules["pydicom"]
            else:
                sys.modules["pydicom"] = original


if __name__ == "__main__":
    unittest.main()
