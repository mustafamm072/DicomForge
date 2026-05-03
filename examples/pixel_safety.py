from dicomforge import DicomDataset, Tag
from dicomforge.pixels import check_pixel_capability
from dicomforge.uids import TransferSyntaxUID


dataset = DicomDataset(
    {
        Tag.TransferSyntaxUID: TransferSyntaxUID.ExplicitVRLittleEndian,
        Tag.Rows: 2,
        Tag.Columns: 2,
        Tag.SamplesPerPixel: 1,
        Tag.PhotometricInterpretation: "MONOCHROME2",
        Tag.BitsAllocated: 16,
        Tag.BitsStored: 12,
        Tag.HighBit: 11,
        Tag.PixelRepresentation: 0,
        Tag.PixelData: b"\x00\x00\x01\x00\x02\x00\x03\x00",
    }
)

capability = check_pixel_capability(dataset)
print(capability)
