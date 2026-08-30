"""WebSocket gateway: order entry in, L2 market data out.

Design:
  - One asyncio task per connection, all sharing one OrderBook.
  - The book is synchronous and single-threaded. Because asyncio runs one
    coroutine at a time and no await happens mid-match, submit() and cancel()
    are effectively atomic. No locking needed, and none should be added
    without also auditing every await inside the matching path.
  - Every mutation broadcasts a new L2 snapshot to all subscribers.

Protocol is line-delimited JSON.

Client -> server:
    {"action": "submit", "id": "o1", "side": "BUY", "price": 100,
     "quantity": 10, "type": "LIMIT"}
    {"action": "cancel", "id": "o1"}
    {"action": "snapshot"}

Server -> client:
    {"type": "ack", "order_id": "o1", "trades": [...], "resting": true}
    {"type": "book", "bids": [[price, qty], ...], "asks": [...],
     "best_bid": 100, "best_ask": 101, "spread": 1}
    {"type": "error", "message": "..."}
"""

import asyncio
import json
from typing import Set

import websockets

from engine import Order, OrderBook, OrderType, Side


class Gateway:
    def __init__(self, symbol="TEST", min_price=1, max_price=1_000_000, depth=10):
        self.book = OrderBook(symbol, min_price, max_price)
        self.depth = depth
        self.clients: Set = set()

    # ---------- messages ----------

    def book_message(self):
        snap = self.book.snapshot(self.depth)
        return {
            "type": "book",
            "symbol": self.book.symbol,
            "bids": [[p, q] for p, q in snap["bids"]],
            "asks": [[p, q] for p, q in snap["asks"]],
            "best_bid": self.book.best_bid,
            "best_ask": self.book.best_ask,
            "spread": self.book.spread,
        }

    async def broadcast(self, message):
        """Push to every connected client. Dead sockets are dropped, not raised."""
        if not self.clients:
            return
        payload = json.dumps(message)
        results = await asyncio.gather(
            *(c.send(payload) for c in self.clients), return_exceptions=True
        )
        for client, result in zip(list(self.clients), results):
            if isinstance(result, Exception):
                self.clients.discard(client)

    # ---------- request handling ----------

    def handle(self, request):
        """Apply one request to the book. Returns (reply, book_changed)."""
        action = request.get("action")

        if action == "snapshot":
            return self.book_message(), False

        if action == "cancel":
            order_id = request.get("id")
            if not order_id:
                return {"type": "error", "message": "cancel needs an id"}, False
            found = self.book.cancel(order_id)
            return {"type": "ack", "order_id": order_id, "cancelled": found}, found

        if action == "submit":
            try:
                order = Order(
                    order_id=str(request["id"]),
                    side=Side(request["side"].upper()),
                    price=request.get("price"),
                    quantity=int(request["quantity"]),
                    type=OrderType(request.get("type", "LIMIT").upper()),
                )
            except (KeyError, ValueError, AttributeError, TypeError) as exc:
                return {"type": "error", "message": f"bad order: {exc}"}, False

            try:
                trades = self.book.submit(order)
            except ValueError as exc:
                return {"type": "error", "message": str(exc)}, False

            return {
                "type": "ack",
                "order_id": order.order_id,
                "trades": [
                    {"price": t.price, "quantity": t.quantity,
                     "buy": t.buy_order_id, "sell": t.sell_order_id}
                    for t in trades
                ],
                "resting": order.order_id in self.book._orders,
            }, True

        return {"type": "error", "message": f"unknown action: {action!r}"}, False

    async def serve_client(self, socket):
        self.clients.add(socket)
        try:
            await socket.send(json.dumps(self.book_message()))
            async for raw in socket:
                try:
                    request = json.loads(raw)
                except json.JSONDecodeError:
                    await socket.send(json.dumps(
                        {"type": "error", "message": "invalid JSON"}))
                    continue

                reply, changed = self.handle(request)
                await socket.send(json.dumps(reply))
                if changed:
                    await self.broadcast(self.book_message())
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(socket)


async def main(host="localhost", port=8765):
    gateway = Gateway("RELIANCE", 1, 200_000)
    async with websockets.serve(gateway.serve_client, host, port):
        print(f"gateway listening on ws://{host}:{port}")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
