"""Compact fixed-gutter numeric ticks; exact values remain inspectable."""
import html
from decimal import Decimal


def compact_decimal(value, *, signed=False):
    """Bound tick text, not underlying values or plot coordinates."""
    value = Decimal(str(value))
    if not value:
        return "0"
    prefix = "+" if signed and value > 0 else ""
    def compact(text):
        coefficient, separator, exponent = text.lower().partition("e")
        if "." in coefficient:
            coefficient = coefficient.rstrip("0").rstrip(".")
        return prefix + coefficient + ("e" + str(int(exponent)) if separator else "")
    exact = compact(format(value, "f"))
    if len(exact) <= 8:
        return exact
    for precision in range(8, 0, -1):
        label = compact(format(value, f".{precision}g"))
        if len(label) <= 8:
            return label
    raise ValueError("Number outside supported axis range")


def numeric_axis(values, *, signed=False, actual=None, unit="credits"):
    labels = [compact_decimal(value, signed=signed) for value in values]
    return "".join(f'<span title="{html.escape(format(Decimal(str(exact)), "f"))} {html.escape(unit)}">{label}</span>'
        for label, exact in zip(labels, actual if actual is not None else values))
