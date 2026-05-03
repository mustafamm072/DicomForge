"""Async networking primitives for lightweight DIMSE-style services.

The module intentionally keeps the wire format small and dependency-free. It is
not a full DICOM Upper Layer implementation; it gives applications a predictable
async association lifecycle and command semantics that can be backed by a real
DIMSE transport later without changing the high-level service API.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Union

from dicomforge.dataset import DicomDataset
from dicomforge.errors import DicomForgeError
from dicomforge.uids import DimseStatusCode, SopClassUID

JsonObject = Dict[str, Any]
DatasetInput = Union[DicomDataset, Dict[Any, Any]]
EchoHandler = Callable[["AssociationRequest"], Union["DimseStatus", Awaitable["DimseStatus"]]]
FindHandler = Callable[
    ["AssociationRequest", DicomDataset],
    Union[Iterable[DicomDataset], Awaitable[Iterable[DicomDataset]]],
]
MoveHandler = Callable[
    ["AssociationRequest", DicomDataset, str],
    Union["DimseStatus", Awaitable["DimseStatus"]],
]
StoreHandler = Callable[
    ["AssociationRequest", DicomDataset],
    Union["DimseStatus", Awaitable["DimseStatus"]],
]


class NetworkError(DicomForgeError):
    """Raised when an association or DIMSE command fails."""


class AssociationRejectedError(NetworkError):
    """Raised when the SCP rejects an association request."""


class AssociationClosedError(NetworkError):
    """Raised when a command is attempted on a closed association."""


@dataclass(frozen=True)
class DimseStatus:
    """Result status for a DIMSE command."""

    code: int
    message: str = "Success"
    SUCCESS: ClassVar["DimseStatus"]
    PENDING: ClassVar["DimseStatus"]
    CANCEL: ClassVar["DimseStatus"]
    UNABLE_TO_PROCESS: ClassVar["DimseStatus"]

    @property
    def is_success(self) -> bool:
        return self.code == DimseStatusCode.Success

    @property
    def is_pending(self) -> bool:
        return self.code == DimseStatusCode.Pending

    def to_message(self) -> JsonObject:
        return {"code": self.code, "message": self.message}

    @classmethod
    def from_message(cls, value: JsonObject) -> "DimseStatus":
        return cls(
            code=int(value.get("code", DimseStatusCode.UnableToProcess)),
            message=str(value.get("message", "")),
        )


DimseStatus.SUCCESS = DimseStatus(DimseStatusCode.Success, "Success")
DimseStatus.PENDING = DimseStatus(DimseStatusCode.Pending, "Pending")
DimseStatus.CANCEL = DimseStatus(DimseStatusCode.Cancel, "Cancel")
DimseStatus.UNABLE_TO_PROCESS = DimseStatus(
    DimseStatusCode.UnableToProcess,
    "Unable to process",
)


@dataclass(frozen=True)
class AssociationRequest:
    """Metadata supplied during association negotiation."""

    calling_ae_title: str
    called_ae_title: str
    requested_sop_classes: Tuple[str, ...] = (
        SopClassUID.Verification,
        SopClassUID.StudyRootQueryRetrieveInformationModelFind,
        SopClassUID.StudyRootQueryRetrieveInformationModelMove,
        SopClassUID.SecondaryCaptureImageStorage,
    )


def _encode_value(value: Any) -> Any:
    if isinstance(value, DicomDataset):
        return {"__dicomforge_dataset__": dataset_to_message(value)}
    if isinstance(value, bytes):
        return {"__dicomforge_bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, bytearray):
        return {"__dicomforge_bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, list):
        return [_encode_value(item) for item in value]
    if isinstance(value, tuple):
        return [_encode_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode_value(item) for key, item in value.items()}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict):
        dataset = value.get("__dicomforge_dataset__")
        if isinstance(dataset, dict):
            return dataset_from_message(dataset)
        encoded = value.get("__dicomforge_bytes__")
        if isinstance(encoded, str):
            return base64.b64decode(encoded.encode("ascii"))
        return {key: _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    return value


def dataset_to_message(dataset: DatasetInput) -> JsonObject:
    """Serialize a dataset into a JSON-compatible message payload."""

    normalized = dataset if isinstance(dataset, DicomDataset) else DicomDataset(dataset)
    return {key: _encode_value(value) for key, value in normalized.to_plain_dict().items()}


def dataset_from_message(message: JsonObject) -> DicomDataset:
    """Deserialize a dataset from a JSON-compatible message payload."""

    return DicomDataset({key: _decode_value(value) for key, value in message.items()})


async def _read_message(reader: asyncio.StreamReader) -> JsonObject:
    size_bytes = await reader.readexactly(4)
    size = int.from_bytes(size_bytes, "big")
    if size <= 0:
        raise NetworkError("Received an empty networking message.")
    payload = await reader.readexactly(size)
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise NetworkError("Received a malformed networking message.")
    return decoded


async def _write_message(writer: asyncio.StreamWriter, message: JsonObject) -> None:
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    writer.write(len(payload).to_bytes(4, "big") + payload)
    await writer.drain()


async def _maybe_await(value: Union[Any, Awaitable[Any]]) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
        return await value
    return value


class Association:
    """Async client association with explicit release and socket cleanup."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request: AssociationRequest,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self.request = request
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def is_closed(self) -> bool:
        return self._closed or self._writer.is_closing()

    async def __aenter__(self) -> "Association":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    @classmethod
    async def connect(
        cls,
        host: str,
        port: int,
        *,
        calling_ae_title: str = "DICOMFORGE",
        called_ae_title: str = "ANY-SCP",
        requested_sop_classes: Iterable[str] = AssociationRequest.requested_sop_classes,
    ) -> "Association":
        reader, writer = await asyncio.open_connection(host, port)
        requested = tuple(requested_sop_classes)
        request = AssociationRequest(calling_ae_title, called_ae_title, requested)
        association = cls(reader, writer, request)
        try:
            await _write_message(
                writer,
                {
                    "type": "associate",
                    "calling_ae_title": calling_ae_title,
                    "called_ae_title": called_ae_title,
                    "requested_sop_classes": requested,
                },
            )
            response = await _read_message(reader)
            if response.get("type") != "associate_accept":
                reason = str(response.get("reason", "association rejected"))
                raise AssociationRejectedError(reason)
            return association
        except Exception:
            await association.close()
            raise

    async def release(self) -> None:
        if self.is_closed:
            return
        try:
            async with self._lock:
                if not self.is_closed:
                    await _write_message(self._writer, {"type": "release"})
                    response = await _read_message(self._reader)
                    if response.get("type") != "release_response":
                        raise NetworkError("Association release was not acknowledged.")
        finally:
            await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (ConnectionError, OSError):
            pass

    async def _command(self, message: JsonObject) -> JsonObject:
        if self.is_closed:
            raise AssociationClosedError("Cannot send a DIMSE command on a closed association.")
        try:
            async with self._lock:
                await _write_message(self._writer, message)
                response = await _read_message(self._reader)
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception:
            await self.close()
            raise
        if response.get("type") == "error":
            raise NetworkError(str(response.get("message", "DIMSE command failed.")))
        return response

    async def c_echo(self) -> DimseStatus:
        response = await self._command({"type": "c_echo"})
        return DimseStatus.from_message(response.get("status", {}))

    async def c_find(self, query: DatasetInput) -> List[DicomDataset]:
        response = await self._command({"type": "c_find", "query": dataset_to_message(query)})
        results = response.get("results", [])
        if not isinstance(results, list):
            raise NetworkError("C-FIND response did not contain a result list.")
        return [dataset_from_message(result) for result in results]

    async def c_move(self, query: DatasetInput, destination_ae_title: str) -> DimseStatus:
        response = await self._command(
            {
                "type": "c_move",
                "query": dataset_to_message(query),
                "destination_ae_title": destination_ae_title,
            }
        )
        return DimseStatus.from_message(response.get("status", {}))

    async def c_store(self, dataset: DatasetInput) -> DimseStatus:
        response = await self._command({"type": "c_store", "dataset": dataset_to_message(dataset)})
        return DimseStatus.from_message(response.get("status", {}))


