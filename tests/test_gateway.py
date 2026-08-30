import asyncio
import json

import pytest
import websockets

from gateway import Gateway


@pytest.fixture
def gw():
    return Gateway("TEST", 1, 10_000)


# ---------- request handling, no sockets involved ----------

def test_submit_returns_ack(gw):
    reply, changed = gw.handle({"action": "submit", "id": "a1", "side": "SELL",
                                "price": 100, "quantity": 10})
    assert reply["type"] == "ack" and reply["resting"] is True
    assert changed is True


def test_submit_produces_trades(gw):
    gw.handle({"action": "submit", "id": "a1", "side": "SELL", "price": 100, "quantity": 10})
    reply, _ = gw.handle({"action": "submit", "id": "b1", "side": "BUY",
                          "price": 100, "quantity": 10})
    assert reply["trades"] == [{"price": 100, "quantity": 10, "buy": "b1", "sell": "a1"}]
    assert reply["resting"] is False


def test_market_order_over_the_wire(gw):
    gw.handle({"action": "submit", "id": "a1", "side": "SELL", "price": 100, "quantity": 10})
    reply, _ = gw.handle({"action": "submit", "id": "m", "side": "BUY",
                          "quantity": 5, "type": "MARKET"})
    assert reply["trades"][0]["price"] == 100


def test_fok_rejection_over_the_wire(gw):
    gw.handle({"action": "submit", "id": "a1", "side": "SELL", "price": 100, "quantity": 10})
    reply, changed = gw.handle({"action": "submit", "id": "f", "side": "BUY",
                                "price": 100, "quantity": 50, "type": "FOK"})
    assert reply["trades"] == [] and reply["resting"] is False
    assert gw.book.open_order_count == 1


def test_cancel(gw):
    gw.handle({"action": "submit", "id": "a1", "side": "SELL", "price": 100, "quantity": 10})
    reply, changed = gw.handle({"action": "cancel", "id": "a1"})
    assert reply["cancelled"] is True and changed is True


def test_cancel_unknown_order_does_not_change_book(gw):
    reply, changed = gw.handle({"action": "cancel", "id": "nope"})
    assert reply["cancelled"] is False and changed is False


def test_snapshot_shape(gw):
    gw.handle({"action": "submit", "id": "a1", "side": "SELL", "price": 101, "quantity": 10})
    gw.handle({"action": "submit", "id": "b1", "side": "BUY", "price": 99, "quantity": 5})
    msg, changed = gw.handle({"action": "snapshot"})
    assert msg["bids"] == [[99, 5]] and msg["asks"] == [[101, 10]]
    assert msg["best_bid"] == 99 and msg["best_ask"] == 101 and msg["spread"] == 2
    assert changed is False


def test_book_message_is_json_serialisable(gw):
    json.dumps(gw.book_message())


@pytest.mark.parametrize("request_body", [
    {"action": "submit", "id": "x", "side": "SIDEWAYS", "price": 1, "quantity": 1},
    {"action": "submit", "id": "x", "side": "BUY", "quantity": 1},          # no price
    {"action": "submit", "id": "x", "side": "BUY", "price": 1},             # no quantity
    {"action": "submit", "id": "x", "side": "BUY", "price": 1, "quantity": 0},
    {"action": "cancel"},                                                    # no id
    {"action": "teleport"},
])
def test_bad_requests_return_errors_without_crashing(gw, request_body):
    reply, changed = gw.handle(request_body)
    assert reply["type"] == "error"
    assert changed is False


def test_duplicate_order_id_is_an_error(gw):
    gw.handle({"action": "submit", "id": "dup", "side": "SELL", "price": 100, "quantity": 10})
    reply, _ = gw.handle({"action": "submit", "id": "dup", "side": "SELL",
                          "price": 101, "quantity": 10})
    assert reply["type"] == "error"


# ---------- end to end over a real socket ----------

@pytest.mark.asyncio
async def test_round_trip_over_websocket():
    gw = Gateway("TEST", 1, 10_000)
    async with websockets.serve(gw.serve_client, "localhost", 8799):
        async with websockets.connect("ws://localhost:8799") as ws:
            first = json.loads(await ws.recv())
            assert first["type"] == "book"

            await ws.send(json.dumps({"action": "submit", "id": "a1", "side": "SELL",
                                      "price": 100, "quantity": 10}))
            ack = json.loads(await ws.recv())
            assert ack["type"] == "ack" and ack["resting"] is True

            update = json.loads(await ws.recv())
            assert update["type"] == "book" and update["asks"] == [[100, 10]]


@pytest.mark.asyncio
async def test_second_client_sees_first_clients_order():
    gw = Gateway("TEST", 1, 10_000)
    async with websockets.serve(gw.serve_client, "localhost", 8798):
        async with websockets.connect("ws://localhost:8798") as watcher:
            await watcher.recv()  # initial snapshot

            async with websockets.connect("ws://localhost:8798") as trader:
                await trader.recv()
                await trader.send(json.dumps({"action": "submit", "id": "a1",
                                              "side": "SELL", "price": 100,
                                              "quantity": 7}))
                await trader.recv()  # ack

            broadcast = json.loads(await asyncio.wait_for(watcher.recv(), timeout=2))
            assert broadcast["type"] == "book"
            assert broadcast["asks"] == [[100, 7]]


@pytest.mark.asyncio
async def test_malformed_json_does_not_kill_the_connection():
    gw = Gateway("TEST", 1, 10_000)
    async with websockets.serve(gw.serve_client, "localhost", 8797):
        async with websockets.connect("ws://localhost:8797") as ws:
            await ws.recv()
            await ws.send("{not json")
            error = json.loads(await ws.recv())
            assert error["type"] == "error"

            await ws.send(json.dumps({"action": "snapshot"}))
            assert json.loads(await ws.recv())["type"] == "book"
