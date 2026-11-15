"""Low-level access to MainStage / Logic Pro channel strip files (.cst).

The .cst format is undocumented. The offsets below were found by comparing
channel strips saved by MainStage 3.x before and after changing a single
parameter. Every write is guarded by a sanity check so that an unknown layout
is rejected instead of silently corrupting a file.
"""
from __future__ import annotations

import math
import plistlib
import struct
from dataclasses import dataclass

MAGIC = b"OCuA"

# Channel header (fixed offsets from the start of the file)
OFF_VOL_INT = 121   # integer part of the fader value (0..127)
OFF_SOLO = 124      # 1 = solo
OFF_PAN = 125       # 0..127, 64 = centre
OFF_MUTE = 126      # 1 = muted
OFF_VOL_FIX = 152   # fader value as unsigned 8.24 fixed point, little endian

FADER_MAX = 127.0   # +6 dB
FADER_UNITY = 90.0  # 0 dB


class CstError(ValueError):
    """Raised when a channel strip file does not look like we expect."""


# ---------------------------------------------------------------- fader math
def db_to_fader(db: float) -> float:
    """Logic/MainStage fader law: dB = 40 * log10(value / 90)."""
    if db <= -96:
        return 0.0
    return min(FADER_MAX, FADER_UNITY * 10 ** (db / 40.0))


def fader_to_db(value: float) -> float:
    if value <= 0:
        return -math.inf
    return 40.0 * math.log10(value / FADER_UNITY)


def fader_to_fixed(value: float) -> int:
    return min(int(round(value * 2 ** 24)), int(FADER_MAX) << 24)


def fixed_to_fader(fixed: int) -> float:
    return fixed / 2 ** 24


def pan_to_byte(pan: float) -> int:
    pan = max(-1.0, min(1.0, float(pan)))
    return 64 + (round(pan * 63) if pan >= 0 else round(pan * 64))


def byte_to_pan(b: int) -> float:
    v = b - 64
    return v / 63.0 if v >= 0 else v / 64.0


# ------------------------------------------------------------ header access
@dataclass
class ChannelHeader:
    volume_db: float
    fader: float
    pan: float
    muted: bool
    solo: bool


def _check(data: bytes | bytearray, path: str = "") -> int:
    if len(data) < OFF_VOL_FIX + 4 or data[:4] != MAGIC:
        raise CstError(f"{path or 'data'}: not a channel strip file")
    fixed = struct.unpack_from("<I", data, OFF_VOL_FIX)[0]
    if data[OFF_VOL_INT] != fixed >> 24 or (fixed >> 24) > FADER_MAX:
        raise CstError(f"{path or 'data'}: unknown channel strip layout, refusing to edit")
    return fixed


def read_header(data: bytes | bytearray, path: str = "") -> ChannelHeader:
    fixed = _check(data, path)
    fader = fixed_to_fader(fixed)
    return ChannelHeader(
        volume_db=round(fader_to_db(fader), 2),
        fader=fader,
        pan=round(byte_to_pan(data[OFF_PAN]), 3),
        muted=bool(data[OFF_MUTE]),
        solo=bool(data[OFF_SOLO]),
    )


def write_header(data: bytearray, *, volume_db: float | None = None, pan: float | None = None,
                 muted: bool | None = None, solo: bool | None = None, path: str = "") -> dict:
    """Modify the header in place. Returns the matching data.plist channel keys."""
    _check(data, path)
    plist: dict = {}
    if volume_db is not None:
        fixed = fader_to_fixed(db_to_fader(volume_db))
        struct.pack_into("<I", data, OFF_VOL_FIX, fixed)
        data[OFF_VOL_INT] = fixed >> 24
        plist["volume"] = fixed
    if pan is not None:
        data[OFF_PAN] = pan_to_byte(pan)
        plist["Channel_pan"] = max(-1.0, min(1.0, float(pan)))
    if muted is not None:
        data[OFF_MUTE] = 1 if muted else 0
        plist["Channel_isMuted"] = bool(muted)
    if solo is not None:
        data[OFF_SOLO] = 1 if solo else 0
        plist["Channel_isSolo"] = bool(solo)
    return plist


def edit_file(path: str, **kwargs) -> dict:
    with open(path, "rb") as f:
        data = bytearray(f.read())
    plist = write_header(data, path=path, **kwargs)
    with open(path, "wb") as f:
        f.write(data)
    return plist


# ------------------------------------------------------- file reference chunk
FILE_TAG = b"ELIF"   # "FILE" little endian; holds a bplist with bookmark + URL


@dataclass
class FileRef:
    offset: int          # offset of the ELIF tag
    length: int          # total chunk length incl. 8 byte header
    url: str
    bookmark: bytes


def find_file_ref(data: bytes) -> FileRef | None:
    i = data.find(FILE_TAG)
    if i < 0:
        return None
    length = struct.unpack_from("<I", data, i + 4)[0]
    try:
        p = plistlib.loads(bytes(data[i + 8: i + length]))
    except Exception as exc:  # pragma: no cover - defensive
        raise CstError(f"file reference chunk is not readable: {exc}") from exc
    return FileRef(i, length, p.get("CFileRef_URL", ""), p.get("CFileRef_Bookmark", b""))


def replace_file_ref(data: bytes, url: str, bookmark: bytes, length_fields: list[int]) -> bytes:
    """Swap the audio file reference of a (Playback) channel strip.

    ``length_fields`` are offsets of little-endian uint32 size fields that
    enclose the file chunk and must grow/shrink with it. They are found by
    :func:`detect_length_fields` on a known-good template.
    """
    ref = find_file_ref(data)
    if ref is None:
        raise CstError("channel strip has no file reference")
    payload = plistlib.dumps({"CFileRef_Bookmark": bookmark, "CFileRef_URL": url},
                             fmt=plistlib.FMT_BINARY)
    new_chunk = FILE_TAG + struct.pack("<I", len(payload) + 8) + payload
    delta = len(new_chunk) - ref.length
    out = bytearray(data[: ref.offset]) + new_chunk + data[ref.offset + ref.length:]
    for off in length_fields:
        v = struct.unpack_from("<I", out, off)[0]
        struct.pack_into("<I", out, off, v + delta)
    return bytes(out)


def detect_length_fields(data: bytes) -> list[int]:
    """Find uint32 size fields before the file chunk that point just past it.

    A size field at offset ``o`` with value ``v`` is accepted when ``o + v``
    lands within a few bytes of the end of the file chunk; this matches the
    nested chunk headers MainStage writes around plug-in state.
    """
    ref = find_file_ref(data)
    if ref is None:
        raise CstError("channel strip has no file reference")
    end = ref.offset + ref.length
    fields = []
    for o in range(0, ref.offset - 3):
        v = struct.unpack_from("<I", data, o)[0]
        if v < 64 or v > len(data):
            continue
        rel = o + v - end
        if -32 <= rel <= 32 and o + v <= len(data):
            fields.append((o, rel))
    return [o for o, _ in fields]
