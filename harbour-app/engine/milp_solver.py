"""
milp_solver.py
──────────────
System-wide fair resource allocation.

The solver determines which user-to-program matches
maximize total need-coverage across ALL users simultaneously, subject to:

    • capacity        (programs are scarce)
    • eligibility     (income ceiling, household-size floor)
    • distance        (a user without transport can't cross town)
    • urgency         (today > this_week > this_month, via objective weights)
    • demographic parity across configured groups

Mathematical formulation:

    Variables:  x[i,j] ∈ {0,1}   = 1 iff user i assigned to program j
                                    for a need they actually have

    Objective:  maximize  Σ_{i,j}  w_i · need_match[i,j] · x[i,j]
                where w_i is the urgency weight of user i

    s.t.  (1) Σ_i x[i,j] ≤ capacity_j            ∀ programs j   (scarcity)
          (2) Σ_j x[i,j] ≤ |needs_i|             ∀ users i      (no over-assign)
          (3) x[i,j] = 0 if user i ineligible / too far / wrong service
          (4) | served_rate(g) − served_rate(overall) | ≤ δ  ∀ groups g  (PARITY)

Constraint (4) is the demographic-parity constraint, expressed exactly as the
fair-ML literature does:  |  N̂(g)/N(g) − N̂/N  | ≤ δ   (Aghaei et al., 2023).
We linearize it for the integer program below.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence

import pulp

# Local imports work whether run as module or script
try:
    from .synthetic_data import UserProfile, Resource, zone_distance
except ImportError:
    from synthetic_data import UserProfile, Resource, zone_distance


# ──────────────────────────────────────────────────────────────────────────────
# Eligibility / feasibility — which (user, resource) pairs are even allowed
# ──────────────────────────────────────────────────────────────────────────────

def is_feasible(user: UserProfile, res: Resource, max_distance: float = 5.0) -> bool:
    """A match is feasible only if ALL hard rules pass."""
    # 1. the resource must serve a need the user actually has
    if res.service_type not in user.needs:
        return False
    # 2. income ceiling (0 = no ceiling)
    if res.max_income and user.monthly_income > res.max_income:
        return False
    # 3. household-size floor
    if res.min_household_size and user.household_size < res.min_household_size:
        return False
    # 4. distance — users without transport have a tighter radius
    d = zone_distance(user.zip_zone, res.zip_zone)
    limit = max_distance if user.has_transport else max_distance * 0.5
    if d > limit:
        return False
    return True


@dataclass
class Assignment:
    user_id: str
    resource_id: str
    resource_name: str
    service_type: str
    distance: float
    confidence: float           # 0..1, how strong this match is


@dataclass
class SolveResult:
    assignments: list[Assignment]
    objective_value: float
    users_served: int
    total_users: int
    served_by_group: dict[str, float]     # group -> served rate (for the equity audit)
    parity_gap: float                      # max deviation across groups
    status: str
    fairness_on: bool


# ──────────────────────────────────────────────────────────────────────────────
# The solver
# ──────────────────────────────────────────────────────────────────────────────

def solve(
    users: Sequence[UserProfile],
    resources: Sequence[Resource],
    *,
    fairness: bool = True,
    parity_delta: float = 0.10,        # allowed deviation in served-rate across groups
    max_distance: float = 5.0,
    verbose: bool = False,
) -> SolveResult:
    """
    Solve the fair allocation MILP.

    Set fairness=False to get the *naive* (utility-only) solution — this is the
    baseline we put on the LEFT of the split-screen demo. fairness=True is the
    RIGHT side: same data, with the demographic-parity constraint switched on.
    """
    prob = pulp.LpProblem("Harbour_FairAllocation", pulp.LpMaximize)

    # ── decision variables: only build x[i,j] for FEASIBLE pairs ──────────────
    x = {}
    feasible_pairs = []
    for i, u in enumerate(users):
        for j, r in enumerate(resources):
            if is_feasible(u, r, max_distance):
                x[(i, j)] = pulp.LpVariable(f"x_{i}_{j}", cat="Binary")
                feasible_pairs.append((i, j))

    # ── confidence/score per feasible pair (also used as objective weight) ────
    def match_score(u: UserProfile, r: Resource) -> float:
        # Proximity (50 pts): same zone = full score, degrades with distance
        d = zone_distance(u.zip_zone, r.zip_zone)
        proximity = 0.50 * (1.0 / (1.0 + d))

        # Income headroom (30 pts): wider margin under the ceiling = better odds
        if r.max_income and r.max_income > 0:
            headroom = (r.max_income - u.monthly_income) / r.max_income
            income = 0.30 * min(1.0, max(0.0, headroom))
        else:
            income = 0.30   # no ceiling → full score

        # Capacity (20 pts): more open slots = better odds of getting served
        cap = min(r.capacity, 40) / 40.0 if r.capacity and r.capacity > 0 else 0.5
        capacity = 0.20 * cap

        return round(proximity + income + capacity, 3)

    score = {(i, j): match_score(users[i], resources[j]) for (i, j) in feasible_pairs}

    # ── OBJECTIVE: maximize urgency-weighted, score-weighted coverage ─────────
    prob += pulp.lpSum(
        users[i].urgency_weight * score[(i, j)] * x[(i, j)]
        for (i, j) in feasible_pairs
    ), "total_weighted_coverage"

    # ── (1) capacity: each program can't exceed remaining slots ───────────────
    for j, r in enumerate(resources):
        pairs_j = [(i, j) for (ii, jj) in feasible_pairs if jj == j for i in [ii]]
        if pairs_j:
            prob += pulp.lpSum(x[p] for p in pairs_j) <= r.capacity, f"cap_{j}"

    # ── (2) no over-assignment: a user gets at most one program per need ──────
    for i, u in enumerate(users):
        pairs_i = [(i, j) for (ii, jj) in feasible_pairs if ii == i for j in [jj]]
        if pairs_i:
            prob += pulp.lpSum(x[p] for p in pairs_i) <= len(u.needs), f"maxneed_{i}"
        # also: at most one program per (user, service_type)
        by_service: dict[str, list] = {}
        for (ii, jj) in pairs_i:
            by_service.setdefault(resources[jj].service_type, []).append((ii, jj))
        for stype, plist in by_service.items():
            if len(plist) > 1:
                prob += pulp.lpSum(x[p] for p in plist) <= 1, f"oneper_{i}_{stype}"

    # ── (4) DEMOGRAPHIC PARITY ────────────────────────────────────────────────
    # "served" = user gets at least one assignment.  We approximate the served
    # COUNT per group with the sum of that group's assignment variables, divided
    # by group size, and force every group's rate within ±δ of the global rate.
    #
    # To keep it linear we constrain group served-COUNT proportionally:
    #     served(g)/N(g)  ≥  (overall served fraction) − δ
    # implemented via a shared lower-bound variable.
    groups = sorted({u.race_group for u in users})
    group_idx = {g: [i for i, u in enumerate(users) if u.race_group == g] for g in groups}

    if fairness:
        # served_i ∈ [0,1] proxy: sum of this user's vars, capped at 1 via aux var
        served = {i: pulp.LpVariable(f"served_{i}", cat="Binary") for i in range(len(users))}
        for i in range(len(users)):
            pairs_i = [(i, j) for (ii, jj) in feasible_pairs if ii == i for j in [jj]]
            if pairs_i:
                # served_i <= sum(x) and served_i >= each x  → served=1 iff any assigned
                prob += served[i] <= pulp.lpSum(x[p] for p in pairs_i), f"served_le_{i}"
                for p in pairs_i:
                    prob += served[i] >= x[p], f"served_ge_{i}_{p[1]}"
            else:
                prob += served[i] == 0, f"served_zero_{i}"

        # global served-rate lower bound that every group must meet (within δ)
        # We enforce: served(g)/|g| >= L  and  served(g)/|g| <= L + δ   for a free L.
        L = pulp.LpVariable("parity_floor", lowBound=0, upBound=1)
        for g in groups:
            idx = group_idx[g]
            if idx:
                ng = len(idx)
                prob += pulp.lpSum(served[i] for i in idx) >= L * ng, f"parity_lo_{g}"
                prob += pulp.lpSum(served[i] for i in idx) <= (L + parity_delta) * ng, f"parity_hi_{g}"

    # ── solve ──────────────────────────────────────────────────────────────────
    solver = pulp.PULP_CBC_CMD(msg=1 if verbose else 0)
    prob.solve(solver)

    # ── extract assignments ─────────────────────────────────────────────────────
    assignments: list[Assignment] = []
    served_users: set[int] = set()
    for (i, j) in feasible_pairs:
        if x[(i, j)].value() and x[(i, j)].value() > 0.5:
            u, r = users[i], resources[j]
            assignments.append(Assignment(
                user_id=u.user_id,
                resource_id=r.resource_id,
                resource_name=r.name,
                service_type=r.service_type,
                distance=round(zone_distance(u.zip_zone, r.zip_zone), 2),
                confidence=score[(i, j)],
            ))
            served_users.add(i)

    # ── equity audit: served rate per group ──────────────────────────────────
    served_by_group = {}
    for g in groups:
        idx = group_idx[g]
        served_by_group[g] = round(
            sum(1 for i in idx if i in served_users) / len(idx), 3
        ) if idx else 0.0
    rates = list(served_by_group.values())
    parity_gap = round(max(rates) - min(rates), 3) if rates else 0.0

    return SolveResult(
        assignments=assignments,
        objective_value=round(pulp.value(prob.objective) or 0, 2),
        users_served=len(served_users),
        total_users=len(users),
        served_by_group=served_by_group,
        parity_gap=parity_gap,
        status=pulp.LpStatus[prob.status],
        fairness_on=fairness,
    )


if __name__ == "__main__":
    from synthetic_data import generate_users, generate_resources
    us = generate_users(120)
    rs = generate_resources()
    print("Solving WITHOUT fairness (naive baseline)…")
    naive = solve(us, rs, fairness=False)
    print(f"  served {naive.users_served}/{naive.total_users}  parity_gap={naive.parity_gap}")
    print(f"  by group: {naive.served_by_group}")
    print("\nSolving WITH demographic-parity constraint…")
    fair = solve(us, rs, fairness=True, parity_delta=0.08)
    print(f"  served {fair.users_served}/{fair.total_users}  parity_gap={fair.parity_gap}")
    print(f"  by group: {fair.served_by_group}")
