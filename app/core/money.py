"""Money is integer paise (hard rule 3). Helpers never accept or return floats."""

PAISE_PER_RUPEE = 100


def require_paise(value: object, *, allow_zero: bool = True) -> int:
    """The value itself if it is an int amount of paise; raises otherwise (bool/float rejected)."""
    if type(value) is not int:
        raise TypeError(f"money must be integer paise, got {type(value).__name__}")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"invalid amount: {value} paise")
    return value


def percent_of(amount_paise: int, percent: int) -> int:
    """floor(amount * percent / 100) in integer arithmetic: never rounds a refund up."""
    require_paise(amount_paise)
    if type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError("percent must be an integer from 0 to 100")
    return amount_paise * percent // 100


def format_inr(amount_paise: int) -> str:
    """₹1,234.50 style, Indian digit grouping (12,34,567.00)."""
    require_paise(amount_paise)
    rupees, paise = divmod(amount_paise, PAISE_PER_RUPEE)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"₹{digits}.{paise:02d}"
