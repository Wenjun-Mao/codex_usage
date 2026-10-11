"""Human-unit labels; stored values and geometry remain unrounded."""
import html
from decimal import Decimal, localcontext, ROUND_CEILING
from codex_usage.report_numbers import MAX_SUMMARY_DECIMALS


def compact_decimal(value, *, signed=False, unit="credits", trim=True):
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
        threshold = Decimal(10) ** -MAX_SUMMARY_DECIMALS
        if abs(scaled) < threshold:
            relation = ">-" if scaled < 0 else "<"
            return relation + ("$" if unit == "cost" else "") + format(threshold, "f") + suffix
        places = 2
        while scaled and places < MAX_SUMMARY_DECIMALS and abs(scaled) < Decimal(10) ** -places:
            places += 1
        text = format(scaled, f".{places}f")
        if trim:
            text = text.rstrip("0").rstrip(".")
        return ("$" if unit == "cost" else "") + prefix + (text or "0") + suffix


def metric_label(value, unit):
    text = compact_decimal(value, unit=unit, trim=unit != "cost")
    return text if unit == "cost" else text + (" tokens" if unit == "tokens" else " credits")


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
    if any(len(label) > 12 for label in labels) or len(set(labels)) < len(set(numbers)):
        scale = Decimal(10) ** max(abs(v) for v in numbers).adjusted()
        with localcontext() as context:
            context.prec = 40
            labels = [compact_decimal(v / scale, signed=signed, unit=unit) for v in numbers]
    scale_label = (format(scale, "f") if -6 <= scale.adjusted() <= 12 else
        f'10<sup>{scale.adjusted()}</sup>') if scale else ""
    notice = f'<small class="ub-scale">× {scale_label} {unit}</small>' if scale else ""
    return notice + "".join(f'<span title="{html.escape(format(Decimal(str(exact)), "f"))} {html.escape(unit)}">{label}</span>'
        for label, exact in zip(labels, actual if actual is not None else values))
