"""
scraper.py
──────────
Collects community-resource listings (food banks, rent relief, clinics,
childcare, job centers) and writes them to data/resources.json in the
Open Referral HSDS v3.0 shape that the Harbour engine consumes.

TWO MODES
  1) LIVE scrape  ── `python scraper.py --live --url <listing_url>`
        Real requests + BeautifulSoup. Run this locally where you HAVE
        internet. It fetches a public resource-directory page, parses the
        listing cards, and maps each to an HSDS record. Selectors are kept
        in SELECTORS so you can retarget a new source in one place.

  2) SEED        ── `python scraper.py --seed`   (default)
        Generates a realistic, geographically-distributed HSDS dataset so
        the app runs immediately with zero network. Replace with --live
        output once you point it at a real source.

NOTE ON ETHICS/ToS: only scrape sources whose terms allow it, prefer official
open-data endpoints (many 211 / city portals publish HSDS or CSV directly),
and cache results — don't hammer a live site on every request. Prefer an
HSDA-compliant API over HTML scraping whenever one is available.
"""

from __future__ import annotations
import argparse, json, os, random, sys, time

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
OUT = os.path.join(DATA_DIR, "resources.json")

SERVICE_TYPES = ["food", "housing", "healthcare", "childcare", "employment"]

# ── Selectors for the LIVE scraper (retarget here for a new source) ───────────
SELECTORS = {
    "card":     "div.resource-card",       # each listing
    "name":     "h3.resource-name",
    "address":  "span.address",
    "hours":    "span.hours",
    "category": "span.category",
    "phone":    "a.phone",
}


def scrape_osm(bbox: str = "29.5,-95.8,30.1,-95.1", max_per_type: int = 8) -> list[dict]:
    """
    Fetch real community resources from OpenStreetMap via Overpass API.
    bbox = "south,west,north,east"  (default: bundled demonstration area)
    Uses a single combined query to avoid rate-limiting.
    """
    try:
        import requests
    except ImportError:
        sys.exit("pip install requests")

    # One combined query — one HTTP request, no rate limit issues
    b = bbox
    query = f"""
[out:json][timeout:40];
(
  node["amenity"="food_bank"]({b});
  way["amenity"="food_bank"]({b});
  node["amenity"="soup_kitchen"]({b});
  way["amenity"="soup_kitchen"]({b});
  node["social_facility"="food_bank"]({b});
  node["social_facility"="food_pantry"]({b});
  node["amenity"="shelter"]({b});
  way["amenity"="shelter"]({b});
  node["social_facility"="shelter"]({b});
  way["social_facility"="shelter"]({b});
  node["social_facility"="homeless_shelter"]({b});
  node["amenity"="clinic"]({b});
  way["amenity"="clinic"]({b});
  node["amenity"="health_post"]({b});
  node["healthcare"="clinic"]({b});
  way["healthcare"="clinic"]({b});
  node["amenity"="childcare"]({b});
  way["amenity"="childcare"]({b});
  node["amenity"="kindergarten"]({b});
  way["amenity"="kindergarten"]({b});
  node["office"="employment_agency"]({b});
  way["office"="employment_agency"]({b});
  node["government"="employment_agency"]({b});
);
out center;
"""

    # Tag → service type mapping
    def _service(tags: dict) -> str:
        amenity = tags.get("amenity", "")
        sf = tags.get("social_facility", "")
        office = tags.get("office", "") + tags.get("government", "")
        hc = tags.get("healthcare", "")
        if amenity in ("food_bank", "soup_kitchen") or sf in ("food_bank", "food_pantry"):
            return "food"
        if amenity == "shelter" or sf in ("shelter", "homeless_shelter"):
            return "housing"
        if amenity in ("clinic", "health_post") or hc == "clinic":
            return "healthcare"
        if amenity in ("childcare", "kindergarten"):
            return "childcare"
        if "employment" in office:
            return "employment"
        return "food"   # fallback

    try:
        resp = None
        for endpoint in [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
        ]:
            try:
                resp = requests.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": "HarbourBenefitsNavigator/1.1"},
                    timeout=45,
                )
                resp.raise_for_status()
                break
            except Exception:
                resp = None
                continue
        if resp is None:
            print("  OSM request failed: all endpoints timed out")
            return []
        elements = resp.json().get("elements", [])
    except Exception as e:
        print(f"  OSM request failed: {e}")
        return []

    records, rid, seen = [], 0, set()
    counts: dict[str, int] = {}
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name or name in seen:
            continue
        service = _service(tags)
        if counts.get(service, 0) >= max_per_type:
            continue
        seen.add(name)
        addr = " ".join(filter(None, [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", ""),
            tags.get("addr:city", ""),
        ])).strip() or tags.get("addr:full", "")
        rlat = el.get("lat") or (el.get("center") or {}).get("lat")
        rlon = el.get("lon") or (el.get("center") or {}).get("lon")
        s, w, n, e = (float(x) for x in bbox.split(","))
        zone = _lat_lon_to_zone(rlat, rlon, (s, w, n, e)) if rlat and rlon else rid % 6
        records.append(_hsds_record(
            rid=f"R{rid:04d}", name=name, service=service,
            address=addr,
            hours=tags.get("opening_hours", "Call for hours"),
            phone=tags.get("phone", tags.get("contact:phone", "")),
            url=tags.get("website", tags.get("contact:website", "")),
            zone=zone, capacity=random.randint(10, 40),
            verified_days=0, lat=rlat, lon=rlon,
        ))
        counts[service] = counts.get(service, 0) + 1
        rid += 1

    for svc, n in sorted(counts.items()):
        print(f"  {svc:12s} → {n} results")
    return records


