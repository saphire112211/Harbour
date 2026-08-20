"""
demand_forecast.py
──────────────────
Predicts aggregate resource demand by zone and service type. The forecast is
limited to geography and resource categories; it does not score or profile
individual people. Organizations can use the result to pre-position capacity.

METHOD: a simple, transparent time-series signal — a 4-week moving average of
historical requests per (zone, service) plus a seasonal bump — producing a
next-week demand estimate and a capacity-gap flag. The interface is designed so
the synthetic history can be replaced with validated operational data.
"""

from __future__ import annotations
import numpy as np

SERVICE_TYPES = ["food", "housing", "healthcare", "childcare", "employment"]
RNG = np.random.default_rng(21)


def _synth_history(n_zones=6, n_weeks=8):
    """Synthetic weekly request history per (zone, service). Replace with real logs."""
    hist = {}
    for z in range(n_zones):
        for s in SERVICE_TYPES:
            base = RNG.integers(8, 40)
            trend = RNG.normal(0, 2, n_weeks).cumsum()
            series = np.clip(base + trend + RNG.normal(0, 3, n_weeks), 0, None)
            hist[(z, s)] = series.round().astype(int).tolist()
    return hist


def forecast_next_week(current_capacity: dict[tuple[int, str], int] | None = None,
                       n_zones: int = 6):
    """
    Returns, per (zone, service): predicted demand next week, current capacity,
    and a gap flag. organizations use this to pre-position supply.
    """
    hist = _synth_history(n_zones)
    out = []
    for (z, s), series in hist.items():
        recent = series[-4:]                       # 4-week moving average
        ma = float(np.mean(recent))
        # small seasonal/last-week momentum signal
        momentum = (series[-1] - np.mean(series[-4:-1])) if len(series) >= 4 else 0
        pred = max(0, round(ma + 0.5 * momentum))
        cap = (current_capacity or {}).get((z, s), round(ma * RNG.uniform(0.6, 1.1)))
        gap = pred - cap
        out.append({
            "zone": z, "service": s,
            "predicted_demand": int(pred),
            "current_capacity": int(cap),
            "gap": int(gap),                        # positive = shortfall expected
            "status": "shortfall" if gap > 3 else ("tight" if gap > 0 else "ok"),
        })
    # sort worst shortfalls first
    out.sort(key=lambda r: -r["gap"])
    return out


def top_shortfalls(n: int = 5, n_zones: int = 6):
    f = forecast_next_week(n_zones=n_zones)
    return [r for r in f if r["gap"] > 0][:n]


if __name__ == "__main__":
    print("Predicted shortfalls next week (zone, service): pre-position capacity here")
    for r in top_shortfalls():
        print(f"  Zone {r['zone']} · {r['service']:11s} "
              f"demand {r['predicted_demand']:>3} vs capacity {r['current_capacity']:>3} "
              f"→ gap +{r['gap']}  [{r['status']}]")
