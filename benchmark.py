"""Latency percentiles for the hot paths.

Percentiles rather than means: a mean hides tail behaviour, and the tail is
what you hit during a burst, which is exactly when the book is busiest.
perf_counter_ns because time.time() is wall-clock and can jump backwards.
"""

import random
import statistics
import time

from engine import Order, OrderBook, Side


def percentiles(ns):
    s = sorted(ns)
    pct = lambda p: s[min(int(len(s) * p), len(s) - 1)] / 1000
    return {"n": len(s), "p50": pct(.50), "p90": pct(.90), "p99": pct(.99),
            "p999": pct(.999), "max": s[-1] / 1000, "mean": statistics.mean(s) / 1000}


def report(name, ns):
    p = percentiles(ns)
    print(f"{name:<28} n={p['n']:>7,}  p50={p['p50']:>7.2f}us  p90={p['p90']:>7.2f}us  "
          f"p99={p['p99']:>7.2f}us  p99.9={p['p999']:>8.2f}us  max={p['max']:>9.2f}us")


def timed(fn, n):
    out = []
    for i in range(n):
        args = fn(i)
        t0 = time.perf_counter_ns()
        args()
        out.append(time.perf_counter_ns() - t0)
    return out


def bench_rest(n=50_000):
    book = OrderBook(min_price=1, max_price=200_000)
    return timed(lambda i: (lambda: book.submit(
        Order(f"r{i}", Side.SELL, random.randint(100_000, 100_500), random.randint(1, 100)))), n)


def bench_match(n=50_000):
    book = OrderBook(min_price=1, max_price=200_000)
    for i in range(n):
        book.submit(Order(f"a{i}", Side.SELL, random.randint(100_000, 100_200), 10))
    return timed(lambda i: (lambda: book.submit(
        Order(f"b{i}", Side.BUY, 100_200, random.randint(1, 20)))), n // 2)


def bench_cancel(n=50_000):
    book = OrderBook(min_price=1, max_price=200_000)
    ids = [f"c{i}" for i in range(n)]
    for oid in ids:
        book.submit(Order(oid, Side.SELL, random.randint(100_000, 100_500), 10))
    random.shuffle(ids)
    return timed(lambda i: (lambda: book.cancel(ids[i])), n)


def _populated():
    book = OrderBook(min_price=1, max_price=200_000)
    for i in range(50_000):
        book.submit(Order(f"q{i}", Side.SELL, random.randint(100_000, 100_500), 10))
    return book


def bench_fenwick(n=50_000):
    book = _populated()
    return timed(lambda i: (lambda lo=random.randint(100_000, 100_400):
                            book.liquidity_between(Side.SELL, lo, lo + 100)), n)


def bench_scan(n=20_000):
    book = _populated()
    return timed(lambda i: (lambda lo=random.randint(100_000, 100_400):
                            sum(book.depth(Side.SELL, p) for p in range(lo, lo + 101))), n)


def scaling():
    random.seed(1)
    book = OrderBook(min_price=1, max_price=200_000)
    for i in range(60_000):
        book.submit(Order(f"s{i}", Side.SELL, random.randint(100_000, 101_000), 10))

    print(f"\n{'levels':>8} | {'Fenwick':>10} | {'scan':>10} | {'speedup':>8}")
    print("-" * 44)
    for w in (10, 50, 100, 250, 500, 1000):
        lo, hi = 100_000, 100_000 + w
        t0 = time.perf_counter()
        for _ in range(3000):
            book.liquidity_between(Side.SELL, lo, hi)
        fen = (time.perf_counter() - t0) / 3000 * 1e6

        t0 = time.perf_counter()
        for _ in range(500):
            sum(book.depth(Side.SELL, p) for p in range(lo, hi + 1))
        scan = (time.perf_counter() - t0) / 500 * 1e6
        print(f"{w:>8} | {fen:>8.2f}us | {scan:>8.2f}us | {scan / fen:>7.1f}x")


if __name__ == "__main__":
    random.seed(42)
    print("=" * 108)
    print("LATENCY  (CPython, single-threaded)")
    print("=" * 108)
    report("submit / rest", bench_rest())
    report("submit / match", bench_match())
    report("cancel", bench_cancel())
    report("liquidity query (Fenwick)", bench_fenwick())
    report("liquidity query (scan)", bench_scan())
    scaling()
