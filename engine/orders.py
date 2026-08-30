from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"    # rest whatever doesn't fill
    MARKET = "MARKET"  # take any price, cancel what doesn't fill
    IOC = "IOC"        # immediate-or-cancel: fill now, cancel the rest
    FOK = "FOK"        # fill-or-kill: fill completely or do nothing


@dataclass
class Order:
    order_id: str
    side: Side
    price: int | None  # integer ticks; None for MARKET
    quantity: int
    type: OrderType = OrderType.LIMIT

    def __post_init__(self):
        if self.type is OrderType.MARKET:
            self.price = None
        elif self.price is None:
            raise ValueError(f"{self.type.value} orders need a price")


@dataclass(frozen=True)
class Trade:
    price: int
    quantity: int
    buy_order_id: str
    sell_order_id: str

    def __str__(self):
        return (f"TRADE {self.quantity} @ {self.price} "
                f"(buy={self.buy_order_id} sell={self.sell_order_id})")
