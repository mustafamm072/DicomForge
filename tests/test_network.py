import asyncio
import unittest

from dicomforge import DicomDataset, Tag
from dicomforge.network import (
    Association,
    AssociationClosedError,
    AssociationRejectedError,
    DimseServer,
    DimseStatus,
    dataset_from_message,
    dataset_to_message,
    open_association,
)
from dicomforge.uids import DimseStatusCode, SopClassUID


class NetworkingTests(unittest.IsolatedAsyncioTestCase):
    async def test_association_lifecycle_and_c_echo(self):
        async with DimseServer(ae_title="TEST-SCP") as server:
            association = await open_association(
                "127.0.0.1",
                server.bound_port,
                calling_ae_title="TEST-SCU",
                called_ae_title="TEST-SCP",
            )
            self.assertFalse(association.is_closed)

            status = await association.c_echo()

            self.assertTrue(status.is_success)
            await association.release()
            self.assertTrue(association.is_closed)
            with self.assertRaises(AssociationClosedError):
                await association.c_echo()

    async def test_association_rejects_unknown_called_ae_title(self):
        async with DimseServer(ae_title="KNOWN") as server:
            with self.assertRaisesRegex(AssociationRejectedError, "unknown AE title"):
                await open_association(
                    "127.0.0.1",
                    server.bound_port,
                    called_ae_title="MISSING",
                )

    async def test_association_rejects_unsupported_sop_classes(self):
        async with DimseServer(
            ae_title="KNOWN",
            supported_sop_classes=(SopClassUID.Verification,),
        ) as server:
            with self.assertRaisesRegex(
                AssociationRejectedError,
                "no supported presentation contexts",
            ):
                await open_association(
                    "127.0.0.1",
                    server.bound_port,
                    called_ae_title="KNOWN",
                    requested_sop_classes=(SopClassUID.CTImageStorage,),
                )

    def test_dimse_status_uses_standard_status_constants(self):
        self.assertEqual(DimseStatus.SUCCESS.code, DimseStatusCode.Success)
        self.assertEqual(DimseStatus.PENDING.code, DimseStatusCode.Pending)
        self.assertTrue(DimseStatus.PENDING.is_pending)

    async def test_c_find_returns_datasets(self):
        async def find_handler(request, query):
            self.assertEqual(request.calling_ae_title, "FIND-SCU")
            self.assertEqual(query.get(Tag.PatientName), "Ada")
            return [
                DicomDataset(
                    {
                        Tag.PatientName: "Ada Lovelace",
                        Tag.StudyInstanceUID: "1.2.3",
                    }
                )
            ]

        async with DimseServer(ae_title="FIND-SCP", find_handler=find_handler) as server:
            async with await Association.connect(
                "127.0.0.1",
                server.bound_port,
                calling_ae_title="FIND-SCU",
                called_ae_title="FIND-SCP",
            ) as association:
                results = await association.c_find({Tag.PatientName: "Ada"})

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get(Tag.StudyInstanceUID), "1.2.3")

    async def test_c_move_invokes_destination_handler(self):
        seen = {}

        def move_handler(request, query, destination):
            seen["request"] = request
            seen["query"] = query
            seen["destination"] = destination
            return DimseStatus(0x0000, "Moved 2 instances")

        async with DimseServer(ae_title="MOVE-SCP", move_handler=move_handler) as server:
            async with await open_association(
                "127.0.0.1",
                server.bound_port,
                called_ae_title="MOVE-SCP",
            ) as association:
                status = await association.c_move({Tag.PatientID: "123"}, "STORE-SCP")

        self.assertTrue(status.is_success)
        self.assertEqual(status.message, "Moved 2 instances")
        self.assertEqual(seen["query"].get(Tag.PatientID), "123")
        self.assertEqual(seen["destination"], "STORE-SCP")

    async def test_c_store_preserves_dataset_and_byte_values(self):
        stored = []

        async def store_handler(request, dataset):
            stored.append(dataset)
            return DimseStatus.SUCCESS

        dataset = DicomDataset({Tag.SOPInstanceUID: "1.2.3.4", Tag.PixelData: b"\x00\x01"})
        async with DimseServer(ae_title="STORE-SCP", store_handler=store_handler) as server:
            async with await open_association(
                "127.0.0.1",
                server.bound_port,
                called_ae_title="STORE-SCP",
            ) as association:
                status = await association.c_store(dataset)

        self.assertTrue(status.is_success)
        self.assertEqual(stored[0].get(Tag.SOPInstanceUID), "1.2.3.4")
        self.assertEqual(stored[0].get(Tag.PixelData), b"\x00\x01")

    async def test_c_store_applies_backpressure_with_bounded_queue(self):
        started = asyncio.Event()
        unblock = asyncio.Event()
        stored = []

        async def store_handler(request, dataset):
            stored.append(dataset.get(Tag.SOPInstanceUID))
            started.set()
            await unblock.wait()
            return DimseStatus.SUCCESS

        async with DimseServer(
            ae_title="STORE-SCP",
            store_handler=store_handler,
            store_queue_size=1,
        ) as server:
            async with await open_association(
                "127.0.0.1",
                server.bound_port,
                called_ae_title="STORE-SCP",
            ) as first:
                async with await open_association(
                    "127.0.0.1",
                    server.bound_port,
                    called_ae_title="STORE-SCP",
                ) as second:
                    async with await open_association(
                        "127.0.0.1",
                        server.bound_port,
                        called_ae_title="STORE-SCP",
                    ) as third:
                        tasks = [
                            asyncio.create_task(
                                first.c_store({Tag.SOPInstanceUID: "1"})
                            ),
                            asyncio.create_task(
                                second.c_store({Tag.SOPInstanceUID: "2"})
                            ),
                            asyncio.create_task(
                                third.c_store({Tag.SOPInstanceUID: "3"})
                            ),
                        ]
                        await asyncio.wait_for(started.wait(), timeout=1)
                        await asyncio.sleep(0.05)

                        self.assertFalse(tasks[0].done())
                        self.assertFalse(tasks[1].done())
                        self.assertFalse(tasks[2].done())

                        unblock.set()
                        statuses = await asyncio.gather(*tasks)

        self.assertEqual([status.is_success for status in statuses], [True, True, True])
        self.assertEqual(stored, ["1", "2", "3"])

    async def test_cancellation_closes_client_socket(self):
        started = asyncio.Event()
        unblock = asyncio.Event()

        async def store_handler(request, dataset):
            started.set()
            await unblock.wait()
            return DimseStatus.SUCCESS

        async with DimseServer(ae_title="STORE-SCP", store_handler=store_handler) as server:
            association = await open_association(
                "127.0.0.1",
                server.bound_port,
                called_ae_title="STORE-SCP",
            )
            task = asyncio.create_task(association.c_store({Tag.SOPInstanceUID: "1"}))
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()

            with self.assertRaises(asyncio.CancelledError):
                await task

            self.assertTrue(association.is_closed)
            unblock.set()

    async def test_server_close_cleans_up_blocked_store_socket(self):
        started = asyncio.Event()
        unblock = asyncio.Event()

        async def store_handler(request, dataset):
            started.set()
            await unblock.wait()
            return DimseStatus.SUCCESS

        server = DimseServer(ae_title="STORE-SCP", store_handler=store_handler)
        await server.start()
        association = await open_association(
            "127.0.0.1",
            server.bound_port,
            called_ae_title="STORE-SCP",
        )
        task = asyncio.create_task(association.c_store({Tag.SOPInstanceUID: "1"}))
        await asyncio.wait_for(started.wait(), timeout=1)

        await asyncio.wait_for(server.close(), timeout=1)

        with self.assertRaises(Exception):
            await task
        self.assertTrue(association.is_closed)
        unblock.set()
        await association.close()

    def test_dataset_message_roundtrip(self):
        sequence_tag = Tag(0x0008, 0x1115)
        dataset = DicomDataset(
            {
                Tag.PatientName: "Ada",
                Tag.PixelData: bytearray(b"\x00\x01"),
                sequence_tag: [DicomDataset({Tag.SOPInstanceUID: "1.2.3"})],
            }
        )

        roundtripped = dataset_from_message(dataset_to_message(dataset))

        self.assertEqual(roundtripped.get(Tag.PatientName), "Ada")
        self.assertEqual(roundtripped.get(Tag.PixelData), b"\x00\x01")
        self.assertEqual(roundtripped.get(sequence_tag)[0].get(Tag.SOPInstanceUID), "1.2.3")


if __name__ == "__main__":
    unittest.main()
