"""
seed_supabase.py — populate the Supabase `resources` table from data/resources.json.

Run ONCE after creating the tables in Supabase:
    python seed_supabase.py

Safe to re-run: uses upsert on resource_id (no duplicates).
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "resources.json")

from db import get_sb


def seed():
    sb = get_sb()
    if not sb:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY not set in .env")
        sys.exit(1)

    with open(DATA, encoding="utf-8") as f:
        blob = json.load(f)

    rows = []
    for r in blob["resources"]:
        row = {
            "resource_id":            r["resource_id"],
            "name":                   r["name"],
            "service_type":           r["service_type"],
            "address":                r.get("address", ""),
            "hours":                  r.get("hours", ""),
            "phone":                  r.get("phone", ""),
            "email":                  r.get("email", ""),
            "url":                    r.get("url", ""),
            "zip_zone":               r.get("zip_zone", 0),
            "capacity":               r.get("capacity", 0),
            "max_income":             r.get("max_income", 0),
            "min_household_size":     r.get("min_household_size", 0),
            "last_verified_days_ago": r.get("last_verified_days_ago", 0),
        }
        if r.get("lat") is not None:
            row["lat"] = r["lat"]
        if r.get("lon") is not None:
            row["lon"] = r["lon"]
        rows.append(row)

    sb.table("resources").delete().neq("resource_id", "").execute()
    print("Cleared old records.")
    sb.table("resources").insert(rows).execute()
    print(f"Seeded {len(rows)} resources into Supabase.")


if __name__ == "__main__":
    seed()
