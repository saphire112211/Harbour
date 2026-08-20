"""
synthetic_data.py
─────────────────
Generates statistically grounded synthetic user profiles and a resource
catalog for Harbour's offline demonstration and regression tests.

APPROACH:
  Profiles are sampled from marginal distributions that
  mirror the American Community Survey (ACS) PUMS — the same public microdata
  the U.S. Census uses. In production this would be replaced by a real IPF
  (Iterative Proportional Fitting) draw over PUMS; here we encode the marginals
  directly so the project runs offline with zero external downloads.

  The resource catalog follows the Open Referral HSDS v3.0 schema (the industry
  standard adopted by 211 networks), preserving an interoperable data shape.
"""

from __future__ import annotations
import json
import random
from dataclasses import dataclass, asdict, field
from typing import Literal

import numpy as np
import pandas as pd

# Fixed seeds keep tests and demonstration metrics reproducible.
RNG = np.random.default_rng(42)
random.seed(42)

# ──────────────────────────────────────────────────────────────────────────────
# DEMONSTRATION MARGINAL DISTRIBUTIONS
# (Synthetic values for an offline demonstration. Replace these with an
# approved local PUMS + IPF draw before operational use.)
# ──────────────────────────────────────────────────────────────────────────────

CRISIS_TYPES = ["food", "housing", "healthcare", "childcare", "employment"]

# Probability that a household in crisis presents EACH need (needs can co-occur).
NEED_PREVALENCE = {
    "food":       0.62,
    "housing":    0.41,
    "healthcare": 0.33,
    "childcare":  0.28,
    "employment": 0.46,
}

# Synthetic demographic marginals for fairness regression tests.
# These are the groups the demographic-parity constraint will protect.
RACE_GROUPS = ["Hispanic", "Black", "White", "Asian", "Other"]
RACE_WEIGHTS = [0.44, 0.22, 0.25, 0.07, 0.02]

# Synthetic primary-language distribution.
LANGUAGES = ["English", "Spanish", "Vietnamese", "Other"]
LANG_WEIGHTS = [0.52, 0.39, 0.05, 0.04]

URGENCY_LEVELS = ["today", "this_week", "this_month"]
URGENCY_WEIGHTS = [0.28, 0.44, 0.28]


@dataclass
class UserProfile:
    """One synthetic household in crisis."""
    user_id: str
    needs: list[str]                # which crisis types they present
    urgency: str                    # today / this_week / this_month
    household_size: int
    monthly_income: int             # USD
    race_group: str                 # sensitive attribute (fairness)
    language: str
    has_transport: bool
    zip_zone: int                   # 0..N-1, abstract geographic zone
    # urgency as a numeric weight, used by the MILP objective
    urgency_weight: float = field(init=False)

    def __post_init__(self):
        self.urgency_weight = {"today": 3.0, "this_week": 2.0, "this_month": 1.0}[self.urgency]


def _sample_needs() -> list[str]:
    """Each user gets >=1 need, sampled from prevalence."""
    needs = [c for c in CRISIS_TYPES if RNG.random() < NEED_PREVALENCE[c]]
    if not needs:                                   # guarantee at least one
        needs = [RNG.choice(CRISIS_TYPES)]
    return needs


def generate_users(n: int = 200, n_zones: int = 6) -> list[UserProfile]:
    """Draw `n` synthetic households."""
    users = []
    for i in range(n):
        size = int(RNG.choice([1, 2, 3, 4, 5, 6], p=[0.18, 0.24, 0.22, 0.18, 0.12, 0.06]))
        # Income in USD/month — low-income-skewed demonstration data
        base = RNG.normal(1200, 480)
        income = max(0, int(base + size * RNG.normal(240, 95)))
        users.append(UserProfile(
            user_id=f"U{i:04d}",
            needs=_sample_needs(),
            urgency=str(RNG.choice(URGENCY_LEVELS, p=URGENCY_WEIGHTS)),
            household_size=size,
            monthly_income=income,
            race_group=str(RNG.choice(RACE_GROUPS, p=RACE_WEIGHTS)),
            language=str(RNG.choice(LANGUAGES, p=LANG_WEIGHTS)),
            has_transport=bool(RNG.random() < 0.45),
            zip_zone=int(RNG.integers(0, n_zones)),
        ))
    return users


