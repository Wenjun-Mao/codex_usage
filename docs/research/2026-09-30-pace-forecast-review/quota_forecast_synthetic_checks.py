"""Standalone SYNTHETIC checks for quota pace review; standard library only.

No private data, network calls, extension imports, or product implementation.
Times are hours and quota changes are percentage points.
Source pin reviewed: 7bebe7f46b50204834a18717b2d6d731a6cd27ca
Proposal pin reviewed: 73a887d8efd32e0c0cb6105fe4d5221ffd46f19a
Run: python quota_forecast_synthetic_checks.py
"""
from collections import defaultdict
from math import exp, floor, isfinite, log, sqrt
from statistics import median

def validate(points):
    if len(points) < 2:
        raise ValueError("Need at least two observations")
    if not all(isfinite(t) and isfinite(u) for t, u in points):
        raise ValueError("Nonfinite observation")
    if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise ValueError("Timestamps must increase strictly")

def level_slope(points, half_life=None):
    validate(points)
    if half_life is not None and half_life <= 0:
        raise ValueError("Half-life must be positive")
    end = points[-1][0]
    w = [1.0 if half_life is None else 2 ** ((t-end)/half_life)
         for t, u in points]
    total = sum(w)
    mt = sum(a*t for a, (t,u) in zip(w, points))/total
    mu = sum(a*u for a, (t,u) in zip(w, points))/total
    return (sum(a*(t-mt)*(u-mu) for a, (t,u) in zip(w, points)) /
            sum(a*(t-mt)**2 for a, (t,u) in zip(w, points)))

def interval_slope(points, half_life=None):
    """Integrate weights over each interval, assuming constant rate within it.

    With no decay the calculation telescopes exactly to net change / elapsed
    time: no assumption about within-interval timing is then needed.
    """
    validate(points)
    if half_life is not None and half_life <= 0:
        raise ValueError("Half-life must be positive")
    end = points[-1][0]
    numerator = denominator = 0.0
    for (a,u), (b,v) in zip(points, points[1:]):
        dt = b-a
        if half_life is None:
            exposure = dt
        else:
            k = log(2)/half_life
            exposure = (exp(k*(b-end))-exp(k*(a-end)))/k
        numerator += exposure*(v-u)/dt
        denominator += exposure
    return numerator/denominator

def median_buckets(points, minutes):
    if minutes <= 0:
        raise ValueError("Bucket width must be positive")
    grouped = defaultdict(list)
    for t,u in points:
        grouped[floor(t*60/minutes)].append((t,u))
    return [(median(t for t,u in rows), median(u for t,u in rows))
            for key,rows in sorted(grouped.items())]

def theil_sen(points):
    validate(points)
    return median((v-u)/(b-a) for i,(a,u) in enumerate(points)
                  for b,v in points[i+1:])

def induced_rate_weights(points, half_life):
    """Exact interval-rate weights implied by weighted regression on levels."""
    validate(points)
    end=points[-1][0]
    w=[2**((t-end)/half_life) for t,u in points]
    mt=sum(a*t for a,(t,u) in zip(w,points))/sum(w)
    d=sum(a*(t-mt)**2 for a,(t,u) in zip(w,points))
    c=[a*(t-mt)/d for a,(t,u) in zip(w,points)]
    return [(points[j][0]-points[j-1][0])*sum(c[j:])
            for j in range(1,len(points))]

