"""Request-local canonical capture dictionaries shared by report consumers."""
from codex_usage.allowance_windows import seconds


class CaptureDirectory:
    def __init__(self, points, provenance):
        self.ordered = sorted(dict.fromkeys(points), key=lambda p: (seconds(p), p.limit_id, p.slot))
        self.positions = {point: index for index, point in enumerate(self.ordered)}
        self.captures = [dict(p.to_dict(), provenance=", ".join(sorted(provenance[p])))
                         for p in self.ordered]

    def exported(self, point):
        return self.captures[self.positions[point]]
