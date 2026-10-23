"""Compact capture layouts, retaining dictionary order and JSON scalar identity."""
import json
from functools import lru_cache


@lru_cache(maxsize=32)
def _layout(keys, types):
    if any(kind not in (str, int, float, bool, type(None)) for kind in types):
        return None
    order = tuple(sorted(range(len(keys)), key=keys.__getitem__))
    schema = (tuple(keys[i] for i in order), tuple(types[i] for i in order))
    return schema, order, tuple(i for i, kind in enumerate(types) if kind is float)


def point_key(point):
    if not isinstance(point, dict):
        raise ValueError("Invalid allowance capture")
    return _key(tuple(point), tuple(point.values()), point)


def _key(keys, values, point):
    types = tuple(map(type, values))
    layout = _layout(keys, types)
    if layout is not None:
        schema, order, floats = layout
        if floats:
            values = list(values)
            for i in floats:
                values[i] = repr(values[i])
        return schema, tuple(values[i] for i in order)
    return json.dumps(point, sort_keys=True, separators=(",", ":"))


def encode_captures(captures):
    schemas, positions, rows, identities = [], {}, [], set()
    for point in captures:
        if not isinstance(point, dict):
            raise ValueError("Invalid allowance capture")
        fields, values = tuple(point), tuple(point.values())
        key = _key(fields, values, point)
        if key in identities:
            raise ValueError("Duplicate allowance capture")
        identities.add(key)
        if fields not in positions:
            if any(type(field) is not str for field in fields):
                raise ValueError("Invalid allowance capture field")
            positions[fields] = len(schemas)
            schemas.append(fields)
        rows.append([positions[fields], *values])
    return schemas, rows


def decode_captures(schemas, rows):
    if not isinstance(schemas, list) or not isinstance(rows, list):
        raise ValueError("Invalid allowance capture table")
    for fields in schemas:
        if (not isinstance(fields, list) or any(type(field) is not str for field in fields)
                or len(fields) != len(set(fields))):
            raise ValueError("Invalid allowance capture layout")
    schemas = [tuple(fields) for fields in schemas]
    captures, identities = [], set()
    for row in rows:
        if (not isinstance(row, list) or not row or type(row[0]) is not int
                or not 0 <= row[0] < len(schemas)):
            raise ValueError("Invalid allowance capture layout reference")
        fields = schemas[row[0]]
        if len(row) != len(fields) + 1:
            raise ValueError("Invalid allowance capture row")
        values = tuple(row[1:])
        point = dict(zip(fields, values))
        key = _key(fields, values, point)
        if key in identities:
            raise ValueError("Duplicate allowance capture")
        identities.add(key)
        captures.append(point)
    return captures
