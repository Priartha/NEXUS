import asyncio
import json
import websockets

async def main():
    async with websockets.connect('wss://public-socket.india.delta.exchange') as ws:
        await ws.send(json.dumps({'type': 'enable_heartbeat'}))
        await ws.send(json.dumps({'type': 'subscribe', 'payload': {'channels': [{'name': 'ticker', 'symbols': ['BTCUSD']}]}}))
        print('subscribed')
        for _ in range(5):
            msg = await ws.recv()
            print(msg)

asyncio.run(main())
