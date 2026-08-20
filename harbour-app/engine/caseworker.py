"""
caseworker.py
─────────────
Human-in-the-loop escalation with vulnerability-based prioritization.

Caseworker capacity is treated as scarce. Safety flags, families with children,
same-day urgency, and broken referrals move a case higher in the queue. State is
stored in Supabase when configured and in escalations.json otherwise.
"""

from __future__ import annotations
import json, os, sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(HERE, "data", "escalations.json")

# Import the shared Supabase client (harbour-app/ is added to path so db.py is found).
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _get_sb():
    try:
        from db import get_sb
        return get_sb()
    except Exception:
        return None


# ── vulnerability score: what pushes a case up the scarce-time queue ──────────
def vulnerability_score(case: dict) -> int:
    s = 0
    if case.get("safety_flag"):        s += 100      # safety always first
    if case.get("has_children"):       s += 40
    if case.get("urgency") == "today": s += 30
    if case.get("reason") == "broken_loop": s += 25  # help didn't arrive
    if case.get("reason") == "low_confidence": s += 10
    if case.get("no_id"):              s += 5
    return s


REASON_LABEL = {
    "safety": "Safety keyword detected",
    "low_confidence": "Voice intake unclear after 2 tries",
    "broken_loop": "Reported they did NOT receive help",
}


def _seed():
    """Demo escalations for the bundled service area."""
    now = datetime.now()
    return [
        {"id": "C001", "user_hash": "u_8f3a", "reason": "safety", "safety_flag": True,
         "summary": "Reports domestic violence; needs to leave home tonight with two children",
         "urgency": "today", "has_children": True,
         "flagged_at": (now - timedelta(minutes=6)).isoformat(),
         "status": "open", "language": "Spanish"},
        {"id": "C002", "user_hash": "u_2b91", "reason": "broken_loop", "safety_flag": False,
         "summary": "The community food hub was at capacity when they arrived; family has not eaten today",
         "urgency": "today", "has_children": True,
         "flagged_at": (now - timedelta(hours=3)).isoformat(),
         "status": "open", "language": "Spanish"},
        {"id": "C003", "user_hash": "u_d7c4", "reason": "low_confidence", "safety_flag": False,
         "summary": "Primary language Vietnamese; transcript unclear on housing eviction timeline",
         "urgency": "this_week", "has_children": False, "no_id": True,
         "flagged_at": (now - timedelta(hours=1)).isoformat(),
         "status": "open", "language": "Other"},
        {"id": "C004", "user_hash": "u_5e22", "reason": "broken_loop", "safety_flag": False,
         "summary": "The community health center did not pick up; infant still without medical care",
         "urgency": "this_week", "has_children": True,
         "flagged_at": (now - timedelta(hours=20)).isoformat(),
         "status": "open", "language": "English"},
    ]


def _load():
    sb = _get_sb()
    if sb:
        rows = sb.table("escalations").select("*").execute().data
        return rows or []
    if not os.path.exists(STORE):
        return []
    with open(STORE, encoding="utf-8") as f:
        return json.load(f)


_SUPABASE_COLS = {"id","user_hash","reason","summary","urgency","has_children",
                  "safety_flag","language","status","referred_to","flagged_at","resolved_at"}

def save(cases):
    sb = _get_sb()
    if sb:
        if cases:
            try:
                rows = [{k: v for k, v in c.items() if k in _SUPABASE_COLS} for c in cases]
                sb.table("escalations").upsert(rows).execute()
            except Exception as e:
                print(f"[caseworker] Supabase save failed: {e}. Falling back to JSON.")
                with open(STORE, "w", encoding="utf-8") as f:
                    json.dump(cases, f, indent=2)
        return
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(cases, f, indent=2)


def queue():
    """Open cases, triaged by vulnerability (highest need first)."""
    cases = [c for c in _load() if c["status"] == "open"]
    for c in cases:
        c["vulnerability"] = vulnerability_score(c)
        c["reason_label"] = REASON_LABEL.get(c["reason"], c["reason"])
    cases.sort(key=lambda c: -c["vulnerability"])
    return cases


def resolve(case_id: str, referred_to: str = ""):
    cases = _load()
    for c in cases:
        if c["id"] == case_id:
            c["status"] = "resolved"
            c["resolved_at"] = datetime.now().isoformat()
            c["referred_to"] = referred_to or "Direct assistance"
    save(cases)
    return {"resolved": case_id, "referred_to": referred_to or "Direct assistance"}


def resolved_cases():
    """Closed cases, most recent first, with where each was referred."""
    cases = [c for c in _load() if c["status"] == "resolved"]
    for c in cases:
        c["reason_label"] = REASON_LABEL.get(c["reason"], c["reason"])
    cases.sort(key=lambda c: c.get("resolved_at", ""), reverse=True)
    return cases


def stats():
    """Panorama metrics for the caseworker dashboard."""
    cases = _load()
    openc = [c for c in cases if c["status"] == "open"]
    closed = [c for c in cases if c["status"] == "resolved"]
    # referrals grouped by organization
    by_organization = {}
    for c in closed:
        organization = c.get("referred_to", "Direct assistance")
        by_organization[organization] = by_organization.get(organization, 0) + 1
    return {
        "total": len(cases),
        "open": len(openc),
        "resolved": len(closed),
        "resolution_rate": round(len(closed) / len(cases), 2) if cases else 0,
        "referrals_by_organization": by_organization,
    }


def add_escalation(reason: str, summary: str, **kw):
    cases = _load()
    cid = f"C{len(cases)+1:03d}"
    cases.append({"id": cid, "user_hash": f"u_{cid}", "reason": reason,
                  "summary": summary, "flagged_at": datetime.now().isoformat(),
                  "status": "open", **kw})
    save(cases)
    return cid


if __name__ == "__main__":
    if os.path.exists(STORE):
        os.remove(STORE)
    print("Caseworker queue (vulnerability-triaged, NOT first-come-first-served):\n")
    for c in queue():
        print(f"  [{c['vulnerability']:>3}] {c['id']} · {c['reason_label']:35s} "
              f"{'👶' if c.get('has_children') else '  '} {c['urgency']:10s} {c['summary']}")
    print("\nResolving C001…"); resolve("C001")
    print("Remaining open:", [c["id"] for c in queue()])
