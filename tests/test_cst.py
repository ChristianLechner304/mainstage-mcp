import plistlib
import struct

import pytest

from mainstage_mcp import cst


def fake_strip(fader=90.0, pan=64, mute=0, with_file=False, url="file:///a.mp3"):
    data = bytearray(cst.MAGIC + bytes(400))
    fixed = cst.fader_to_fixed(fader)
    struct.pack_into("<I", data, cst.OFF_VOL_FIX, fixed)
    data[cst.OFF_VOL_INT] = fixed >> 24
    data[cst.OFF_PAN] = pan
    data[cst.OFF_MUTE] = mute
    if with_file:
        payload = plistlib.dumps({"CFileRef_Bookmark": b"book", "CFileRef_URL": url},
                                 fmt=plistlib.FMT_BINARY)
        chunk = cst.FILE_TAG + struct.pack("<I", len(payload) + 8) + payload
        start = len(data)
        end = start + len(chunk)
        struct.pack_into("<I", data, 300, end - 300)  # enclosing size field
        data += chunk + b"tail"
    return data


@pytest.mark.parametrize("db,value", [(0, 90.0), (6, 127.0), (-6, 63.72), (-10, 50.61)])
def test_fader_law(db, value):
    assert cst.db_to_fader(db) == pytest.approx(value, abs=0.05)
    assert cst.fader_to_db(cst.db_to_fader(db)) == pytest.approx(db, abs=0.05)


def test_fader_is_clamped():
    assert cst.db_to_fader(12) == 127.0
    assert cst.db_to_fader(-200) == 0.0


def test_header_roundtrip():
    data = fake_strip(fader=127.0)
    plist = cst.write_header(data, volume_db=-3, pan=1.0, muted=True)
    h = cst.read_header(data)
    assert h.volume_db == pytest.approx(-3, abs=0.01)
    assert h.pan == 1.0 and h.muted
    assert plist["Channel_isMuted"] is True
    assert plist["volume"] == struct.unpack_from("<I", data, cst.OFF_VOL_FIX)[0]


def test_rejects_unknown_layout():
    data = fake_strip()
    data[cst.OFF_VOL_INT] = 3
    with pytest.raises(cst.CstError):
        cst.write_header(data, volume_db=0)
    with pytest.raises(cst.CstError):
        cst.read_header(b"nope" + bytes(200))


def test_replace_file_ref_updates_sizes():
    data = bytes(fake_strip(with_file=True))
    fields = cst.detect_length_fields(data)
    assert 300 in fields
    long_url = "file:///Users/x/" + "very%20long%20name/" * 10 + "song.mp3"
    new = cst.replace_file_ref(data, long_url, b"bookmark-data", fields)
    ref = cst.find_file_ref(new)
    assert ref.url == long_url and ref.bookmark == b"bookmark-data"
    assert 300 + struct.unpack_from("<I", new, 300)[0] == ref.offset + ref.length
    assert new.endswith(b"tail")
