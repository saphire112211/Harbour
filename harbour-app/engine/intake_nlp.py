"""
intake_nlp.py
─────────────
Turns a free-text transcript (what Whisper would produce from the user's voice)
into the structured constraints the MILP needs.

The current implementation is a transparent, rule-based extractor with a
confidence score. Matched evidence is returned with each result, and confidence
gates confirmation, repetition, or human escalation.

In production the keyword layer would be replaced/augmented by a fine-tuned
classifier or an LLM call while preserving the same downstream interface.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field

CRISIS_TYPES = ["food", "housing", "healthcare", "childcare", "employment"]

# Keyword evidence per need. Multilingual on purpose (EN + ES) because the
# target user may describe their situation in Spanish.
NEED_KEYWORDS = {
    "food": [
        "food", "eat", "hungry", "groceries", "meal", "pantry",
        "comida", "comer", "hambre", "despensa", "alimento",
    ],
    "housing": [
        "rent", "evict", "homeless", "landlord", "housing", "shelter", "apartment",
        "renta", "desalojo", "casero", "vivienda", "refugio", "apartamento",
    ],
    "healthcare": [
        "doctor", "sick", "medicine", "health", "hospital", "insurance", "clinic",
        "medico", "enfermo", "medicina", "salud", "seguro", "clinica",
    ],
    "childcare": [
        "kids", "children", "childcare", "daycare", "school", "baby",
        "hijos", "niños", "guarderia", "escuela", "bebe",
    ],
    "employment": [
        "job", "work", "unemployed", "laid off", "fired", "income",
        "trabajo", "empleo", "desempleado", "despidieron", "ingreso",
    ],
}

# Urgency evidence.
URGENCY_KEYWORDS = {
    "today": ["today", "now", "tonight", "immediately", "emergency", "right now",
              "hoy", "ahora", "esta noche", "emergencia", "ya"],
    "this_week": ["this week", "days", "soon", "30 days", "esta semana", "dias", "pronto"],
}

# Safety-critical keywords → MUST route to a human, AI does NOT proceed.
# Single words that alone are high-risk signals.
SAFETY_WORDS = {
    "suicide", "suicidal", "suicidio", "suicidarme",
}

# Phrases — substring match after lowercasing.
SAFETY_KEYWORDS = [
    # English — self-harm / suicide (many phrasings of the same intent)
    "kill myself", "kill me", "want to kill", "wanna kill", "gonna kill",
    "end my life", "end it all", "end everything", "take my life",
    "want to die", "wanna die", "going to die", "wish i were dead",
    "wish i was dead", "better off dead", "don't want to be here",
    "don't want to live", "cant go on", "can't go on", "no reason to live",
    "not worth living", "life is not worth", "hurt myself", "harm myself",
    "self harm", "self-harm", "cut myself", "cutting myself",
    # English — violence / danger
    "abuse", "hit me", "violence", "danger", "weapon", "child alone", "domestic",
    "threaten", "threatened", "beat me", "rape", "assault",
    # Spanish — self-harm / suicide
    "matarme", "quiero matarme", "hacerme daño", "lastimarme", "cortarme",
    "quitarme la vida", "acabar con mi vida", "acabar con todo",
    "quiero morir", "quisiera morir", "no quiero vivir", "no vale la pena vivir",
    "mejor estar muerto", "no puedo mas", "no puedo seguir",
    # Spanish — violence / danger
    "lastimar", "abuso", "golpea", "golpean", "violencia",
    "peligro", "arma", "amenaza", "violar", "agresion",
]

# Word-pair combinations: if BOTH a harm verb and a target word appear → flag.
_HARM_VERBS = {"kill", "hurt", "harm", "end", "die", "dying", "dead"}
_SELF_TARGETS = {"me", "myself", "i", "my life", "everything"}

LANG_HINTS = {
    "Spanish": ["comida", "renta", "trabajo", "hijos", "salud", "ayuda", "necesito", "tengo"],
    "Mandarin": ["我", "需要", "帮助"],
}


@dataclass
class IntakeResult:
    needs: list[str]
    urgency: str
    language: str
    confidence: float                 # 0..1
    safety_flag: bool
    matched_terms: dict[str, list[str]] = field(default_factory=dict)
    action: str = ""                  # what the system should do next


def _detect_language(text: str) -> str:
    t = text.lower()
    for lang, hints in LANG_HINTS.items():
        if sum(h in t for h in hints) >= 2:
            return lang
    return "English"


def extract(transcript: str) -> IntakeResult:
    """Main entry point: transcript → structured constraints + confidence."""
    text = transcript.lower()

    # 1. safety screen FIRST — overrides everything
    # Three independent detection paths — any one is enough to flag:
    safety_hits = [k for k in SAFETY_KEYWORDS if k in text]
    single_word_hit = any(w in re.split(r'\W+', text) for w in SAFETY_WORDS)
    words = set(re.split(r'\W+', text))
    combo_hit = bool(_HARM_VERBS & words) and bool(_SELF_TARGETS & words)
    safety_flag = bool(safety_hits) or single_word_hit or combo_hit

    # 2. needs
    matched: dict[str, list[str]] = {}
    needs = []
    for need, kws in NEED_KEYWORDS.items():
        hits = [k for k in kws if k in text]
        if hits:
            needs.append(need)
            matched[need] = hits

    # 3. urgency
    urgency = "this_month"
    for level, kws in URGENCY_KEYWORDS.items():
        if any(k in text for k in kws):
            urgency = level
            break

    # 4. language
    language = _detect_language(transcript)

    # 5. CONFIDENCE — the gate.
    # Heuristic: more distinct keyword evidence + a clear single dominant need
    # => higher confidence. Very short transcripts or zero matches => low.
    n_words = max(1, len(text.split()))
    total_hits = sum(len(v) for v in matched.values())
    if not needs:
        confidence = 0.15
    else:
        evidence = min(1.0, total_hits / 4.0)        # saturates at 4 keyword hits
        length_ok = min(1.0, n_words / 12.0)          # very short = less reliable
        confidence = round(0.4 + 0.45 * evidence + 0.15 * length_ok, 2)
        confidence = min(confidence, 0.99)

    # 6. decide the next action (drives human-in-the-loop)
    if safety_flag:
        action = "ESCALATE_SAFETY"          # human specialist, AI does not match
    elif confidence >= 0.80:
        action = "PROCEED_TO_MILP"
    elif confidence >= 0.50:
        action = "CONFIRM_TRANSCRIPT"        # ask user to confirm
    else:
        action = "ASK_REPEAT"                # re-record; 2nd failure -> human

    return IntakeResult(
        needs=needs or ["food"],            # never empty downstream
        urgency=urgency,
        language=language,
        confidence=confidence,
        safety_flag=safety_flag,
        matched_terms=matched,
        action=action,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Demo
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    samples = [
        "I lost my job three weeks ago. I have two kids and we are renting. "
        "My landlord said I have 30 days. I don't have a car.",
        "Perdi mi trabajo y no tengo comida para mis hijos, necesito ayuda hoy.",
        "uh... help",                                      # low confidence
        "My partner hit me and I need to leave tonight.",  # safety flag
    ]
    for s in samples:
        r = extract(s)
        print(f"\nTranscript: {s[:60]}...")
        print(f"  needs={r.needs}  urgency={r.urgency}  lang={r.language}")
        print(f"  confidence={r.confidence}  safety={r.safety_flag}  ACTION={r.action}")
