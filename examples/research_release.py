"""Executable, dependency-free research workflow using only synthetic CT data."""

import json
import secrets
import tempfile
from pathlib import Path

from dicomforge import (
    DicomDataset, ReleasePolicy, SopClassUID, Tag, TransferSyntaxUID,
    dcmwrite, inspect_collection, release_collection,
)


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root/'source').mkdir()
        paths = []
        for index in range(2):
            dataset = DicomDataset({
                Tag.SOPClassUID: SopClassUID.CTImageStorage, Tag.SOPInstanceUID: f'2.25.{index+1}',
                Tag.StudyInstanceUID: '2.25.10', Tag.SeriesInstanceUID: '2.25.11',
                Tag.FrameOfReferenceUID: '2.25.12', Tag.PatientID: 'SYNTHETIC',
                Tag.PatientName: 'Synthetic^Subject', Tag.Modality: 'CT', Tag.Rows: 1, Tag.Columns: 2,
                Tag.SamplesPerPixel: 1, Tag.PhotometricInterpretation: 'MONOCHROME2',
                Tag.BitsAllocated: 16, Tag.BitsStored: 16, Tag.HighBit: 15, Tag.PixelRepresentation: 0,
                Tag.TransferSyntaxUID: TransferSyntaxUID.ExplicitVRLittleEndian,
                Tag.PixelData: b'\x00\x00\x01\x00', Tag.BurnedInAnnotation: 'NO',
                Tag.PixelSpacing: [1, 1], Tag.ImageOrientationPatient: [1, 0, 0, 0, 1, 0],
                Tag.ImagePositionPatient: [0, 0, index],
            })
            path = root/'source'/f'{index}.dcm'
            dcmwrite(path, dataset)
            paths.append(path)
        assert inspect_collection(paths).status == 'accepted'
        # Real deployments persist a project key securely; ephemeral is suitable here.
        policy = ReleasePolicy('synthetic-example', secrets.token_bytes(32), pixels_reviewed=True)
        release_collection(paths, root/'out', policy, dry_run=True)
        manifest = release_collection(paths, root/'out', policy)
        assert release_collection(paths, root/'out', policy, resume=True) == manifest
        print(json.dumps({'completed': manifest['completed'], 'instances': len(manifest['instances'])}))


if __name__ == '__main__':
    main()
