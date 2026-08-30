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
real exchange. Unfilled remainder rests.

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
python -m pytest tests/ -q      # 26 tests
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

## Layout

```
engine/orders.py    Order, Trade, Side
engine/fenwick.py   Fenwick tree over the price grid
engine/book.py      OrderBook: matching, cancellation, liquidity
tests/test_book.py
benchmark.py
```

## Todo

- Market, IOC and FOK order types
- WebSocket gateway for L2 market data
- Multi-symbol books
- Event journal and snapshot/restore
