"""Search-term expansion so that e.g. "Flöte" also finds "Flute" or "Woodwind".

Each group lists words that mean (roughly) the same instrument. A query word
matches a sound if any word of its group occurs in the sound's name or category.
German and English terms are included; extend freely.
"""
from __future__ import annotations

import re
import unicodedata

GROUPS: list[set[str]] = [
    {"flute", "flöte", "floete", "flutes", "piccolo", "pan flute", "panflöte", "recorder", "blockflöte", "woodwind"},
    {"piano", "klavier", "flügel", "fluegel", "grand", "upright"},
    {"electric piano", "e-piano", "epiano", "rhodes", "wurlitzer", "wurli", "suitcase", "ep"},
    {"organ", "orgel", "b3", "hammond", "tonewheel", "drawbar", "church organ", "kirchenorgel", "pipe organ"},
    {"strings", "streicher", "string", "violin", "violine", "geige", "viola", "bratsche", "cello"},
    {"brass", "bläser", "blaeser", "blech", "horn", "horns", "hörner"},
    {"trumpet", "trompete"}, {"trombone", "posaune"}, {"tuba"}, {"french horn", "waldhorn"},
    {"sax", "saxophon", "saxophone", "saxofon"}, {"clarinet", "klarinette"}, {"oboe"}, {"bassoon", "fagott"},
    {"choir", "chor", "voices", "stimmen", "vocal", "vox", "aah", "ooh"},
    {"pad", "fläche", "flaeche", "flächen", "atmosphere", "ambient"},
    {"lead", "solo", "melodie"},
    {"synth", "synthesizer", "analog", "poly"},
    {"bass", "bässe"},
    {"bell", "bells", "glocke", "glocken", "glockenspiel", "chime", "chimes", "celesta", "celeste"},
    {"mallet", "marimba", "vibraphone", "vibraphon", "xylophone", "xylophon", "vibes"},
    {"harp", "harfe"}, {"accordion", "akkordeon", "ziehharmonika", "harmonika", "musette"},
    {"harmonica", "mundharmonika", "blues harp"},
    {"guitar", "gitarre", "acoustic guitar", "akustikgitarre"},
    {"clavinet", "clavi", "clav"}, {"harpsichord", "cembalo"},
    {"drums", "schlagzeug", "drum kit", "percussion", "perkussion"},
    {"steel drum", "steeldrum", "steel pan"},
    {"sitar"}, {"banjo"}, {"mandolin", "mandoline"}, {"ukulele"},
]


def norm(s: str) -> str:
    s = s.lower().replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


_INDEX: dict[str, set[str]] = {}
for g in GROUPS:
    ng = {norm(w) for w in g}
    for w in ng:
        _INDEX.setdefault(w, set()).update(ng)


def expand(word: str) -> set[str]:
    w = norm(word)
    out = {w} | _INDEX.get(w, set())
    if w.endswith("s") and w[:-1] in _INDEX:
        out |= _INDEX[w[:-1]]
    return out


def _contains(hay: str, term: str) -> bool:
    """Whole-word match, allowing plural endings ("flute" ~ "flutes", "glocke" ~ "glocken")."""
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?:s|es|n|en)?(?![a-z0-9])", hay) is not None


def matches(query: str, haystack: str) -> tuple[bool, int]:
    """All query words must match (via synonyms). Returns (match, score)."""
    hay = norm(haystack)
    words = [w for w in norm(query).split() if w]
    if not words:
        return True, 0
    score = 0
    for w in words:
        alts = expand(w)
        hit = [a for a in alts if _contains(hay, a)]
        if not hit:
            return False, 0
        score += 3 if norm(w) in hay else 2
    return True, score