def scrape_live(url: str, max_items: int = 100) -> list[dict]:
    """
    Real scrape. Requires `requests` and `beautifulsoup4` and internet.
    Maps each listing card to an HSDS-style record.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        sys.exit("Install deps first:  pip install requests beautifulsoup4")

    headers = {"User-Agent": "HarbourBenefitsNavigator/1.1"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    records = []
    for i, card in enumerate(soup.select(SELECTORS["card"])[:max_items]):
        def grab(sel):
            el = card.select_one(SELECTORS[sel])
            return el.get_text(strip=True) if el else ""

        name = grab("name")
        if not name:
            continue
        category = grab("category").lower()
        service = next((s for s in SERVICE_TYPES if s in category), "food")
        # capture the source link if the card has one
        link_el = card.select_one("a")
        link = link_el.get("href", "") if link_el else ""
        if link and link.startswith("/"):
            from urllib.parse import urljoin
            link = urljoin(url, link)
        records.append(_hsds_record(
            rid=f"R{i:04d}", name=name, service=service,
            address=grab("address"), hours=grab("hours") or "Call for hours",
            phone=grab("phone"), url=link,
        ))
        time.sleep(0.3)   # be polite
    return records


def _lat_lon_to_zone(lat: float, lon: float,
                     bbox=(29.5, -95.8, 30.1, -95.1)) -> int:
    """Map a lat/lon to zone 0-5 on a 3×2 grid of the service area."""
    s, w, n, e = bbox
    row = min(2, max(0, int((lat - s) / (n - s) * 3)))
    col = min(1, max(0, int((lon - w) / (e - w) * 2)))
    return row * 2 + col


def _hsds_record(rid, name, service, address, hours, phone,
                 zone=None, capacity=None, max_income=0, min_hh=0,
                 verified_days=0, url="", lat=None, lon=None) -> dict:
    """One Open Referral HSDS-shaped service record."""
    return {
        "resource_id": rid,
        "name": name,
        "service_type": service,
        "address": address,
        "phone": phone,
        "hours": hours,
        "url": url,
        "lat": lat,
        "lon": lon,
        "zip_zone": zone if zone is not None else random.randint(0, 5),
        "capacity": capacity if capacity is not None else random.randint(6, 50),
        "max_income": max_income,
        "min_household_size": min_hh,
        "last_verified_days_ago": verified_days,
        "hsds": {"schema": "openreferral-hsds-3.0", "status": "active"},
    }


# ── SEED generator (realistic, no network) ────────────────────────────────────
SEED_NAMES = {
    "food": ["Central Community Food Hub", "Southwest Community Pantry",
             "Open Door Food Pantry", "Northside Food Shelf",
             "Family Support Food Shelf", "Neighborhood Table"],
    "housing": ["Community Rent Relief", "Affordable Housing Assistance",
                "Central Emergency Shelter", "Family Support Lodge"],
    "healthcare": ["Community Health Center", "Public Health Clinic",
                   "Neighborhood Health and Wellness", "Community Care Clinic"],
    "childcare": ["Community Childcare Network", "Early Learning Center",
                  "Community Child Development Center"],
    "employment": ["Regional Workforce Center", "Community Career Center",
                   "Community Job Connection", "Multicultural Employment Services"],
}
STREETS = ["Main Street", "Oak Avenue", "River Road", "Market Street", "Park Lane",
           "Cedar Drive", "Hill Avenue", "Lake Road", "Center Boulevard", "North Street"]


def scrape_seed() -> list[dict]:
    random.seed(11)
    records = []
    rid = 0
    for service, names in SEED_NAMES.items():
        for name in names:
            zone = random.randint(0, 5)
            slug = name.lower().replace(" ", "-").replace("'", "").replace("#", "").replace(".", "")
            records.append(_hsds_record(
                rid=f"R{rid:04d}", name=name, service=service,
                address=f"{random.randint(100, 9999)} {random.choice(STREETS)}",
                hours=random.choice(["Mon-Fri 9-5", "Daily 8-8", "Mon-Sat 10-4",
                                     "Apply online", "Tue/Thu 9-1"]),
                phone=f"(555) {random.randint(200,999)}-{random.randint(1000,9999)}",
                url=f"https://findhelp.example.org/program/{slug}",
                zone=zone,
                capacity=random.randint(6, 45),
                max_income=random.choice([0, 1600, 2200, 3000]),
                min_hh=random.choice([0, 0, 0, 2]),
                verified_days=random.randint(0, 70),
            ))
            rid += 1
    return records


def main():
    ap = argparse.ArgumentParser(description="Harbour community-resource scraper")
    ap.add_argument("--live", action="store_true", help="scrape a live HTML URL")
    ap.add_argument("--osm",  action="store_true", help="fetch real data from OpenStreetMap")
    ap.add_argument("--seed", action="store_true", help="generate seed data (default)")
    ap.add_argument("--url",  default="", help="listing URL for --live")
    ap.add_argument("--bbox", default="29.5,-95.8,30.1,-95.1",
                    help="lat/lon bbox for --osm (default: bundled demonstration area). "
                         "Format: south,west,north,east")
    args = ap.parse_args()

    if args.live:
        if not args.url:
            sys.exit("--live needs --url <listing_url>")
        print(f"Scraping live: {args.url}")
        records = scrape_live(args.url)
    elif args.osm:
        print(f"Fetching real resources from OpenStreetMap (bbox={args.bbox})...")
        records = scrape_osm(args.bbox)
        if not records:
            print("Warning: OSM returned 0 results — falling back to seed data")
            records = scrape_seed()
    else:
        print("Generating seed dataset (HSDS v3.0 shape)...")
        records = scrape_seed()

    with open(OUT, "w") as f:
        json.dump({"source": "live" if args.live else "seed",
                   "schema": "openreferral-hsds-3.0",
                   "count": len(records),
                   "resources": records}, f, indent=2)

    by_type = {}
    for r in records:
        by_type[r["service_type"]] = by_type.get(r["service_type"], 0) + 1
    print(f"Wrote {len(records)} resources to {OUT}")
    print("  by service:", by_type)
    print("  total capacity:", sum(r["capacity"] for r in records), "slots")


if __name__ == "__main__":
    main()
