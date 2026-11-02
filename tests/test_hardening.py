"""End-to-end regressions for the independent 0.11 review findings."""

import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dicomforge import AnonymizationPlan, DicomDataset, Tag, part10
from dicomforge.adapt import from_pydicom, to_pydicom
from dicomforge.anonymize import UidRemapper
from dicomforge.api import DicomFile, batch_anonymize, validate_for_sop_class_detailed
from dicomforge.dataset import BulkDataReference
from dicomforge.dicomweb import (
    DicomwebClient, DicomwebError, DicomwebResponse, dataset_from_dicom_json,
    dataset_to_dicom_json, parse_multipart_related_streaming,
)
from dicomforge.errors import DicomValidationError
from dicomforge.io import read, write
from dicomforge.multipart import iter_multipart_chunks
from dicomforge.transcode import compress_pixel_data, decompress_pixel_data
from dicomforge.transport import RetryTransport, StreamingDicomwebResponse
from dicomforge.uids import SopClassUID, TransferSyntaxUID as TS, generate_uid, is_valid_uid

HAS_PYDICOM = importlib.util.find_spec('pydicom') is not None
HAS_PIXELS = importlib.util.find_spec('numpy') is not None and importlib.util.find_spec('PIL') is not None


def image(index=0, **overrides):
    ds = DicomDataset({
        Tag.SOPClassUID: SopClassUID.CTImageStorage, Tag.SOPInstanceUID: f'1.2.3.4.{index+1}',
        Tag.TransferSyntaxUID: TS.ExplicitVRLittleEndian,
        Tag.StudyInstanceUID: '1.2.3', Tag.SeriesInstanceUID: '1.2.3.4',
        Tag.FrameOfReferenceUID: '1.2.5', Tag.PatientName: 'SYNTHETIC^PATIENT',
        Tag.PatientID: 'SYNTHETIC-ID', Tag.Modality: 'CT', Tag.Rows: 1, Tag.Columns: 2,
        Tag.SamplesPerPixel: 1, Tag.PhotometricInterpretation: 'MONOCHROME2',
        Tag.BitsAllocated: 16, Tag.BitsStored: 16, Tag.HighBit: 15,
        Tag.PixelRepresentation: 0, Tag.PixelData: struct.pack('<HH', 258, 1024),
        Tag.PixelSpacing: [1, 1], Tag.ImageOrientationPatient: [1, 0, 0, 0, 1, 0],
        Tag.ImagePositionPatient: [0, 0, index], Tag.BurnedInAnnotation: 'NO',
        Tag.RescaleSlope: 1, Tag.RescaleIntercept: 0, Tag.ImageType: ['ORIGINAL', 'PRIMARY'],
        Tag.StudyDate: '20260101', Tag.StudyTime: '', Tag.StudyID: '', Tag.AccessionNumber: '',
        Tag.SeriesNumber: 1, Tag.InstanceNumber: index+1, Tag.KVP: '', Tag.AcquisitionNumber: '',
    })
    for key, value in overrides.items():
        ds[key] = value
    return ds


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reports_and_repr_are_value_free_and_do_not_load_files(self):
        report = AnonymizationPlan.starter_profile().apply_with_report(image())
        self.assertNotIn('SYNTHETIC', json.dumps(report.to_dict()))
        self.assertNotIn('SYNTHETIC', repr(report))
        with patch('dicomforge.io.read', side_effect=AssertionError('must not read')):
            self.assertEqual(repr(DicomFile('SYNTHETIC-name.dcm')), 'DicomFile(loaded=False)')

    def test_nested_paths_include_item_index(self):
        ds = image(ReferencedStudySequence=[DicomDataset({'PatientName': 'A'}),
                                            DicomDataset({'PatientName': 'B'})])
        report = AnonymizationPlan.starter_profile().apply_with_report(ds)
        paths = [event.item_path for event in report.events if event.tag == Tag.PatientName]
        self.assertIn((Tag.ReferencedStudySequence, 0, Tag.PatientName), paths)
        self.assertIn((Tag.ReferencedStudySequence, 1, Tag.PatientName), paths)

    def test_long_uid_roots_and_non_ascii_uids_rejected(self):
        root = '1.' + '2'*58
        for generate in (generate_uid, UidRemapper):
            with self.assertRaises(ValueError):
                generate(root)
        self.assertFalse(is_valid_uid('1.2.\u0663'))
        with self.assertRaises(ValueError):
            UidRemapper('1.02.3')
        mapper = UidRemapper(key=b'a'*32, namespace='trial')
        self.assertEqual(len({mapper.remap(f'1.2.{n}') for n in range(1000)}), 1000)
        self.assertEqual(mapper.remap('1.2.3'), UidRemapper(key=b'a'*32, namespace='trial').remap('1.2.3'))

    def test_truncation_rejected_at_every_pixel_header_and_value_offset(self):
        blob = part10.dumps(image())
        start = blob.index(struct.pack('<HH', 0x7FE0, 0x0010))
        for size in range(start+1, len(blob)):
            with self.subTest(size=size), self.assertRaises(DicomValidationError):
                part10.loads(blob[:size])

    def test_deflate_limit_and_truncated_stream(self):
        blob = part10.dumps(image(), transfer_syntax=TS.DeflatedExplicitVRLittleEndian)
        with self.assertRaises(DicomValidationError):
            part10.loads(blob, max_decompressed_bytes=10)
        with self.assertRaises(DicomValidationError):
            part10.loads(blob[:-3])

    def test_native_metadata_scan_does_not_read_pixel_payload(self):
        path = self.root/'large.dcm'
        write(path, image())
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('eager read')):
            metadata = read(path, stop_before_pixels=True)
        self.assertNotIn(Tag.PixelData, metadata)
        with self.assertRaises(DicomValidationError):
            write(self.root/'partial.dcm', metadata)

    def test_unknown_explicit_vr_and_standard_sequence_are_preserved(self):
        ds = image()
        ds.set((0x0011, 0x1010), 'private text', vr='LO')
        ds.set('ContentSequence', [DicomDataset({'PatientName': 'SYNTHETIC'})], vr='SQ')
        ds.set('ConvolutionKernel', 'BONE', vr='SH')
        restored = part10.loads(part10.dumps(ds))
        again = part10.loads(part10.dumps(restored))
        self.assertEqual(again.vr((0x0011, 0x1010)), 'LO')
        self.assertEqual(again['ConvolutionKernel'], 'BONE')
        self.assertEqual(again['ContentSequence'][0][Tag.PatientName], 'SYNTHETIC')

    def test_numeric_string_lexical_form_survives_unchanged_read_write(self):
        ds = image(RescaleSlope='1.0000000000')
        blob = part10.dumps(ds)
        self.assertIn(b'1.0000000000', part10.dumps(part10.loads(blob)))

    def test_atomic_no_overwrite_and_failed_write_preserve_existing_file(self):
        path = self.root/'out.dcm'
        write(path, image())
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            write(path, image(1), overwrite=False)
        with self.assertRaises(DicomValidationError):
            write(path, DicomDataset())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.root.glob('.dicomforge-*')), [])

    def test_batch_collisions_are_reported_before_writes(self):
        inputs = []
        for folder in ('a', 'b'):
            (self.root/folder).mkdir()
            path = self.root/folder/'image.dcm'
            write(path, image(len(inputs)))
            inputs.append(path)
        (self.root/'out').mkdir()
        result = batch_anonymize(inputs, self.root/'out')
        self.assertTrue(all(isinstance(value, ValueError) for value in result.values()))
        self.assertFalse(list((self.root/'out').iterdir()))

    def test_json_preserves_vr_bulk_references_person_names_and_nulls(self):
        data = {'7FE00010': {'vr': 'OW', 'BulkDataURI': 'https://example.invalid/bulk'},
                '00100010': {'vr': 'PN', 'Value': [{'Alphabetic': 'Synthetic', 'Ideographic': '示例'}]},
                '00080050': {'vr': 'SH'}, '00100020': {'vr': 'LO', 'Value': [None, 'x']}}
        ds = dataset_from_dicom_json(data)
        self.assertIsInstance(ds[Tag.PixelData], BulkDataReference)
        self.assertEqual(dataset_to_dicom_json(ds), data)

    def test_empty_type1_values_are_errors(self):
        for value in (b'', [], None, ''):
            issues = validate_for_sop_class_detailed(image(PixelData=value))
            self.assertTrue(any(i.tag == Tag.PixelData and i.is_error for i in issues))

    def test_rejects_nonstandard_32_bit_rle_image(self):
        with self.assertRaises(DicomValidationError):
            compress_pixel_data(image(BitsAllocated=32, BitsStored=32, HighBit=31,
                                       PixelData=struct.pack('<II', 1, 2)))

    def test_rle_decompression_checks_budget_before_allocation_or_mutation(self):
        ds = compress_pixel_data(image())
        original = ds[Tag.PixelData]
        with self.assertRaises(DicomValidationError):
            decompress_pixel_data(ds, max_output_bytes=1)
        self.assertIs(ds[Tag.PixelData], original)
        from dicomforge.rle import rle_decode_frame
        with self.assertRaises(DicomValidationError):
            rle_decode_frame(ds[Tag.PixelData].fragments[0], rows=65535, columns=65535,
                             bits_allocated=16)

    def test_multipart_truncation_and_embedded_boundary_prefix(self):
        ct = 'multipart/related; boundary=abc'
        with self.assertRaises(DicomwebError):
            list(parse_multipart_related_streaming(ct, [b'--abc\r\nContent-Type: x\r\n\r\nshort']))
        data = b'payload\r\n--abcNOT-A-DELIMITER\r\n--abc--BINARY\r\nmore'
        wire = b'--abc\r\nContent-Type: x\r\n\r\n'+data+b'\r\n--abc--\r\n'
        for size in (1, 2, 7, 31):
            parts = list(parse_multipart_related_streaming(ct, (wire[i:i+size] for i in range(0, len(wire), size))))
            self.assertEqual(parts[0].body, data)
        with self.assertRaises(DicomwebError):
            list(iter_multipart_chunks(ct, [wire], max_part_bytes=3))

    def test_upload_generator_is_never_retried_empty(self):
        class Transport:
            def __init__(self):
                self.bodies = []
            def request(self, method, url, headers, body):
                self.bodies.append(b''.join(body))
                return DicomwebResponse(503, {})
        transport = Transport()
        RetryTransport(transport, backoff_base=0).request('POST', 'https://example.invalid', {}, iter([b'data']))
        self.assertEqual(transport.bodies, [b'data'])

    def test_stream_close_on_early_exit_and_stow_partial_outcomes(self):
        called = []
        with StreamingDicomwebResponse(200, {}, iter([b'a', b'b']), lambda: called.append(True)):
            pass
        self.assertEqual(called, [True])
        response = DicomwebResponse(202, {}, json.dumps({
            '00081199': {'vr': 'SQ', 'Value': [{'00081155': {'vr': 'UI', 'Value': ['1.2.3']}}]},
            '00081198': {'vr': 'SQ', 'Value': [{'00081155': {'vr': 'UI', 'Value': ['1.2.4']},
                                               '00081197': {'vr': 'US', 'Value': [42752]}}]}
        }).encode())
        result = response.store_result()
        self.assertFalse(result.is_success)
        self.assertEqual(result.failed[0].failure_reason, 42752)

    def test_stream_retrieval_stages_incomplete_instances_and_closes_connection(self):
        closed = []
        wire = b'--abc\r\nContent-Type: application/dicom\r\n\r\npayload\r\n--abc--\r\n'
        class Transport:
            def stream(self, *args, **kwargs):
                return StreamingDicomwebResponse(200, {'content-type': 'multipart/related; boundary=abc'},
                                                iter(wire[index:index+3] for index in range(0, len(wire), 3)),
                                                lambda: closed.append(True))
        client = DicomwebClient('https://example.invalid', Transport())
        paths = list(client.retrieve_study_to('1.2.3', self.root/'complete'))
        self.assertEqual(paths[0].read_bytes(), b'payload')
        self.assertTrue(closed)
        wire = wire[:-12]
        with self.assertRaises(DicomwebError):
            list(client.retrieve_study_to('1.2.3', self.root/'incomplete'))
        self.assertEqual(list((self.root/'incomplete').iterdir()), [])

    def test_read_write_file_meta_and_nested_endian_semantics(self):
        ds = image()
        ds.set('SourceApplicationEntityTitle', 'SYNTHETIC-AE', vr='AE')
        child = DicomDataset()
        child.set((0x0011, 0x1001), struct.pack('<HH', 1, 258), vr='OW')
        ds['ReferencedStudySequence'] = [child]
        output = part10.loads(part10.dumps(ds, transfer_syntax=TS.ExplicitVRBigEndian))
        self.assertEqual(output['SourceApplicationEntityTitle'], 'SYNTHETIC-AE')
        self.assertEqual(struct.unpack('>HH', output['ReferencedStudySequence'][0][(0x0011, 0x1001)]), (1, 258))
        ds['MediaStorageSOPInstanceUID'] = '1.2.999'
        with self.assertRaises(DicomValidationError):
            part10.dumps(ds)

    @unittest.skipUnless(HAS_PYDICOM, 'optional pydicom')
    def test_nested_pydicom_deidentification_and_roundtrip(self):
        child = DicomDataset({'PatientName': 'NESTED-SYNTHETIC', (0x0011, 0x1010): b'phi'})
        ds = image(ReferencedStudySequence=[child])
        path = self.root/'nested.dcm'
        write(path, ds)
        for reader in ('native', 'pydicom'):
            for writer in ('native', 'pydicom'):
                restored = read(path, backend=reader)
                AnonymizationPlan.starter_profile().apply(restored)
                output = self.root/f'{reader}-{writer}.dcm'
                write(output, restored, backend=writer)
                checked = read(output)
                nested = checked[Tag.ReferencedStudySequence][0]
                self.assertEqual(nested[Tag.PatientName], 'Anonymous')
                self.assertNotIn((0x0011, 0x1010), nested)
        self.assertIsInstance(from_pydicom(to_pydicom(ds))[Tag.ReferencedStudySequence][0], DicomDataset)

    @unittest.skipUnless(HAS_PYDICOM, 'optional pydicom')
    def test_rle_all_backend_combinations(self):
        ds = compress_pixel_data(image())
        for writer in ('native', 'pydicom'):
            path = self.root/f'{writer}.dcm'
            write(path, ds, backend=writer)
            for reader in ('native', 'pydicom'):
                restored = read(path, backend=reader)
                decompress_pixel_data(restored)
                self.assertEqual(restored[Tag.PixelData], struct.pack('<HH', 258, 1024))

    @unittest.skipUnless(HAS_PYDICOM, 'optional pydicom')
    def test_pydicom_decimal_lexical_values_preserved(self):
        ds = image(RescaleSlope='1.0000000000')
        source = self.root/'lexical.dcm'
        write(source, ds)
        restored = read(source, backend='pydicom')
        for backend in ('native', 'pydicom'):
            output = self.root/f'lexical-{backend}.dcm'
            write(output, restored, backend=backend)
            self.assertIn(b'1.0000000000', output.read_bytes())

    @unittest.skipUnless(HAS_PIXELS, 'optional pixels')
    def test_pixel_values_byte_order_stored_bits_and_modality_preview(self):
        from dicomforge.adapt import pixel_array, to_pil_image
        for syntax in (TS.ExplicitVRLittleEndian, TS.ExplicitVRBigEndian):
            ds = part10.loads(part10.dumps(image(), transfer_syntax=syntax))
            self.assertEqual(pixel_array(ds).tolist(), [[258, 1024]])
        ds = image(BitsStored=12, HighBit=11, PixelRepresentation=1, PixelData=struct.pack('<HH', 4095, 2048))
        self.assertEqual(pixel_array(ds).tolist(), [[-1, -2048]])
        self.assertEqual(pixel_array(compress_pixel_data(ds)).tolist(), [[-1, -2048]])
        ds = image(PixelData=struct.pack('<HH', 0, 1024), RescaleIntercept=-1024,
                   WindowCenter=[0, 10], WindowWidth=[400, 100])
        self.assertEqual(list(to_pil_image(ds).getdata()), [0, 127])

    @unittest.skipUnless(HAS_PIXELS, 'optional pixels')
    def test_bitpacked_multiframe_and_custom_codec_execute(self):
        import numpy as np
        from dicomforge.adapt import pixel_array
        from dicomforge.codecs import Codec, CodecRegistry
        ds = image(Columns=3, NumberOfFrames=2, BitsAllocated=1, BitsStored=1, HighBit=0,
                   PixelData=b'\x35\x00')
        self.assertEqual(pixel_array(ds, frame=1).tolist(), [[0, 1, 1]])
        registry = CodecRegistry([Codec('custom', frozenset({TS.JPEG2000Lossless}),
                                       decode_frame=lambda ds, index: np.array([[index, 7]]))])
        custom = image(TransferSyntaxUID=TS.JPEG2000Lossless)
        self.assertEqual(pixel_array(custom, registry=registry).tolist(), [[0, 7]])
        with self.assertRaises(DicomValidationError):
            pixel_array(image(), max_frame_bytes=1)


if __name__ == '__main__':
    unittest.main()