class DimseServer:
    """Async SCP for C-ECHO, C-FIND, C-MOVE, and backpressure-aware C-STORE."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        ae_title: str = "ANY-SCP",
        echo_handler: Optional[EchoHandler] = None,
        find_handler: Optional[FindHandler] = None,
        move_handler: Optional[MoveHandler] = None,
        store_handler: Optional[StoreHandler] = None,
        supported_sop_classes: Iterable[str] = AssociationRequest.requested_sop_classes,
        store_queue_size: int = 8,
    ) -> None:
        self.host = host
        self.port = port
        self.ae_title = ae_title
        self.echo_handler = echo_handler
        self.find_handler = find_handler
        self.move_handler = move_handler
        self.store_handler = store_handler
        self.supported_sop_classes = tuple(supported_sop_classes)
        self.store_queue_size = store_queue_size
        self._server: Optional[asyncio.AbstractServer] = None
        self._store_queue: asyncio.Queue[
            Optional[Tuple[AssociationRequest, DicomDataset, "asyncio.Future[DimseStatus]"]]
        ] = asyncio.Queue(maxsize=store_queue_size)
        self._store_worker: Optional[asyncio.Task[None]] = None
        self._connections: List[asyncio.StreamWriter] = []

    @property
    def sockets(self) -> Tuple[Any, ...]:
        if self._server is None or self._server.sockets is None:
            return ()
        return tuple(self._server.sockets)

    @property
    def bound_port(self) -> int:
        sockets = self.sockets
        if not sockets:
            raise NetworkError("DIMSE server is not started.")
        return int(sockets[0].getsockname()[1])

    async def __aenter__(self) -> "DimseServer":
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self._server is not None:
            return
        self._store_worker = asyncio.create_task(self._run_store_worker())
        self._server = await asyncio.start_server(self._handle_connection, self.host, self.port)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for writer in list(self._connections):
            writer.close()
        for writer in list(self._connections):
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
        if self._store_worker is not None:
            self._store_worker.cancel()
            try:
                await self._store_worker
            except asyncio.CancelledError:
                pass
            self._store_worker = None
        while not self._store_queue.empty():
            item = self._store_queue.get_nowait()
            try:
                if item is not None:
                    _, _, future = item
                    if not future.done():
                        future.set_exception(
                            NetworkError("DIMSE server closed before C-STORE completed.")
                        )
            finally:
                self._store_queue.task_done()

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        if self._server is None:
            raise NetworkError("DIMSE server failed to start.")
        await self._server.serve_forever()

    async def _run_store_worker(self) -> None:
        while True:
            item = await self._store_queue.get()
            try:
                if item is None:
                    return
                request, dataset, future = item
                if future.cancelled():
                    continue
                try:
                    if self.store_handler is None:
                        status = DimseStatus.SUCCESS
                    else:
                        status = await _maybe_await(self.store_handler(request, dataset))
                    if not isinstance(status, DimseStatus):
                        status = DimseStatus.SUCCESS
                    if not future.done():
                        future.set_result(status)
                except Exception as exc:
                    if not future.done():
                        future.set_exception(exc)
            finally:
                self._store_queue.task_done()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._connections.append(writer)
        try:
            first = await _read_message(reader)
            if first.get("type") != "associate":
                await _write_message(
                    writer,
                    {"type": "associate_reject", "reason": "missing associate"},
                )
                return
            request = AssociationRequest(
                calling_ae_title=str(first.get("calling_ae_title", "")),
                called_ae_title=str(first.get("called_ae_title", "")),
                requested_sop_classes=tuple(first.get("requested_sop_classes", ())),
            )
            if request.called_ae_title not in (self.ae_title, "ANY-SCP"):
                await _write_message(
                    writer,
                    {
                        "type": "associate_reject",
                        "reason": f"unknown AE title {request.called_ae_title}",
                    },
                )
                return
            accepted_sop_classes = tuple(
                uid for uid in request.requested_sop_classes if uid in self.supported_sop_classes
            )
            if not accepted_sop_classes:
                await _write_message(
                    writer,
                    {
                        "type": "associate_reject",
                        "reason": "no supported presentation contexts",
                    },
                )
                return
            await _write_message(writer, {"type": "associate_accept", "ae_title": self.ae_title})
            while not reader.at_eof():
                message = await _read_message(reader)
                if message.get("type") == "release":
                    await _write_message(writer, {"type": "release_response"})
                    return
                response = await self._dispatch(request, message)
                await _write_message(writer, response)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            return
        finally:
            if writer in self._connections:
                self._connections.remove(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _dispatch(self, request: AssociationRequest, message: JsonObject) -> JsonObject:
        command = message.get("type")
        try:
            if command == "c_echo":
                status = await self._handle_echo(request)
                return {"type": "c_echo_response", "status": status.to_message()}
            if command == "c_find":
                query = dataset_from_message(message.get("query", {}))
                results = await self._handle_find(request, query)
                return {
                    "type": "c_find_response",
                    "results": [dataset_to_message(result) for result in results],
                }
            if command == "c_move":
                query = dataset_from_message(message.get("query", {}))
                destination = str(message.get("destination_ae_title", ""))
                status = await self._handle_move(request, query, destination)
                return {"type": "c_move_response", "status": status.to_message()}
            if command == "c_store":
                dataset = dataset_from_message(message.get("dataset", {}))
                status = await self._handle_store(request, dataset)
                return {"type": "c_store_response", "status": status.to_message()}
            raise NetworkError(f"Unsupported DIMSE command {command!r}.")
        except Exception as exc:
            return {"type": "error", "message": str(exc)}

    async def _handle_echo(self, request: AssociationRequest) -> DimseStatus:
        if self.echo_handler is None:
            return DimseStatus.SUCCESS
        status = await _maybe_await(self.echo_handler(request))
        return status if isinstance(status, DimseStatus) else DimseStatus.SUCCESS

    async def _handle_find(
        self,
        request: AssociationRequest,
        query: DicomDataset,
    ) -> Iterable[DicomDataset]:
        if self.find_handler is None:
            return []
        return await _maybe_await(self.find_handler(request, query))

    async def _handle_move(
        self,
        request: AssociationRequest,
        query: DicomDataset,
        destination_ae_title: str,
    ) -> DimseStatus:
        if self.move_handler is None:
            return DimseStatus.SUCCESS
        status = await _maybe_await(self.move_handler(request, query, destination_ae_title))
        return status if isinstance(status, DimseStatus) else DimseStatus.SUCCESS

    async def _handle_store(
        self,
        request: AssociationRequest,
        dataset: DicomDataset,
    ) -> DimseStatus:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[DimseStatus] = loop.create_future()
        await self._store_queue.put((request, dataset, future))
        return await future


async def open_association(
    host: str,
    port: int,
    *,
    calling_ae_title: str = "DICOMFORGE",
    called_ae_title: str = "ANY-SCP",
    requested_sop_classes: Iterable[str] = AssociationRequest.requested_sop_classes,
) -> Association:
    """Open an async association to a DIMSE server."""

    return await Association.connect(
        host,
        port,
        calling_ae_title=calling_ae_title,
        called_ae_title=called_ae_title,
        requested_sop_classes=requested_sop_classes,
    )


async def start_dimse_server(
    host: str = "127.0.0.1",
    port: int = 0,
    **kwargs: Any,
) -> DimseServer:
    """Create and start a DIMSE server."""

    server = DimseServer(host, port, **kwargs)
    await server.start()
    return server
