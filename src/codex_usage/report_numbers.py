"""Bounded display precision without changing accounting or source values."""
from decimal import Decimal, localcontext

MAX_SUMMARY_DECIMALS = 6


def decimal_text(value, *, places=2, trim=False):
    number = Decimal(str(value))
    if not number:
        number = Decimal(0)
    threshold = Decimal(10) ** -MAX_SUMMARY_DECIMALS
    if number and abs(number) < threshold:
        return (">-" if number < 0 else "<") + format(threshold, "f")
    places = min(places, MAX_SUMMARY_DECIMALS)
    while number and places < MAX_SUMMARY_DECIMALS and abs(number) < Decimal(10) ** -places:
        places += 1
    with localcontext() as context:
        context.prec = max(40, len(number.as_tuple().digits) + places + 4)
        text = format(number, f",.{places}f")
    return text.rstrip("0").rstrip(".") if trim and "." in text else text


def estimated_credits(value):
    places = 0 if abs(value) >= 1000 else 2 if 0 < abs(value) < 1 else 1
    return decimal_text(value, places=places)


def summary_money(value):
    return "<$0.01" if 0 < value < .01 else "$" + decimal_text(value)


def percentage_text(value):
    number = Decimal(str(value))
    if 0 < number < Decimal(".01"):
        return "<0.01"
    if Decimal("99.99") < number < 100:
        return ">99.99"
    return decimal_text(number, trim=True)
