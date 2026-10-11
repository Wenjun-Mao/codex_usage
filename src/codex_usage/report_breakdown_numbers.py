"""Human-unit labels; stored values and geometry remain unrounded."""
import html
from decimal import Decimal, localcontext, ROUND_CEILING


def compact_decimal(value, *, signed=False, unit="credits"):
    value = Decimal(str(value))
    if not value:
        return "$0" if unit == "cost" else "0"
    prefix = "+" if signed and value > 0 else ""
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + 4)
        scale, suffix = Decimal(1), ""
        for power, name in ((12, "T"), (9, "B"), (6, "M"), (3, "K")):
            if abs(value) >= Decimal(10) ** power:
                scale, suffix = Decimal(10) ** power, " " + name
                break
        scaled = value / scale
        places = 2
        while scaled and abs(scaled) < Decimal(10) ** -places:
            places += 1
        text = format(scaled, f".{places}f").rstrip("0").rstrip(".")
        return ("$" if unit == "cost" else "") + prefix + (text or "0") + suffix


def tick_ceiling(value):
    value = Decimal(str(value))
    if value <= 0:
        return 1.0
    with localcontext() as context:
        context.prec = 40
        step = Decimal(10) ** value.adjusted() / 2
        return float((value / step).to_integral_value(rounding=ROUND_CEILING) * step)


def numeric_axis(values, *, signed=False, actual=None, unit="credits"):
    numbers = [Decimal(str(v)) for v in values]
    labels = [compact_decimal(v, signed=signed, unit=unit) for v in numbers]
    scale = None
    if any(len(label) > 12 for label in labels):
        scale = Decimal(10) ** max(abs(v) for v in numbers).adjusted()
        with localcontext() as context:
            context.prec = 40
            labels = [compact_decimal(v / scale, signed=signed, unit=unit) for v in numbers]
    notice = f'<small class="ub-scale">× {format(scale, "f")} {unit}</small>' if scale else ""
    return notice + "".join(f'<span title="{html.escape(format(Decimal(str(exact)), "f"))} {html.escape(unit)}">{label}</span>'
        for label, exact in zip(labels, actual if actual is not None else values))
