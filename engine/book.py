from collections import OrderedDict

from sortedcontainers import SortedDict

from .fenwick import Fenwick
from .orders import Order, OrderType, Side, Trade


class Level(OrderedDict):
    """order_id -> Order at one price, with a running quantity total.

    OrderedDict is a doubly linked list underneath: insertion order gives FIFO
    within the level, delete-by-key gives O(1) cancellation at any depth.
    """
    total = 0


class OrderBook:
    """Price-time priority limit order book.

    Layout: SortedDict[price] -> Level.

    SortedDict keeps price levels ordered, so peekitem(0) is the best price.
    Bids are keyed by -price so index 0 is the best on both sides.
    """

    def __init__(self, symbol="TEST", min_price=1, max_price=1_000_000):
        self.symbol = symbol
        self._bids = SortedDict()
        self._asks = SortedDict()
        self._orders = {}
        self._liquidity = {
            Side.BUY: Fenwick(min_price, max_price),
            Side.SELL: Fenwick(min_price, max_price),
        }

    def _book(self, side):
        return self._bids if side is Side.BUY else self._asks

    @staticmethod
    def _key(side, price):
        return -price if side is Side.BUY else price

    @property
    def best_bid(self):
        return -self._bids.peekitem(0)[0] if self._bids else None

    @property
    def best_ask(self):
        return self._asks.peekitem(0)[0] if self._asks else None

    @property
    def spread(self):
        return self.best_ask - self.best_bid if self._bids and self._asks else None

    @property
    def open_order_count(self):
        return len(self._orders)

    def available_against(self, order):
        """Quantity this order could fill against the book right now.

        Uses the liquidity index rather than walking levels, so the FOK
        feasibility check below is O(log N) instead of O(levels).
        """
        other = Side.SELL if order.side is Side.BUY else Side.BUY
        index = self._liquidity[other]
        if order.price is None:
            return index.total()
        if order.side is Side.BUY:
            return index.range_sum(index.min_price, order.price)
        return index.range_sum(order.price, index.max_price)

    def submit(self, order):
        """Match against the opposite side, then handle the remainder by type.

        LIMIT rests it, MARKET and IOC discard it, FOK never gets here unless
        the whole quantity can fill.
        """
        if order.order_id in self._orders:
            raise ValueError(f"duplicate order_id: {order.order_id}")
        if order.quantity <= 0:
            raise ValueError("quantity must be positive")

        # All-or-nothing: check before touching the book, so a rejected FOK
        # leaves no trace.
        if order.type is OrderType.FOK and self.available_against(order) < order.quantity:
            return []

        trades = []
        book = self._book(Side.SELL if order.side is Side.BUY else Side.BUY)
        if order.price is None:
            crosses = lambda p: True          # MARKET takes any price
        elif order.side is Side.BUY:
            crosses = lambda p: order.price >= p
        else:
            crosses = lambda p: order.price <= p

        while order.quantity and book:
            key, level = book.peekitem(0)
            price = abs(key)
            if not crosses(price):
                break

            while order.quantity and level:
                resting = next(iter(level.values()))
                fill = min(order.quantity, resting.quantity)
                order.quantity -= fill
                resting.quantity -= fill
                level.total -= fill
                self._liquidity[resting.side].add(price, -fill)

                # trades print at the resting price, so improvement goes to the aggressor
                buy, sell = (order, resting) if order.side is Side.BUY else (resting, order)
                trades.append(Trade(price, fill, buy.order_id, sell.order_id))

                if not resting.quantity:
                    del level[resting.order_id]
                    del self._orders[resting.order_id]

            if not level:
                del book[key]

        if order.quantity and order.type is OrderType.LIMIT:
            self._rest(order)
        return trades

    def _rest(self, order):
        key = self._key(order.side, order.price)
        level = self._book(order.side).setdefault(key, Level())
        level[order.order_id] = order
        level.total += order.quantity
        self._orders[order.order_id] = order
        self._liquidity[order.side].add(order.price, order.quantity)

    def cancel(self, order_id):
        """Remove a resting order. False if it was never on the book."""
        order = self._orders.pop(order_id, None)
        if order is None:
            return False
        book, key = self._book(order.side), self._key(order.side, order.price)
        book[key].total -= order.quantity
        del book[key][order_id]
        if not book[key]:
            del book[key]
        self._liquidity[order.side].add(order.price, -order.quantity)
        return True

    def depth(self, side, price):
        level = self._book(side).get(self._key(side, price))
        return level.total if level else 0

    def liquidity_between(self, side, low, high):
        """Resting quantity across a price range, without walking the levels."""
        return self._liquidity[side].range_sum(low, high)

    def total_liquidity(self, side):
        return self._liquidity[side].total()

    def snapshot(self, levels=5):
        top = lambda b: [(abs(k), v.total) for k, v in list(b.items())[:levels]]
        return {"bids": top(self._bids), "asks": top(self._asks)}
