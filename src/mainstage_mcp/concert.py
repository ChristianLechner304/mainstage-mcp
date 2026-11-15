"""Read and modify MainStage concert packages (.concert).

Layout of a MainStage 3.2+ concert (all folders are macOS "packages"):

    My Concert.concert/
        data.plist                 window/document settings
        Concert.patch/
            data.plist             concert-level channels + ordered list of nodes
            <Patch name>.patch/    one folder per patch (or set, which nests nodes)
                data.plist         patch settings (name, tempo, ...) + channel list
                <Channel>.cst      one channel strip file per channel

All plists are binary property lists and are written back as such.
"""
from __future__ import annotations

import copy
import math
import os
import plistlib
import shutil
import time
import uuid
from dataclasses import dataclass, field

from . import cst


class ConcertError(RuntimeError):
    pass


def _load(path: str):
    with open(path, "rb") as f:
        return plistlib.load(f)


def _save(path: str, data) -> None:
    tmp = path + ".tmp-mainstage-mcp"
    with open(tmp, "wb") as f:
        plistlib.dump(data, f, fmt=plistlib.FMT_BINARY, sort_keys=False)
    os.replace(tmp, path)


def _safe_name(name: str) -> str:
    bad = '/:\\'
    out = "".join("-" if c in bad else c for c in name).strip()
    if not out or out.startswith("."):
        raise ConcertError(f"invalid name: {name!r}")
    return out


@dataclass
class PatchRef:
    name: str
    folder: str           # absolute path of the .patch folder
    node: str             # node name as stored in the parent's node list
    parent: str           # absolute path of the parent folder (Concert.patch or set)
    is_set: bool
    depth: int
    children: list = field(default_factory=list)


