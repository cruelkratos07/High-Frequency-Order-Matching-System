import random

import pytest

from engine import Fenwick, Order, OrderBook, OrderType, Side


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


# ---------- order types ----------

@pytest.fixture
def loaded(book):
    """Asks resting at 100, 101, 102 with 10 each."""
    for i, p in enumerate((100, 101, 102)):
        book.submit(Order(f"s{i}", Side.SELL, p, 10))
    return book


def test_market_order_walks_the_book(loaded):
    trades = loaded.submit(Order("m", Side.BUY, None, 25, OrderType.MARKET))
    assert [(t.price, t.quantity) for t in trades] == [(100, 10), (101, 10), (102, 5)]


def test_market_order_ignores_price_argument(loaded):
    """A price passed to a MARKET order is discarded, not used as a limit."""
    order = Order("m", Side.BUY, 100, 25, OrderType.MARKET)
    assert order.price is None
    assert sum(t.quantity for t in loaded.submit(order)) == 25


def test_market_order_discards_unfilled_remainder(loaded):
    trades = loaded.submit(Order("m", Side.BUY, None, 100, OrderType.MARKET))
    assert sum(t.quantity for t in trades) == 30
    assert loaded.open_order_count == 0
    assert loaded.best_bid is None


def test_market_order_on_empty_book_does_nothing(book):
    assert book.submit(Order("m", Side.BUY, None, 10, OrderType.MARKET)) == []
    assert book.open_order_count == 0


def test_ioc_fills_what_it_can_and_cancels_the_rest(loaded):
    trades = loaded.submit(Order("i", Side.BUY, 101, 25, OrderType.IOC))
    assert sum(t.quantity for t in trades) == 20
    assert loaded.open_order_count == 1      # only the untouched 102 level
    assert loaded.best_bid is None


def test_ioc_respects_its_limit_price(loaded):
    trades = loaded.submit(Order("i", Side.BUY, 100, 30, OrderType.IOC))
    assert sum(t.quantity for t in trades) == 10


def test_fok_rejected_leaves_book_untouched(loaded):
    before = loaded.snapshot()
    assert loaded.submit(Order("f", Side.BUY, 101, 25, OrderType.FOK)) == []
    assert loaded.snapshot() == before
    assert loaded.open_order_count == 3


def test_fok_fills_when_exactly_enough_liquidity(loaded):
    trades = loaded.submit(Order("f", Side.BUY, 101, 20, OrderType.FOK))
    assert sum(t.quantity for t in trades) == 20
    assert loaded.open_order_count == 1


def test_fok_never_rests(loaded):
    loaded.submit(Order("f", Side.BUY, 102, 30, OrderType.FOK))
    assert loaded.best_bid is None


def test_rejected_fok_id_is_reusable(loaded):
    """A rejected order was never registered, so its id is still free."""
    assert loaded.submit(Order("f", Side.BUY, 101, 25, OrderType.FOK)) == []
    assert sum(t.quantity for t in loaded.submit(
        Order("f", Side.BUY, 101, 20, OrderType.FOK))) == 20


def test_available_against_matches_actual_fill(loaded):
    order = Order("probe", Side.BUY, 101, 999, OrderType.IOC)
    predicted = loaded.available_against(order)
    assert sum(t.quantity for t in loaded.submit(order)) == predicted


def test_limit_order_still_rests(loaded):
    loaded.submit(Order("l", Side.BUY, 99, 10))
    assert loaded.best_bid == 99


def test_non_market_order_requires_a_price():
    with pytest.raises(ValueError):
        Order("bad", Side.BUY, None, 10, OrderType.IOC)
