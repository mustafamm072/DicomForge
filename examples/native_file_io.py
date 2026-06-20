"""Read and write DICOM files with no third-party dependencies.

DICOMForge ships a native DICOM Part 10 codec, so reading and writing ``.dcm``
files works out of the box — pydicom is only needed for compressed pixel data.

Run with:  PYTHONPATH=src python3 examples/native_file_io.py
"""

from dicomforge import DicomDataset, SopClassUID, Tag, dcmread, dcmwrite, part10
from dicomforge.uids import TransferSyntaxUID


def build_dataset() -> DicomDataset:
    return DicomDataset(
        {
            Tag.SpecificCharacterSet: "ISO_IR 192",  # UTF-8
            Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
            Tag.SOPInstanceUID: "1.2.826.0.1.3680043.8.498.1",
            Tag.PatientName: "Müller^Anna",
            Tag.PatientID: "MRN-0007",
            Tag.Modality: "OT",
            Tag.Rows: 2,
            Tag.Columns: 2,
            Tag.BitsAllocated: 8,
            Tag.BitsStored: 8,
            Tag.HighBit: 7,
            Tag.PixelRepresentation: 0,
            Tag.SamplesPerPixel: 1,
            Tag.PhotometricInterpretation: "MONOCHROME2",
            Tag.PixelData: bytes([0, 64, 128, 255]),
        }
    )


def main() -> None:
    dataset = build_dataset()

    # 1. Write a conformant DICOM Part 10 file with the native backend.
    #    backend="auto" (the default) would use pydicom when it is installed;
    #    here we pin the native codec so the example is dependency-free.
    dcmwrite("native_example.dcm", dataset, backend="native")

    # 2. Read it back. stop_before_pixels makes metadata scans cheap.
    header = dcmread("native_example.dcm", backend="native", stop_before_pixels=True)
    print("Patient:", header.get(Tag.PatientName))
    print("Modality:", header.get(Tag.Modality))
    print("Transfer syntax:", header.get(Tag.TransferSyntaxUID))

    full = dcmread("native_example.dcm", backend="native")
    print("Pixel bytes:", list(full.get(Tag.PixelData)))

    # 3. Serialise to/from bytes directly, choosing the transfer syntax.
    implicit = part10.dumps(
        dataset, transfer_syntax=TransferSyntaxUID.ImplicitVRLittleEndian
    )
    restored = part10.loads(implicit)
    assert restored.get(Tag.PatientID) == "MRN-0007"
    print("Implicit VR round-trip OK, bytes:", len(implicit))


if __name__ == "__main__":
    main()
