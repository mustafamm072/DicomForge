import asyncio

from dicomforge.network import DimseServer, open_association


async def main() -> None:
    async with DimseServer(ae_title="LOCAL-SCP") as server:
        async with await open_association(
            "127.0.0.1",
            server.bound_port,
            called_ae_title="LOCAL-SCP",
        ) as association:
            status = await association.c_echo()
            print(status)


asyncio.run(main())
