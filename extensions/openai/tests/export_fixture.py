"""Export the probe's own fixtures for local bridge checks, not host acceptance."""

import json

from probe.data import synthetic_usage


if __name__ == "__main__":
    print(json.dumps({
        f"{period}:{project}": synthetic_usage(period, project)
        for period in ("today", "yesterday", "7d", "30d")
        for project in ("all", "demo-a", "demo-b")
    }))
