import sys
import types
import unittest

from dicomforge.io import read


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


if __name__ == "__main__":
    unittest.main()
