import asyncio
import websockets

async def main():
    async with websockets.connect('ws://127.0.0.1:8000/ws/chart?tf=5m') as ws:
        print('connected')
        for i in range(20):
            msg = await ws.recv()
            print('MSG', msg)

asyncio.run(main())
