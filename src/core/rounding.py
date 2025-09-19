def round_lot(qty: float) -> int:
    return int(qty) if qty >= 0 else 0

def clamp_order_value(qty: int, price: float, max_value: int) -> int:
    if max_value <= 0:
        return qty
    if qty * price <= max_value:
        return qty
    return max(int(max_value // price), 0)
