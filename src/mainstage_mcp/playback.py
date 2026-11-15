"""Playback channel strips: find a template, locate audio files, build new strips."""
from __future__ import annotations

import os
import plistlib
import re
import struct
import unicodedata
from dataclasses import dataclass

from . import cst

AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aif", ".aiff", ".caf", ".flac", ".aac")


@dataclass
class PlaybackTemplate:
    cst_path: str
    plist_channel: dict | None   # channel entry from the patch that contained it
    length_fields: list[int]


def _is_playback(raw: bytes) -> bool:
    return raw[:4] == cst.MAGIC and b"Playback" in raw[:2000] and cst.find_file_ref(raw) is not None


# Size fields that enclose the file chunk, relative to the position of the
# "Playback" plug-in name. Observed in MainStage 3.6/3.7 channel strips:
#   -128  channel strip slot chunk
#   +32 / +52  plug-in state chunk (common layout)
#   +880  plug-in state chunk (layout with extended plug-in data)
KNOWN_FIELD_OFFSETS = (-128, 32, 52, 880)


def _length_fields(raw: bytes) -> list[int]:
    pb = raw.find(b"Playback")
    ref = cst.find_file_ref(raw)
    end = ref.offset + ref.length
    fields = [o for o in cst.detect_length_fields(raw) if (o - pb) in KNOWN_FIELD_OFFSETS]
    exact = [o for o in fields if o + struct.unpack_from("<I", raw, o)[0] == end]
    if len(fields) < 2 or not exact:
        raise ValueError("unknown Playback channel strip layout")
    return fields


def load_template(path: str) -> PlaybackTemplate:
    with open(path, "rb") as f:
        raw = f.read()
    if not _is_playback(raw):
        raise ValueError(f"{path} is not a Playback channel strip with an audio file")
    fields = _length_fields(raw)
    plist_channel = None
    dp = os.path.join(os.path.dirname(path), "data.plist")
    if os.path.isfile(dp):
        try:
            with open(dp, "rb") as f:
                for c in plistlib.load(f).get("channels", []):
                    if c.get("Filename") == os.path.basename(path):
                        plist_channel = c
        except Exception:
            pass
    return PlaybackTemplate(path, plist_channel, fields)


def find_template(search_dirs: list[str], explicit: str | None = None) -> PlaybackTemplate:
    """Use an explicit template or the first Playback strip found in existing concerts."""
    if explicit:
        return load_template(os.path.expanduser(explicit))
    fallback = None
    for base in search_dirs:
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, files in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and d not in ("Samples", "Sampler Instruments", "Alchemy Samples")]
            for fn in files:
                if not fn.endswith(".cst"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, "rb") as f:
                        head = f.read(4)
                        if head != cst.MAGIC:
                            continue
                        raw = head + f.read()
                    if _is_playback(raw):
                        tpl = load_template(p)
                        pb = raw.find(b"Playback")
                        if any(o - pb == 52 for o in tpl.length_fields):
                            return tpl          # preferred: most common layout
                        fallback = fallback or tpl
                except (OSError, cst.CstError, ValueError):
                    continue
    if fallback:
        return fallback
    raise FileNotFoundError(
        "No Playback channel strip template found. Create one patch in any concert with the "
        "Playback plug-in and an audio file loaded, save it, and try again "
        "(or set MAINSTAGE_PLAYBACK_TEMPLATE to that .cst file).")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def find_audio_files(directory: str, query: str = "", limit: int = 20, max_depth: int = 6) -> list[dict]:
    directory = os.path.abspath(os.path.expanduser(directory))
    if not os.path.isdir(directory):
        raise FileNotFoundError(directory)
    words = _norm(query).split()
    out = []
    base_depth = directory.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, files in os.walk(directory):
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.endswith((".concert", ".patch"))]
        for fn in files:
            if not fn.lower().endswith(AUDIO_EXT):
                continue
            n = _norm(fn)
            if words and not all(w in n for w in words):
                continue
            p = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            out.append({"path": p, "name": fn, "size_mb": round(size / 1e6, 1)})
    out.sort(key=lambda d: (len(d["name"]), d["name"]))
    return out[:limit]


def make_transform(template: PlaybackTemplate, url: str, bookmark: bytes):
    def transform(raw: bytes) -> bytes:
        return cst.replace_file_ref(raw, url, bookmark, template.length_fields)
    return transform
