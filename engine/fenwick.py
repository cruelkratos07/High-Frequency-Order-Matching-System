class Fenwick:
    """Prefix sums over a fixed price grid in O(log N).

    A segment tree would also work but costs more memory and code for range
    min/max and lazy updates this never needs.
    """

    def __init__(self, min_price, max_price, tick=1):
        self.min_price, self.max_price, self.tick = min_price, max_price, tick
        self.size = (max_price - min_price) // tick + 1
        self._t = [0] * (self.size + 1)

    def _idx(self, price):
        if not self.min_price <= price <= self.max_price:
            raise ValueError(f"price {price} outside [{self.min_price}, {self.max_price}]")
        if (price - self.min_price) % self.tick:
            raise ValueError(f"price {price} off the {self.tick}-tick grid")
        return (price - self.min_price) // self.tick + 1  # 1-indexed: i & -i stalls at 0

    def add(self, price, delta):
        i = self._idx(price)
        while i <= self.size:
            self._t[i] += delta
            i += i & -i

    def prefix_sum(self, price):
        i, total = self._idx(price), 0
        while i:
            total += self._t[i]
            i -= i & -i
        return total

    def range_sum(self, low, high):
        if low > high:
            return 0
        upper = self.prefix_sum(high)
        return upper if low == self.min_price else upper - self.prefix_sum(low - self.tick)

    def total(self):
        return self.prefix_sum(self.max_price)
