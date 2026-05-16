import asyncio
from binance_server import _get

async def test():
    data = await _get('/api/v3/ticker/price', {'symbol': 'BTCUSDT'})
    price = float(data['price'])
    print(f'BTC Price: ${price:,.2f}')

asyncio.run(test())
