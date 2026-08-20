"""
test_core.py
────────────
Lightweight test suite proving the core behaves correctly.
Run:  python test_core.py   (no pytest dependency required)
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

from synthetic_data import generate_users, generate_resources, UserProfile, Resource
from milp_solver import solve, is_feasible
from intake_nlp import extract
from demo_scenario import build_scarcity_scenario

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS: {name}")
    else:
        failed += 1; print(f"  FAIL: {name}")


print("INTAKE NLP")
r = extract("I lost my job and my landlord is evicting me, I have kids")
check("detects multiple needs", set(["housing", "employment", "childcare"]).issubset(set(r.needs)))
check("high confidence on clear text", r.confidence >= 0.8)
check("proceeds to MILP", r.action == "PROCEED_TO_MILP")

r2 = extract("my partner hit me")
check("safety flag triggers", r2.safety_flag is True)
check("safety routes to escalation", r2.action == "ESCALATE_SAFETY")

r3 = extract("help")
check("vague input has low confidence", r3.confidence < 0.5)
check("vague input asks for a repeat", r3.action == "ASK_REPEAT")

r4 = extract("necesito comida para mis hijos hoy")
check("spanish detected", r4.language == "Spanish")
check("spanish needs extracted", "food" in r4.needs)


print("\nFEASIBILITY")
u = UserProfile("U0", ["food"], "today", 3, 900, "Latino", "Spanish", False, 0)
r_ok = Resource("R0", "FB", "food", 0, 10, 0, 0, "9-5")
r_wrong = Resource("R1", "Clinic", "healthcare", 0, 10, 0, 0, "9-5")
r_income = Resource("R2", "FB2", "food", 0, 10, 500, 0, "9-5")  # income ceiling 500
check("feasible when service matches", is_feasible(u, r_ok))
check("infeasible when wrong service", not is_feasible(u, r_wrong))
check("infeasible when over income ceiling", not is_feasible(u, r_income))


print("\nMILP SOLVER")
users = generate_users(80)
resources = generate_resources()
res = solve(users, resources, fairness=True)
check("solver reaches optimal", res.status == "Optimal")
check("serves at least some users", res.users_served > 0)
check("never over capacity", all(
    sum(1 for a in res.assignments if a.resource_id == r.resource_id) <= r.capacity
    for r in resources
))
check("parity gap within delta", res.parity_gap <= 0.15)


print("\nFAIRNESS EFFECT (the core claim)")
us, rs = build_scarcity_scenario()
naive = solve(us, rs, fairness=False, max_distance=2.0)
fair  = solve(us, rs, fairness=True, parity_delta=0.10, max_distance=2.0)
check("naive produces a larger parity gap than fair", naive.parity_gap > fair.parity_gap)
check("fair gap respects delta", fair.parity_gap <= 0.10 + 1e-6)
check("fair cost is small (<=20% fewer served)",
      (naive.users_served - fair.users_served) <= 0.2 * naive.total_users)

print(f"\n{'='*40}\n{passed} passed, {failed} failed\n{'='*40}")
sys.exit(1 if failed else 0)
