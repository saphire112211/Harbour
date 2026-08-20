"""
followups.py
────────────
After intake, Harbour asks a small set of plain-language eligibility questions
tailored to the person's detected needs. The answers refine eligibility signals
before matching and make the relevant rules easier to understand.

The questions and interpretations remain rule-based and auditable.
"""

from __future__ import annotations

# Questions are plain-language, tied to real eligibility rules, and only asked
# when relevant to the detected need. Each has an id, the question, and options.
QUESTION_BANK = {
    "household_size": {
        "q": "How many people live in your home, including you?",
        "options": ["Just me", "2", "3", "4", "5 or more"],
        "applies_to": ["food", "housing", "childcare"],
        "why": "Benefit amounts and income limits depend on household size.",
    },
    "income_band": {
        "q": "About how much does your household make per month?",
        "options": ["No income right now", "Under $1,500", "$1,500–$2,500", "More than $2,500"],
        "applies_to": ["food", "housing", "healthcare", "childcare"],
        "why": "Most programs use a monthly income limit to decide who qualifies.",
    },
    "has_children": {
        "q": "Do you have children under 18 living with you?",
        "options": ["Yes", "No"],
        "applies_to": ["housing", "childcare", "food"],
        "why": "Families with children qualify for more programs and get priority.",
    },
    "has_id": {
        "q": "Do you have a photo ID?",
        "options": ["Yes", "No", "Not sure"],
        "applies_to": ["housing", "healthcare", "employment"],
        "why": "Some programs ask for ID — but many food and crisis services do not.",
    },
    "eviction_notice": {
        "q": "Have you gotten an eviction or late-rent notice?",
        "options": ["Yes", "No"],
        "applies_to": ["housing"],
        "why": "An eviction notice moves you up the priority list for rent help.",
    },
}


def questions_for(needs: list[str], max_q: int = 3) -> list[dict]:
    """Pick the most relevant questions for the detected needs (cap at max_q)."""
    chosen = []
    seen = set()
    # priority order: the questions that unlock the most eligibility first
    order = ["income_band", "has_children", "household_size", "eviction_notice", "has_id"]
    for qid in order:
        q = QUESTION_BANK[qid]
        if any(n in q["applies_to"] for n in needs) and qid not in seen:
            chosen.append({"id": qid, "q": q["q"], "options": q["options"], "why": q["why"]})
            seen.add(qid)
        if len(chosen) >= max_q:
            break
    return chosen


def interpret(answers: dict) -> dict:
    """
    Turn answers into plain-language eligibility signals + structured fields the
    matcher can use. Transparent: every signal cites the rule it reflects.
    """
    signals = []
    fields = {}

    inc = answers.get("income_band")
    if inc in ("No income right now", "Under $1,500"):
        signals.append("Your income is low enough to qualify for most need-based programs.")
        fields["monthly_income"] = 800
    elif inc == "$1,500–$2,500":
        signals.append("You may qualify depending on household size.")
        fields["monthly_income"] = 2000
    elif inc == "More than $2,500":
        fields["monthly_income"] = 3000

    hh = answers.get("household_size")
    if hh:
        fields["household_size"] = {"Just me": 1, "2": 2, "3": 3, "4": 4, "5 or more": 5}.get(hh, 3)

    if answers.get("has_children") == "Yes":
        signals.append("Because you have children, you qualify for more programs and get priority.")
        fields["has_children"] = True

    if answers.get("eviction_notice") == "Yes":
        signals.append("Your eviction notice moves you up the priority list for rent help.")
        fields["priority_housing"] = True

    if answers.get("has_id") == "No":
        signals.append("No ID? That's okay — many food and crisis services don't require one.")

    if not signals:
        signals.append("Thanks — we'll match you to what's available near you.")

    return {"signals": signals, "fields": fields}


if __name__ == "__main__":
    qs = questions_for(["food", "housing"])
    print("Questions for food+housing:")
    for q in qs:
        print(f"  • {q['q']}  {q['options']}")
    print("\nInterpretation of sample answers:")
    out = interpret({"income_band": "Under $1,500", "has_children": "Yes", "eviction_notice": "Yes"})
    for s in out["signals"]:
        print("  →", s)
    print("  fields:", out["fields"])