def main():
    ts=[0,.25,.5,.75,1]
    cases={
        "steady":[80,82.5,85,87.5,90],
        "early burst":[80,90,90,90,90],
        "middle burst":[80,80,90,90,90],
        "late burst":[80,80,80,80,90],
    }
    print("SYNTHETIC: quarter-hour readings; rates in percentage points/hour")
    for name,values in cases.items():
        points=list(zip(ts,values))
        r=level_slope(points)
        print(f"{name:14s} OLS={r:.6f}; net={interval_slope(points):.6f}; "
              f"OLS ETA={60*(100-values[-1])/r:.3f} min; "
              f"Theil-Sen={theil_sen(points):.6f}")
    assert level_slope(list(zip(ts,cases["late burst"]))) == 8

    print("\nSYNTHETIC: same step at minute 30, different occupied buckets")
    for schedule in ([0,15,30,45,60],
                     [0,5,10,15,20,25,30,45,60],
                     [0,15,30,35,40,45,50,55,60],
                     list(range(0,61,5))):
        points=[(m/60,80 if m<30 else 90) for m in schedule]
        print(f"{schedule}: OLS={level_slope(points):.6f}, "
              f"net={interval_slope(points):.6f}")

    print("\nSYNTHETIC: 21h at 1 pp/h, then 3h at 8 pp/h")
    daily=[(x/4,40+min(x/4,21)+8*max(0,x/4-21)) for x in range(97)]
    for name,r in (("level WLS, half-life 6h",level_slope(daily,6)),
                   ("interval EW, half-life 6h",interval_slope(daily,6)),
                   ("net 24h",interval_slope(daily))):
        print(f"{name}: rate={r:.9f}; ETA={15/r:.6f} h; "
              f"balance at reset in 5h={15-5*r:.6f} pp (negative means exhaustion)")
    weights=induced_rate_weights(daily,6)
    ages=[24-(daily[j-1][0]+daily[j][0])/2 for j in range(1,len(daily))]
    print(f"Level-WLS induced newest-3h rate weight={sum(weights[-12:]):.9f}")
    print(f"Level-WLS induced mean age={sum(w*a for w,a in zip(weights,ages)):.9f} h")
    assert abs(sum(weights)-1) < 1e-12

    print("\nSYNTHETIC: last-bucket median hides a live jump")
    raw=[(m/60,80.) for m in (0,15,30,45,55,56,57,58,59)]
    raw.append((59.9/60,90.))
    bucketed=median_buckets(raw,5)
    print(f"Bucketed={bucketed}")
    print(f"Bucket-level slope={level_slope(bucketed):.6f}; "
          f"raw net rate={interval_slope(raw):.6f}")
    assert level_slope(bucketed) == 0

    print("\nSYNTHETIC: alternating corrections must not become consumption")
    corrected=list(zip(ts,[50,51,50,51,50]))
    positive_only=sum(max(0,b[1]-a[1]) for a,b in zip(corrected,corrected[1:]))
    print(f"Signed net rate={interval_slope(corrected):.6f}; "
          f"positive-only rate={positive_only:.6f}")

    print("\nSYNTHETIC: low movement is not necessarily low decision relevance")
    low=[(t,98.5+t) for t in ts]
    print(f"Net movement=1 pp; rate={level_slope(low):.6f}; "
          f"ETA={(100-low[-1][1])/level_slope(low)*60:.6f} min")

    print("\nSYNTHETIC control favorable to level regression")
    print("True constant rate=2.3 pp/h; 5 quarter-hour samples; integer rounding; "
          "1000 equally spaced initial fractional phases")
    errors={"OLS":[], "net":[]}
    for i in range(1000):
        phase=(i+.5)/1000
        points=[(t,floor(80+phase+2.3*t+.5)) for t in ts]
        errors["OLS"].append(level_slope(points)-2.3)
        errors["net"].append(interval_slope(points)-2.3)
    for name,values in errors.items():
        print(f"{name}: slope RMSE={sqrt(sum(e*e for e in values)/len(values)):.9f}")

    print("\nRounding-only sensitivity, not a confidence interval:")
    print("For net pace with endpoint errors bounded by q/2, projection error "
          "at reset is bounded by q/2 + q*D/S.")
    print(f"q=1 pp, observed span S=1h, reset horizon D=24h: bound={.5+24:.1f} pp")
    print("\nNo historical forecast accuracy, availability, or latency was measured.")

if __name__ == "__main__":
    main()
