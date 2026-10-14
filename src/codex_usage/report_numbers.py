"""Bounded display precision without changing accounting or source values."""
from collections.abc import Sequence
from decimal import Decimal, localcontext

MAX_SUMMARY_DECIMALS = 6
MAX_ECONOMICS_USD_DECIMALS = 9


def format_int(value: int) -> str:
    return f"{value:,}"


def adaptive_usd(values: Sequence[float | None]) -> tuple[str, ...]:
    """Distinguish related USD values within a bounded precision, then collapse noise."""
    numbers = tuple(None if value is None else Decimal(str(value)) for value in values)
    unique_values = tuple(dict.fromkeys(value for value in numbers if value is not None))
    places_by_value = {value: 4 for value in unique_values}
    max_precision_labels = {
        value: _fixed_usd(value, MAX_ECONOMICS_USD_DECIMALS)
        for value in unique_values
    }

    while True:
        labels_by_value = {
            value: _fixed_usd(value, places_by_value[value]) for value in unique_values
        }
        values_by_label: dict[str, dict[str, set[Decimal]]] = {}
        values_to_increase: set[Decimal] = set()
        for value in unique_values:
            label = labels_by_value[value]
            max_label = max_precision_labels[value]
            values_by_label.setdefault(label, {}).setdefault(max_label, set()).add(value)
            rounded = Decimal(label[1:].replace(",", ""))
            if (
                value != 0
                and rounded == 0
                and places_by_value[value] < MAX_ECONOMICS_USD_DECIMALS
            ):
                values_to_increase.add(value)

        for distinct_values in values_by_label.values():
            if len(distinct_values) > 1:
                for related_values in distinct_values.values():
                    values_to_increase.update(
                        value
                        for value in related_values
                        if value != 0
                        and places_by_value[value] < MAX_ECONOMICS_USD_DECIMALS
                    )

        if not values_to_increase:
            break
        for value in values_to_increase:
            places_by_value[value] += 1

    labels = []
    for value in numbers:
        if value is None:
            labels.append("Unavailable")
            continue
        label = labels_by_value[value]
        rounded = Decimal(label[1:].replace(",", ""))
        labels.append(_bounded_usd(value) if value != 0 and rounded == 0 else label)
    return tuple(labels)


def compact_token_count(value: float | int | None) -> str:
    if value is None:
        return "Unavailable"
    number = Decimal(str(value))
    for power, suffix in ((9, "B"), (6, "M"), (3, "K")):
        if abs(number) >= Decimal(10) ** power:
            return decimal_text(number / Decimal(10) ** power, places=2, trim=True) + suffix
    return decimal_text(number, places=2, trim=True)


def _fixed_usd(value: Decimal | None, places: int) -> str:
    if value is None:
        return "Unavailable"
    if value == 0:
        value = Decimal(0)
    amount = format(value, f",.{places}f")
    whole, fraction = amount.split(".")
    fraction = fraction.rstrip("0")
    fraction += "0" * max(0, 4 - len(fraction))
    return f"${whole}.{fraction}"


def _bounded_usd(value: Decimal | None) -> str:
    if value is None:
        return "Unavailable"
    label = _fixed_usd(value, MAX_ECONOMICS_USD_DECIMALS)
    rounded = Decimal(format(value, f".{MAX_ECONOMICS_USD_DECIMALS}f"))
    if value > 0 and rounded == 0:
        threshold = Decimal(1).scaleb(-MAX_ECONOMICS_USD_DECIMALS)
        return f"<${format(threshold, f'.{MAX_ECONOMICS_USD_DECIMALS}f')}"
    if value < 0 and rounded == 0:
        threshold = Decimal(1).scaleb(-MAX_ECONOMICS_USD_DECIMALS)
        return f">-${format(threshold, f'.{MAX_ECONOMICS_USD_DECIMALS}f')}"
    return label


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
