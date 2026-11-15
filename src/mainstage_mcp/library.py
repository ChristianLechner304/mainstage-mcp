"""Sound catalog built from the Logic Pro / MainStage patch library.

The library contains one folder per patch (``Name.patch``) with a
``data.plist`` and a ``#Root.cst`` channel strip. Only single channel-strip
patches are offered, because summing stacks (several channel strips plus
busses) cannot be copied as a single channel safely.
"""
from __future__ import annotations

import os
import plistlib
import re
import threading
from dataclasses import dataclass, asdict


@dataclass
class Sound:
    name: str
    category: str      # e.g. "Synthesizer/Brass"
    kind: str          # "Instrument" or "Audio"
    path: str          # absolute path of the .patch folder
    library: str       # library root it came from
    rel: str           # path relative to the library root (used for @BASE@ references)
    family: str = ""   # channel strip category stored by Apple, e.g. "Vintage B3 Organ"

    @property
    def cst(self) -> str:
        return os.path.join(self.path, "#Root.cst")

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("library")
        return d


class SoundLibrary:
    def __init__(self, roots: list[str]):
        self.roots = [os.path.abspath(os.path.expanduser(r)) for r in roots]
        self._sounds: list[Sound] | None = None
        self._lock = threading.Lock()

    def refresh(self) -> int:
        with self._lock:
            self._sounds = list(self._scan())
            return len(self._sounds)

    @property
    def sounds(self) -> list[Sound]:
        if self._sounds is None:
            self.refresh()
        return self._sounds or []

    def _scan(self):
        seen = set()
        for root in self.roots:
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, _ in os.walk(root):
                for d in list(dirnames):
                    if not d.endswith(".patch"):
                        continue
                    dirnames.remove(d)          # do not descend into patch packages
                    p = os.path.join(dirpath, d)
                    if not os.path.isfile(os.path.join(p, "#Root.cst")):
                        continue
                    try:
                        with open(os.path.join(p, "data.plist"), "rb") as f:
                            data = plistlib.load(f)
                    except Exception:
                        continue
                    if len(data.get("channels", [])) != 1 or "patch" in data:
                        continue
                    rel = os.path.relpath(p, root)
                    parts = rel.split(os.sep)
                    kind = parts[0] if len(parts) > 1 else ""
                    category = "/".join(parts[1:-1]) if len(parts) > 2 else ""
                    name = data["channels"][0].get("Channel_name") or d[:-6]
                    key = (name, category)
                    if key in seen:
                        continue
                    seen.add(key)
                    family = data["channels"][0].get("Channel_chaStrCategory", "") or ""
                    yield Sound(name, category, kind, p, root, rel, family)

    def search(self, query: str = "", category: str = "", kind: str = "Instrument",
               limit: int = 25) -> list[Sound]:
        words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
        cat = category.lower().strip()
        scored = []
        for s in self.sounds:
            if kind and s.kind.lower() != kind.lower():
                continue
            hay_cat = s.category.lower()
            if cat and cat not in hay_cat:
                continue
            hay = f"{s.name} {s.category} {s.family}".lower()
            if words and not all(w in hay for w in words):
                continue
            score = sum(3 if w in s.name.lower() else 1 for w in words)
            if "legacy" in hay_cat:
                score -= 2
            scored.append((-score, s.name, s))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [s for _, _, s in scored[:limit]]

    def categories(self, kind: str = "Instrument") -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.sounds:
            if kind and s.kind.lower() != kind.lower():
                continue
            out[s.category] = out.get(s.category, 0) + 1
        return dict(sorted(out.items()))

    def get(self, name_or_rel: str) -> Sound:
        key = name_or_rel.strip()
        for s in self.sounds:
            if s.rel == key or s.path == key:
                return s
        exact = [s for s in self.sounds if s.name.lower() == key.lower()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            non_legacy = [s for s in exact if "legacy" not in s.category.lower()]
            if len(non_legacy) == 1:
                return non_legacy[0]
            raise KeyError(f'"{name_or_rel}" is ambiguous, use one of: ' +
                           ", ".join(s.rel for s in exact))
        raise KeyError(f'sound "{name_or_rel}" not found, use search_sounds first')

    def plist_meta(self, s: Sound) -> dict:
        with open(os.path.join(s.path, "data.plist"), "rb") as f:
            c = plistlib.load(f)["channels"][0]
        meta = {
            "Channel_chaStrName": c.get("Channel_name", s.name),
            "Channel_chaStrCategory": c.get("Channel_chaStrCategory", ""),
            "Channel_chaStrFullPath": "@BASE@/" + s.rel.replace(os.sep, "/") + "/#Root.cst",
        }
        if "Track_icon" in c:
            meta["Track_icon"] = c["Track_icon"]
        return meta


def list_plugins(dirs: list[str]) -> list[dict]:
    """Installed Audio Unit / VST plug-ins (names only)."""
    out = []
    for d in dirs:
        d = os.path.expanduser(d)
        for fmt, ext in (("Components", ".component"), ("VST3", ".vst3"), ("VST", ".vst")):
            p = os.path.join(d, fmt)
            if not os.path.isdir(p):
                continue
            for n in sorted(os.listdir(p)):
                if n.endswith(ext):
                    out.append({"name": n[: -len(ext)], "format": "AU" if fmt == "Components" else fmt,
                                "location": p})
    return out