class Concert:
    def __init__(self, path: str, backup_dir: str | None = None):
        path = os.path.abspath(os.path.expanduser(path))
        if not path.endswith(".concert"):
            path += ".concert"
        self.path = path
        self.root = os.path.join(path, "Concert.patch")
        if not os.path.isfile(os.path.join(self.root, "data.plist")):
            raise ConcertError(f"not a MainStage 3.2+ concert: {path}")
        self.backup_dir = backup_dir

    @property
    def name(self) -> str:
        return os.path.basename(self.path)[: -len(".concert")]

    # ------------------------------------------------------------- reading
    def root_data(self) -> dict:
        return _load(os.path.join(self.root, "data.plist"))

    def _walk(self, folder: str, depth: int = 0) -> list[PatchRef]:
        data = _load(os.path.join(folder, "data.plist"))
        refs = []
        for node in data.get("nodes", []):
            nf = os.path.join(folder, node)
            dp = os.path.join(nf, "data.plist")
            if not os.path.isfile(dp):
                continue
            d = _load(dp)
            name = d.get("patch", {}).get("engineNode", {}).get("name") or node[:-6]
            is_set = "nodes" in d
            ref = PatchRef(name, nf, node, folder, is_set, depth)
            if is_set:
                ref.children = self._walk(nf, depth + 1)
            refs.append(ref)
        return refs

    def tree(self) -> list[PatchRef]:
        return self._walk(self.root)

    def all_patches(self) -> list[PatchRef]:
        out = []

        def rec(refs):
            for r in refs:
                if r.is_set:
                    rec(r.children)
                else:
                    out.append(r)
        rec(self.tree())
        return out

    def find_patch(self, name: str) -> PatchRef:
        patches = self.all_patches()
        for p in patches:
            if p.name == name:
                return p
        low = name.lower()
        hits = [p for p in patches if p.name.lower() == low] or \
               [p for p in patches if low in p.name.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ConcertError(f'patch "{name}" not found in {self.name}')
        raise ConcertError(f'"{name}" is ambiguous: ' + ", ".join(h.name for h in hits))

    def patch_info(self, ref: PatchRef) -> dict:
        d = _load(os.path.join(ref.folder, "data.plist"))
        en = d["patch"]["engineNode"]
        info = {
            "name": ref.name,
            "program_change": en.get("patchChangeNum") if en.get("hasProgramChange") else None,
            "tempo": en.get("tempo") if en.get("hasTempo") else None,
            "time_signature": [en.get("TimeSignatureNumerator", 4),
                               2 ** en.get("TimeSignatureDenominator", 2)]
            if en.get("hasTimeSignature") else None,
            "transpose": en.get("globalTranspose", 0),
            "channels": [],
        }
        for c in d.get("channels", []):
            entry = {
                "name": c.get("Channel_name"),
                "sound": c.get("Channel_chaStrName"),
                "category": c.get("Channel_chaStrCategory"),
                "file": c.get("Filename"),
            }
            p = os.path.join(ref.folder, c.get("Filename", ""))
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    raw = f.read()
                try:
                    h = cst.read_header(raw, p)
                    entry.update(volume_db=h.volume_db, pan=h.pan, muted=h.muted)
                except cst.CstError:
                    entry.update(volume_db=None)
                fr = cst.find_file_ref(raw)
                if fr is not None:
                    entry["audio_file"] = fr.url
            info["channels"].append(entry)
        return info

    # ------------------------------------------------------------- helpers
    def _max_ids(self) -> tuple[int, int]:
        max_id, max_pc = 0, -1
        for c in self.root_data().get("channels", []):
            max_id = max(max_id, c.get("Channel_instID", 0))
        for p in self.all_patches():
            d = _load(os.path.join(p.folder, "data.plist"))
            for c in d.get("channels", []):
                max_id = max(max_id, c.get("Channel_instID", 0))
            en = d["patch"]["engineNode"]
            if en.get("hasProgramChange"):
                max_pc = max(max_pc, en.get("patchChangeNum", 0))
        return max_id, max_pc

    def _template_patch(self) -> dict:
        patches = self.all_patches()
        if not patches:
            raise ConcertError("the concert needs at least one existing patch to use as a template")
        for p in patches:
            d = _load(os.path.join(p.folder, "data.plist"))
            if d.get("channels"):
                return d
        raise ConcertError("no patch with a channel strip found to use as a template")

    def backup(self, paths: list[str]) -> str | None:
        """Copy the given files/folders (inside the concert) before changing them."""
        if not self.backup_dir:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest_root = os.path.join(self.backup_dir, f"{self.name}-{stamp}")
        for src in paths:
            if not os.path.exists(src):
                continue
            rel = os.path.relpath(src, self.path)
            dst = os.path.join(dest_root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        return dest_root

    @staticmethod
    def _unique_filename(folder: str, base: str, used: set[str]) -> str:
        base = _safe_name(base)
        fn, i = base + ".cst", 2
        while fn in used or os.path.exists(os.path.join(folder, fn)):
            fn = f"{base} {i}.cst"
            i += 1
        used.add(fn)
        return fn

    # ------------------------------------------------------------- writing
    def create_patch(self, name: str, channels: list[dict], *, tempo: float | None = None,
                     time_signature: tuple[int, int] | None = None, transpose: int = 0,
                     position: int | None = None) -> dict:
        """Create a new top-level patch.

        Each channel dict needs ``source_cst`` (path to a channel strip file)
        and may contain ``label``, ``volume_db``, ``pan``, ``muted`` and
        ``meta`` (data.plist keys such as Channel_chaStrName to set).
        """
        if not channels:
            raise ConcertError("a patch needs at least one channel")
        name = _safe_name(name)
        folder_name = name + ".patch"
        root_path = os.path.join(self.root, "data.plist")
        root = self.root_data()
        nodes = root["nodes"]
        if folder_name in nodes or os.path.exists(os.path.join(self.root, folder_name)):
            raise ConcertError(f'a patch called "{name}" already exists')
        if any(p.name == name for p in self.all_patches()):
            raise ConcertError(f'a patch called "{name}" already exists')

        template = self._template_patch()
        max_id, max_pc = self._max_ids()
        self.backup([root_path])

        pdir = os.path.join(self.root, folder_name)
        os.makedirs(pdir)
        try:
            tch = template["channels"][0]
            new_channels, used = [], set()
            for ch in channels:
                label = ch.get("label") or ch.get("meta", {}).get("Channel_chaStrName") or "Channel"
                fn = self._unique_filename(pdir, label, used)
                dst = os.path.join(pdir, fn)
                with open(ch["source_cst"], "rb") as f:
                    raw = bytearray(f.read())
                if ch.get("transform"):
                    raw = bytearray(ch["transform"](bytes(raw)))
                hdr = cst.write_header(raw, volume_db=ch.get("volume_db", 0.0), pan=ch.get("pan", 0.0),
                                       muted=bool(ch.get("muted", False)), solo=False, path=dst)
                with open(dst, "wb") as f:
                    f.write(raw)
                max_id += 4
                c = copy.deepcopy(ch.get("plist_template") or tch)
                c.pop("Channel_chaStrFullPath", None)
                c.update({
                    "Filename": fn, "Root": False, "UUID": str(uuid.uuid4()).upper(),
                    "Channel_instID": max_id, "Channel_name": label, "Custom_name": True,
                    "Channel_isSolo": False, "Channel_userDidModifySmartControls": False,
                })
                c.update(ch.get("meta", {}))
                c.update(hdr)
                new_channels.append(c)

            d = copy.deepcopy(template)
            d["channels"] = new_channels
            p = d["patch"]
            p["selected"] = False
            p["patchMappings"] = {}
            en = p["engineNode"]
            en["name"] = name
            en["hasTempo"] = tempo is not None
            if tempo is not None:
                en["tempo"] = float(tempo)
            en["hasTimeSignature"] = time_signature is not None
            if time_signature is not None:
                num, den = time_signature
                if den not in (1, 2, 4, 8, 16, 32):
                    raise ConcertError("time signature denominator must be a power of two")
                en["TimeSignatureNumerator"] = int(num)
                en["TimeSignatureDenominator"] = int(math.log2(den))
            en["hasProgramChange"] = True
            en["patchChangeNum"] = max_pc + 1
            en["globalTranspose"] = int(transpose)
            _save(os.path.join(pdir, "data.plist"), d)
        except Exception:
            shutil.rmtree(pdir, ignore_errors=True)
            raise

        if position is None or position >= len(nodes):
            nodes.append(folder_name)
        else:
            nodes.insert(max(0, int(position)), folder_name)
        _save(root_path, root)
        return {"patch": name, "program_change": max_pc + 1,
                "channels": [c["Filename"] for c in new_channels]}

    def add_channel(self, patch: str, ch: dict) -> dict:
        """Append one channel strip to an existing patch (same keys as create_patch)."""
        ref = self.find_patch(patch)
        dp = os.path.join(ref.folder, "data.plist")
        d = _load(dp)
        if not d.get("channels") and not ch.get("plist_template"):
            raise ConcertError("patch has no channel to copy settings from")
        max_id, _ = self._max_ids()
        self.backup([dp])
        used = {c.get("Filename") for c in d["channels"]}
        label = ch.get("label") or ch.get("meta", {}).get("Channel_chaStrName") or "Channel"
        fn = self._unique_filename(ref.folder, label, used)
        dst = os.path.join(ref.folder, fn)
        with open(ch["source_cst"], "rb") as f:
            raw = bytearray(f.read())
        if ch.get("transform"):
            raw = bytearray(ch["transform"](bytes(raw)))
        hdr = cst.write_header(raw, volume_db=ch.get("volume_db", 0.0), pan=ch.get("pan", 0.0),
                               muted=bool(ch.get("muted", False)), solo=False, path=dst)
        with open(dst, "wb") as f:
            f.write(raw)
        c = copy.deepcopy(ch.get("plist_template") or d["channels"][0])
        c.pop("Channel_chaStrFullPath", None)
        c.update({"Filename": fn, "Root": False, "UUID": str(uuid.uuid4()).upper(),
                  "Channel_instID": max_id + 4, "Channel_name": label, "Custom_name": True,
                  "Channel_isSolo": False})
        c.update(ch.get("meta", {}))
        c.update(hdr)
        d["channels"].append(c)
        _save(dp, d)
        return self.patch_info(ref)

    def set_patch(self, patch: str, *, tempo: float | None = None, clear_tempo: bool = False,
                  time_signature: tuple[int, int] | None = None, transpose: int | None = None) -> dict:
        ref = self.find_patch(patch)
        dp = os.path.join(ref.folder, "data.plist")
        self.backup([dp])
        d = _load(dp)
        en = d["patch"]["engineNode"]
        if clear_tempo:
            en["hasTempo"] = False
        if tempo is not None:
            en["hasTempo"] = True
            en["tempo"] = float(tempo)
        if time_signature is not None:
            num, den = time_signature
            en["hasTimeSignature"] = True
            en["TimeSignatureNumerator"] = int(num)
            en["TimeSignatureDenominator"] = int(math.log2(den))
        if transpose is not None:
            en["globalTranspose"] = int(transpose)
        _save(dp, d)
        return self.patch_info(ref)

    def set_channel(self, patch: str, channel: str, *, volume_db: float | None = None,
                    pan: float | None = None, muted: bool | None = None) -> dict:
        ref = self.find_patch(patch)
        dp = os.path.join(ref.folder, "data.plist")
        d = _load(dp)
        chans = d.get("channels", [])
        low = channel.lower()
        hits = [c for c in chans if (c.get("Channel_name") or "").lower() == low] or \
               [c for c in chans if low in (c.get("Channel_name") or "").lower()
                or low in (c.get("Channel_chaStrName") or "").lower()]
        if not hits and channel.isdigit() and 1 <= int(channel) <= len(chans):
            hits = [chans[int(channel) - 1]]
        if len(hits) != 1:
            names = ", ".join(c.get("Channel_name", "?") for c in chans)
            raise ConcertError(f'channel "{channel}" not found or ambiguous. Channels: {names}')
        c = hits[0]
        cp = os.path.join(ref.folder, c["Filename"])
        self.backup([dp, cp])
        c.update(cst.edit_file(cp, volume_db=volume_db, pan=pan, muted=muted))
        _save(dp, d)
        return self.patch_info(ref)
