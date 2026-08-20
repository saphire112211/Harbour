"""
text_tools.py
─────────────
Two plain-language support functions:

1. PLAIN LANGUAGE — turn raw regulatory citations (SNAP §273.9) into something
   a person in crisis actually understands. The legal cite stays available as
   secondary detail, never as the headline.

2. READABILITY METRIC — don't just *claim* "plain language", measure it.
   We compute the Flesch Reading Ease score so the UI can show, with a number,
   that the plain version is dramatically easier than the legal text.
   (Higher = easier. 90-100 ≈ 5th grade, 30-50 ≈ college, 0-30 ≈ graduate.)

No external dependency is required.
"""

from __future__ import annotations
import re

# Raw legal citation  → (plain-language headline, secondary legal detail)
PLAIN_LANGUAGE = {
    "food": {
        "plain": "You can likely get food help. Most food banks don't check income at the door — you can usually walk in today.",
        "legal": "SNAP §273.9 — households at or below 130% of the federal poverty line qualify for food assistance.",
    },
    "housing": {
        "plain": "You may qualify for help with rent if you're behind or facing eviction. Bring your lease and any notice you got.",
        "legal": "Emergency Rental Assistance — households facing eviction below 80% of Area Median Income are eligible.",
    },
    "healthcare": {
        "plain": "You can get low-cost or free care even without insurance. Clinics adjust the price to what you can pay.",
        "legal": "Medicaid §1902 — coverage for households below the state income threshold; sliding-scale clinics serve the uninsured.",
    },
    "childcare": {
        "plain": "If you're working or looking for work, you may get help paying for childcare. Have your kids' birth certificates ready.",
        "legal": "CCDF §98.20 — childcare subsidy for working or job-seeking parents below income limits.",
    },
    "employment": {
        "plain": "You can get free help finding a job — resume help, training, and placement. No cost to you.",
        "legal": "WIOA Title I — job placement and training services for dislocated and low-income workers.",
    },
}


def _count_syllables(word: str) -> int:
    word = word.lower()
    word = re.sub(r'[^a-z]', '', word)
    if not word:
        return 0
    groups = re.findall(r'[aeiouy]+', word)
    n = len(groups)
    if word.endswith('e') and n > 1:      # silent e
        n -= 1
    return max(1, n)


def flesch_reading_ease(text: str) -> float:
    """Flesch Reading Ease. Higher = easier to read."""
    sentences = max(1, len(re.findall(r'[.!?]+', text)) or 1)
    words = re.findall(r"[A-Za-z']+", text)
    if not words:
        return 0.0
    n_words = len(words)
    n_syll = sum(_count_syllables(w) for w in words)
    score = 206.835 - 1.015 * (n_words / sentences) - 84.6 * (n_syll / n_words)
    return round(score, 1)


def grade_label(score: float) -> str:
    """Human label for a Flesch Reading Ease score."""
    if score >= 90: return "5th grade"
    if score >= 80: return "6th grade"
    if score >= 70: return "7th grade"
    if score >= 60: return "8th–9th grade"
    if score >= 50: return "10th–12th grade"
    if score >= 30: return "college"
    return "college graduate"


def plain_for(service: str) -> dict:
    """Return plain + legal + readability comparison for a service type."""
    entry = PLAIN_LANGUAGE.get(service, {
        "plain": "You may qualify for this program — contact them to confirm.",
        "legal": "Eligibility determined by program rules.",
    })
    legal_score = flesch_reading_ease(entry["legal"])
    plain_score = flesch_reading_ease(entry["plain"])
    return {
        "plain": entry["plain"],
        "legal": entry["legal"],
        "readability": {
            "legal_score": legal_score, "legal_level": grade_label(legal_score),
            "plain_score": plain_score, "plain_level": grade_label(plain_score),
        },
    }


if __name__ == "__main__":
    for s in PLAIN_LANGUAGE:
        d = plain_for(s)
        r = d["readability"]
        print(f"{s:11s}  legal={r['legal_score']:>5} ({r['legal_level']})  "
              f"→  plain={r['plain_score']:>5} ({r['plain_level']})")
