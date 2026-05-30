import asyncio
import websockets

SESSION_ID = "d7f43a1a-3087-4785-a265-eb58a8748e8f"

async def test():
    uri = f"ws://127.0.0.1:8000/ws/stream/{SESSION_ID}"
    print(f"Connecting to {uri} ...")
    async with websockets.connect(uri) as ws:
        print("Connected!")
        msg = await ws.recv()
        print(f"Received: {msg}")

asyncio.run(test())
