# Limit Order Book

In-memory limit order book with price-time priority matching, O(1) cancellation,
and O(log N) cumulative liquidity queries.

## Layout

`SortedDict[price] -> Level`, where `Level` is an `OrderedDict` of
`order_id -> Order` with a running quantity total.

- **SortedDict** keeps price levels ordered, so `peekitem(0)` is the best price.
  Bids are keyed by `-price` so index 0 is the best on both sides.
- **OrderedDict** is a doubly linked list underneath. Insertion order gives FIFO
  within a level; delete-by-key gives O(1) cancellation at any book depth.
- **`order_id -> Order` dict** locates any resting order for cancellation.
- **Fenwick tree** per side indexes cumulative quantity across the price grid.

Prices are integer ticks. Float prices break cross detection.

## Matching

Better price wins; at equal price, earlier arrival wins. Trades execute at the
**resting** order's price, so price improvement goes to the aggressor, as on a
real exchange.

## Order types

| Type | Crosses at | Unfilled remainder |
|---|---|---|
| `LIMIT` | its limit price | rests on the book |
| `MARKET` | any price | discarded |
| `IOC` | its limit price | discarded |
| `FOK` | its limit price | rejected outright unless the whole quantity fills |

FOK checks feasibility through the liquidity index before touching the book, so
a rejected order is O(log N) and leaves no trace — no partial fills to unwind.
This is the second thing the Fenwick tree buys beyond range queries.

## Liquidity index

"How much size rests between 100 and 120?" walks every level in that range
without an index. A Fenwick tree turns it into two prefix-sum walks.

Fenwick rather than a segment tree because prefix sums are all this needs — a
segment tree earns its extra memory and code only for range min/max or lazy
updates.

## Performance

CPython 3.13 on Windows, single-threaded. Reproduce with `python benchmark.py`.

| Operation | p50 | p90 | p99 | p99.9 |
|---|---|---|---|---|
| submit (rest) | 5.60 us | 7.70 us | 13.70 us | 92.20 us |
| submit (matching) | 8.80 us | 18.60 us | 24.30 us | 115.00 us |
| cancel | 4.30 us | 5.10 us | 7.40 us | 43.30 us |
| liquidity query, Fenwick | 2.80 us | 3.30 us | 4.00 us | 17.40 us |
| liquidity query, level scan | 47.10 us | 87.40 us | 196.60 us | 421.50 us |

### Fenwick vs level scan, by query width

| Price levels | Fenwick | Scan | Speedup |
|---|---|---|---|
| 10 | 2.84 us | 4.22 us | 1.5x |
| 50 | 2.64 us | 25.24 us | 9.6x |
| 100 | 4.35 us | 74.94 us | 17.2x |
| 250 | 5.40 us | 228.25 us | 42.3x |
| 500 | 5.47 us | 438.76 us | 80.2x |
| 1000 | 5.23 us | 840.30 us | 160.7x |

The scan grows linearly with the range; the tree barely moves. **Crossover is
around 10 levels** — below that the index costs more to maintain than it saves,
and a narrow query should just walk the levels.

These are CPython numbers on a general-purpose machine. They measure
algorithmic behaviour, not production low-latency performance.

## Tests

```bash
python -m pytest tests/ -q      # 57 tests
```

Two randomised invariants beyond the unit tests:

- Fenwick index must equal the sum of price levels after every operation in a
  1,500-op mix of submits and cancels
- `best_bid` must stay strictly below `best_ask` after any order sequence

The Fenwick tree is separately cross-checked against a brute-force dict over
2,000 random updates and 500 random range queries.

## Usage

```python
from engine import OrderBook, Order, Side

book = OrderBook("RELIANCE", min_price=1, max_price=10_000)
book.submit(Order("a1", Side.SELL, 100, 50))
book.submit(Order("a2", Side.SELL, 101, 30))

for t in book.submit(Order("b1", Side.BUY, 101, 60)):
    print(t)
# TRADE 50 @ 100 (buy=b1 sell=a1)
# TRADE 10 @ 101 (buy=b1 sell=a2)

book.best_bid, book.best_ask, book.spread
book.liquidity_between(Side.SELL, 100, 105)
book.cancel("a2")
```

## WebSocket gateway

`python gateway.py` serves order entry and L2 market data on
`ws://localhost:8765`, line-delimited JSON. Every mutation broadcasts a fresh
book snapshot to all connected clients.

```jsonc
// client -> server
{"action": "submit", "id": "o1", "side": "BUY", "price": 100, "quantity": 10, "type": "LIMIT"}
{"action": "cancel", "id": "o1"}
{"action": "snapshot"}

// server -> client
{"type": "ack", "order_id": "o1", "trades": [...], "resting": true}
{"type": "book", "bids": [[100, 10]], "asks": [[101, 5]], "best_bid": 100, ...}
{"type": "error", "message": "..."}
```

One asyncio task per connection, all sharing one book. The book is synchronous
and there is no await inside the matching path, so `submit` and `cancel` are
effectively atomic under asyncio's single-threaded scheduling — no locking
needed, and none should be added without auditing that path first.

## Layout

```
engine/orders.py    Order, Trade, Side, OrderType
engine/fenwick.py   Fenwick tree over the price grid
engine/book.py      OrderBook: matching, cancellation, liquidity
gateway.py          asyncio WebSocket server
tests/test_book.py
tests/test_gateway.py
benchmark.py
```

## Todo

- Multi-symbol books
- Event journal and snapshot/restore
- Stop and iceberg order types
