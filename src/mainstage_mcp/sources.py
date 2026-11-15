"""Answer "where can I find a sound like X?" across all known places."""
from __future__ import annotations

import os
import plistlib

from . import synonyms


def _load(path: str):
    with open(path, "rb") as f:
        return plistlib.load(f)


def _channels_of_patch_folder(folder: str):
    try:
        d = _load(os.path.join(folder, "data.plist"))
    except Exception:
        return None, []
    name = d.get("patch", {}).get("engineNode", {}).get("name") or os.path.basename(folder)[:-6]
    return d, [(name, c) for c in d.get("channels", [])]


def _walk_nodes(folder: str, trail: list[str]):
    """Yield (set/patch trail, patch name, channel dict) for a concert or set folder."""
    try:
        data = _load(os.path.join(folder, "data.plist"))
    except Exception:
        return
    for node in data.get("nodes", []):
        nf = os.path.join(folder, node)
        d, chans = _channels_of_patch_folder(nf)
        if d is None:
            continue
        if "nodes" in d:
            setname = d.get("patch", {}).get("engineNode", {}).get("name") or node[:-6]
            yield from _walk_nodes(nf, trail + [setname])
        else:
            for pname, c in chans:
                yield trail, pname, c


def _channel_text(c: dict) -> str:
    return " ".join(str(c.get(k, "")) for k in
                    ("Channel_name", "Channel_chaStrName", "Channel_chaStrCategory", "Channel_chaStrFullPath"))


def search_concerts(query: str, concert_files: list[str], limit: int = 30) -> list[dict]:
    """Channel strips in your existing concerts whose sound/name matches."""
    hits = []
    for cf in concert_files:
        root = os.path.join(cf, "Concert.patch")
        if not os.path.isdir(root):
            continue
        cname = os.path.basename(cf)[:-8]
        for trail, pname, c in _walk_nodes(root, []):
            ok, score = synonyms.matches(query, _channel_text(c))
            if ok:
                hits.append((-score, {
                    "concert": cname, "set": "/".join(trail) or None, "patch": pname,
                    "channel": c.get("Channel_name"), "sound": c.get("Channel_chaStrName"),
                    "category": c.get("Channel_chaStrCategory")}))
    hits.sort(key=lambda t: t[0])
    return [h for _, h in hits[:limit]]


def search_patch_files(query: str, dirs: list[str], limit: int = 20) -> list[dict]:
    """Exported MainStage patch files (.patch outside concerts), e.g. saved favourites."""
    hits = []
    for base in dirs:
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, _ in os.walk(base):
            keep = []
            for d in dirnames:
                p = os.path.join(dirpath, d)
                if d.endswith(".concert") or d.startswith("."):
                    continue
                if d.endswith(".patch"):
                    data, chans = _channels_of_patch_folder(p)
                    if data is None or "patch" not in data:
                        continue  # library patch or broken; library is searched separately
                    text = d[:-6] + " " + " ".join(_channel_text(c) for _, c in chans)
                    ok, score = synonyms.matches(query, text)
                    if ok:
                        hits.append((-score, {"file": p, "name": d[:-6],
                                              "channels": [c.get("Channel_name") for _, c in chans]}))
                    continue
                keep.append(d)
            dirnames[:] = keep
    hits.sort(key=lambda t: t[0])
    return [h for _, h in hits[:limit]]


def search_plugins(query: str, plugins: list[dict]) -> list[dict]:
    return [p for p in plugins if synonyms.matches(query, p["name"])[0]]