# ──────────────────────────────────────────────────────────────────────────────
# RESOURCE CATALOG  (HSDS v3.0–style schema)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Resource:
    """A program/service, in a shape compatible with Open Referral HSDS."""
    resource_id: str
    name: str
    service_type: str               # one of CRISIS_TYPES
    zip_zone: int
    capacity: int                   # remaining slots THIS period (the scarcity!)
    max_income: int                 # eligibility ceiling (USD/month); 0 = none
    min_household_size: int         # eligibility floor; 0 = none
    hours: str
    # HSDS bookkeeping
    last_verified_days_ago: int = 0  # freshness — drives the staleness flag


RESOURCE_TEMPLATES = {
    "food":       ("Banco de Alimentos",         [40, 25, 60, 30]),
    "housing":    ("Programa de Renta Justa",    [8, 12, 6, 10]),
    "healthcare": ("Clínica Comunitaria",         [20, 15, 30]),
    "childcare":  ("Subsidio de Guardería",       [10, 14, 8]),
    "employment": ("Centro de Empleo",            [18, 22, 12]),
}


def generate_resources(n_zones: int = 6) -> list[Resource]:
    """Build a scarce, realistic resource catalog across zones."""
    resources: list[Resource] = []
    rid = 0
    for stype, (label, caps) in RESOURCE_TEMPLATES.items():
        for cap in caps:
            zone = int(RNG.integers(0, n_zones))
            resources.append(Resource(
                resource_id=f"R{rid:04d}",
                name=f"{label} #{rid}",
                service_type=stype,
                zip_zone=zone,
                capacity=int(cap),
                # ~half the programs have an income ceiling (USD/month); rest open
                max_income=int(RNG.choice([0, 1500, 2000, 2500], p=[0.4, 0.2, 0.2, 0.2])),
                min_household_size=int(RNG.choice([0, 0, 0, 2])),
                hours=RNG.choice(["Mon-Fri 9-5", "Daily 8-8", "Mon-Sat 10-4", "Apply online"]),
                last_verified_days_ago=int(RNG.integers(0, 75)),  # freshness varies
            ))
            rid += 1
    return resources


# ──────────────────────────────────────────────────────────────────────────────
# DISTANCE (abstract zone-to-zone) — feeds the MILP distance constraint
# ──────────────────────────────────────────────────────────────────────────────

def zone_distance(z1: int, z2: int) -> float:
    """Toy metric: |zone difference| in 'miles'. Same zone = 0.3 mi baseline."""
    return 0.3 + abs(z1 - z2) * 0.9


# ──────────────────────────────────────────────────────────────────────────────
# CLI / export
# ──────────────────────────────────────────────────────────────────────────────

def export(n_users: int = 200, n_zones: int = 6, out_dir: str | None = None):
    import os
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(out_dir, exist_ok=True)
    users = generate_users(n_users, n_zones)
    resources = generate_resources(n_zones)

    pd.DataFrame([asdict(u) for u in users]).to_csv(f"{out_dir}/users.csv", index=False)
    pd.DataFrame([asdict(r) for r in resources]).to_csv(f"{out_dir}/resources.csv", index=False)

    # also dump resources as HSDS-style JSON to prove interoperability
    with open(f"{out_dir}/resources_hsds.json", "w") as f:
        json.dump([asdict(r) for r in resources], f, indent=2)

    print(f"✓ {len(users)} users  →  {out_dir}/users.csv")
    print(f"✓ {len(resources)} resources  →  {out_dir}/resources.csv (+ HSDS JSON)")
    # quick demographic sanity check
    df = pd.DataFrame([asdict(u) for u in users])
    print("\nRace/ethnicity distribution (sensitive attribute):")
    print((df["race_group"].value_counts(normalize=True) * 100).round(1).to_string())
    print(f"\nTotal resource capacity: {sum(r.capacity for r in resources)} slots "
          f"for {len(users)} users  →  scarcity ratio "
          f"{sum(r.capacity for r in resources)/len(users):.2f}")
    return users, resources


if __name__ == "__main__":
    export()
