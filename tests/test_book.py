import random

import pytest

from engine import Fenwick, Order, OrderBook, Side


@pytest.fixture
def book():
    return OrderBook("TEST", 1, 10_000)


def test_empty_book(book):
    assert book.best_bid is None and book.best_ask is None and book.spread is None


def test_non_crossing_orders_rest(book):
    book.submit(Order("b1", Side.BUY, 99, 10))
    book.submit(Order("a1", Side.SELL, 101, 10))
    assert (book.best_bid, book.best_ask, book.spread) == (99, 101, 2)
    assert book.open_order_count == 2


def test_best_prices(book):
    for p in (98, 100, 99):
        book.submit(Order(f"b{p}", Side.BUY, p, 5))
    for p in (105, 103, 104):
        book.submit(Order(f"a{p}", Side.SELL, p, 5))
    assert (book.best_bid, book.best_ask) == (100, 103)


def test_exact_fill(book):
    book.submit(Order("a1", Side.SELL, 100, 10))
    trades = book.submit(Order("b1", Side.BUY, 100, 10))
    assert len(trades) == 1 and trades[0].quantity == 10
    assert book.open_order_count == 0


def test_partial_fill_rests_remainder(book):
    book.submit(Order("a1", Side.SELL, 100, 10))
    trades = book.submit(Order("b1", Side.BUY, 100, 25))
    assert sum(t.quantity for t in trades) == 10
    assert book.depth(Side.BUY, 100) == 15


def test_walks_multiple_levels(book):
    for i, p in enumerate((100, 101, 102)):
        book.submit(Order(f"a{i}", Side.SELL, p, 10))
    trades = book.submit(Order("b1", Side.BUY, 102, 25))
    assert [(t.price, t.quantity) for t in trades] == [(100, 10), (101, 10), (102, 5)]


def test_no_match_without_cross(book):
    book.submit(Order("a1", Side.SELL, 105, 10))
    assert book.submit(Order("b1", Side.BUY, 100, 10)) == []
    assert book.open_order_count == 2


def test_executes_at_resting_price(book):
    book.submit(Order("a1", Side.SELL, 100, 10))
    assert book.submit(Order("b1", Side.BUY, 110, 10))[0].price == 100


def test_fifo_within_level(book):
    book.submit(Order("first", Side.SELL, 100, 10))
    book.submit(Order("second", Side.SELL, 100, 10))
    trades = book.submit(Order("buy", Side.BUY, 100, 15))
    assert [t.sell_order_id for t in trades] == ["first", "second"]
    assert trades[1].quantity == 5


def test_price_beats_time(book):
    book.submit(Order("early_expensive", Side.SELL, 102, 10))
    book.submit(Order("late_cheap", Side.SELL, 100, 10))
    assert book.submit(Order("buy", Side.BUY, 102, 10))[0].sell_order_id == "late_cheap"


def test_cancel(book):
    book.submit(Order("a1", Side.SELL, 100, 10))
    assert book.cancel("a1") is True
    assert book.best_ask is None and book.open_order_count == 0


def test_cancel_unknown_order(book):
    assert book.cancel("nope") is False


def test_cancel_mid_queue_preserves_order(book):
    for oid in ("o1", "o2", "o3"):
        book.submit(Order(oid, Side.SELL, 100, 10))
    book.cancel("o2")
    trades = book.submit(Order("buy", Side.BUY, 100, 20))
    assert [t.sell_order_id for t in trades] == ["o1", "o3"]


def test_cancel_is_idempotent(book):
    book.submit(Order("a1", Side.SELL, 100, 10))
    assert book.cancel("a1") is True
    assert book.cancel("a1") is False


def test_filled_order_not_cancellable(book):
    book.submit(Order("a1", Side.SELL, 100, 10))
    book.submit(Order("b1", Side.BUY, 100, 10))
    assert book.cancel("a1") is False


def test_duplicate_order_id(book):
    book.submit(Order("dup", Side.SELL, 100, 10))
    with pytest.raises(ValueError):
        book.submit(Order("dup", Side.SELL, 101, 10))


def test_non_positive_quantity(book):
    with pytest.raises(ValueError):
        book.submit(Order("bad", Side.BUY, 100, 0))


def test_fenwick_ranges():
    ft = Fenwick(100, 200)
    ft.add(105, 50)
    ft.add(110, 30)
    assert (ft.range_sum(105, 105), ft.range_sum(105, 110), ft.total()) == (50, 80, 80)
    assert ft.range_sum(111, 200) == 0


def test_fenwick_rejects_off_grid_price():
    with pytest.raises(ValueError):
        Fenwick(100, 200, tick=5).add(102, 10)


def test_fenwick_rejects_out_of_range_price():
    with pytest.raises(ValueError):
        Fenwick(100, 200).add(500, 10)


def test_fenwick_matches_brute_force():
    ft, ref = Fenwick(0, 499), {}
    random.seed(7)
    for _ in range(2000):
        p, d = random.randint(0, 499), random.randint(-15, 40)
        ft.add(p, d)
        ref[p] = ref.get(p, 0) + d
    for _ in range(500):
        lo, hi = sorted((random.randint(0, 499), random.randint(0, 499)))
        assert ft.range_sum(lo, hi) == sum(v for k, v in ref.items() if lo <= k <= hi)


def test_liquidity_tracks_resting_orders(book):
    book.submit(Order("a1", Side.SELL, 100, 50))
    book.submit(Order("a2", Side.SELL, 102, 30))
    assert book.liquidity_between(Side.SELL, 100, 102) == 80
    assert book.liquidity_between(Side.SELL, 101, 102) == 30


def test_liquidity_drops_on_fill(book):
    book.submit(Order("a1", Side.SELL, 100, 50))
    book.submit(Order("b1", Side.BUY, 100, 20))
    assert book.total_liquidity(Side.SELL) == 30


def test_liquidity_drops_on_cancel(book):
    book.submit(Order("a1", Side.SELL, 100, 50))
    book.cancel("a1")
    assert book.total_liquidity(Side.SELL) == 0


def test_liquidity_invariant_under_random_workload(book):
    """Fenwick index must always agree with the sum of the price levels."""
    random.seed(11)
    live = []
    for i in range(1500):
        if random.random() < 0.6 or not live:
            oid = f"o{i}"
            book.submit(Order(oid, random.choice(list(Side)),
                              random.randint(90, 110), random.randint(1, 20)))
            live.append(oid)
        else:
            oid = random.choice(live)
            book.cancel(oid)
            live.remove(oid)

        if i % 100 == 0:
            for side in Side:
                assert book.total_liquidity(side) == sum(
                    book.depth(side, p) for p in range(90, 111))


def test_market_never_crosses(book):
    random.seed(3)
    for i in range(800):
        book.submit(Order(f"x{i}", random.choice(list(Side)),
                          random.randint(95, 105), random.randint(1, 10)))
        if book.best_bid is not None and book.best_ask is not None:
            assert book.best_bid < book.best_ask
