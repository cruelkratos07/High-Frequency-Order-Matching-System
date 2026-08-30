from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    order_id: str
    side: Side
    price: int  # integer ticks - float prices break cross detection
    quantity: int


@dataclass(frozen=True)
class Trade:
    price: int
    quantity: int
    buy_order_id: str
    sell_order_id: str

    def __str__(self):
        return (f"TRADE {self.quantity} @ {self.price} "
                f"(buy={self.buy_order_id} sell={self.sell_order_id})")
