"""Reproducible synthetic metadata/RLE benchmark; no patient data or extras needed."""

import argparse
import json
import platform
import tempfile
import time
import tracemalloc
from pathlib import Path

from dicomforge import __version__, compress_pixel_data, dcmread, dcmwrite, decompress_pixel_data
from dicomforge import DicomDataset, SopClassUID, Tag, TransferSyntaxUID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=10)
    parser.add_argument('--rows', type=int, default=512)
    args = parser.parse_args()
    if args.iterations <= 0 or args.rows <= 0:
        parser.error('iterations and rows must be positive')
    ds = DicomDataset({Tag.SOPClassUID: SopClassUID.CTImageStorage, Tag.SOPInstanceUID: '2.25.1',
                       Tag.Modality: 'CT', Tag.TransferSyntaxUID: TransferSyntaxUID.ExplicitVRLittleEndian,
                       Tag.Rows: args.rows, Tag.Columns: args.rows, Tag.SamplesPerPixel: 1,
                       Tag.PhotometricInterpretation: 'MONOCHROME2', Tag.BitsAllocated: 16,
                       Tag.BitsStored: 12, Tag.HighBit: 11, Tag.PixelRepresentation: 0,
                       Tag.PixelData: b'\x01\x00' * args.rows ** 2})
    measurements = {}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'synthetic.dcm'
        dcmwrite(path, ds)
        def measure(name, operation):
            tracemalloc.start()
            start = time.perf_counter()
            for _ in range(args.iterations):
                operation()
            elapsed = time.perf_counter() - start
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            measurements[name] = {'seconds': elapsed, 'operations_per_second': args.iterations/elapsed,
                                  'peak_python_allocated_bytes': peak}
        measure('metadata_scan', lambda: dcmread(path, stop_before_pixels=True))
        def transcode():
            copied = ds.copy(deep=True)
            compress_pixel_data(copied)
            decompress_pixel_data(copied)
            assert copied[Tag.PixelData] == ds[Tag.PixelData]
        measure('rle_roundtrip', transcode)
    print(json.dumps({'tool_version': __version__, 'python': platform.python_version(),
                      'platform': platform.platform(), 'rows': args.rows, 'iterations': args.iterations,
                      'notes': 'Synthetic constant pixels; Python allocation peak is not process RSS; no speedup claim',
                      'measurements': measurements}, indent=2))


if __name__ == '__main__':
    main()
