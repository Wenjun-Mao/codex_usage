"""Readable display dates without discarding captured clock offsets."""
from datetime import date, datetime


def calendar_label(moment: date) -> str:
    day = f'{moment:%b} {moment.day}, {moment.year}'
    if not isinstance(moment, datetime):
        return day
    offset = moment.strftime('%z')
    zone = ''
    if offset:
        numeric = f'{offset[:3]}:{offset[3:5]}'
        if len(offset) > 5:
            numeric += f':{offset[5:]}'
        zone = f' (UTC{numeric})'
    return f'{day} at {moment:%H:%M}{zone}'
