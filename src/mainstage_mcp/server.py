"""MCP server for Apple MainStage.

Lets an AI assistant inspect concerts, search the sound library and create
song patches (sounds, tempo, time signature, fader/pan/mute, Playback tracks)
by editing the concert package on disk while MainStage has it closed.
"""
from __future__ import annotations

import os
from typing import Annotated, Optional

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server
from pydantic import BaseModel, Field

from . import macos, playback, sources
from .concert import Concert, ConcertError
from .config import Config
from .library import SoundLibrary, list_plugins

INSTRUCTIONS = """\
Tools for building Apple MainStage concerts.

Typical workflow when the user names a song:
1. Work out tempo, time signature and which keyboard sounds the song needs
   (use your own knowledge or a web search if available).
2. search_sounds for each sound (try several keywords, e.g. "brass", "analog brass").
3. create_song_patch with the chosen sounds. Default faders to 0 dB unless the user says otherwise.
4. Optionally add_playback with an audio file the user points you to (find_audio_files).

Concerts are edited on disk. MainStage must not have the concert open, otherwise it would
overwrite the changes. If a tool reports that the concert is open, tell the user to close it
and call the tool again (optionally with wait_seconds so it waits for the user).
Never invent sound names: only use names returned by search_sounds.
"""

mcp = _Server("mainstage", instructions=INSTRUCTIONS)
CFG = Config.from_env()
LIB = SoundLibrary(CFG.library_dirs)


class ChannelSpec(BaseModel):
    sound: str = Field(description='Sound name or "rel" path exactly as returned by search_sounds')
    label: Optional[str] = Field(None, description="Channel strip name shown in MainStage")
    volume_db: float = Field(0.0, description="Fader level in dB (-96 … +6)")
    pan: float = Field(0.0, description="-1 = left, 0 = centre, +1 = right")
    muted: bool = False


# ----------------------------------------------------------------- helpers
def _concert_files() -> list[str]:
    out = []
    for d in CFG.concerts_dirs:
        if not os.path.isdir(d):
            continue
        for root, dirs, _ in os.walk(d):
            for x in list(dirs):
                if x.endswith(".concert"):
                    out.append(os.path.join(root, x))
                    dirs.remove(x)
                elif x.startswith(".") or x.endswith(".patch"):
                    dirs.remove(x)
            if root.count(os.sep) - d.count(os.sep) >= 2:
                dirs[:] = []
    return sorted(out)


def _open(concert: str) -> Concert:
    c = os.path.expanduser(concert)
    if os.path.isabs(c) or os.path.exists(c):
        return Concert(c, CFG.backup_dir)
    want = concert.lower().removesuffix(".concert")
    files = _concert_files()
    exact = [f for f in files if os.path.basename(f)[:-8].lower() == want]
    hits = exact or [f for f in files if want in os.path.basename(f).lower()]
    if len(hits) == 1:
        return Concert(hits[0], CFG.backup_dir)
    if not hits:
        raise ConcertError(f'concert "{concert}" not found in {", ".join(CFG.concerts_dirs)}')
    raise ConcertError(f'"{concert}" is ambiguous: ' + ", ".join(os.path.basename(h) for h in hits))


def _writable(c: Concert, wait_seconds: int) -> None:
    reason = macos.wait_until_closed(c.path, timeout=min(max(wait_seconds, 0), 600))
    if reason:
        raise ConcertError("CONCERT_OPEN: " + reason)


def _err(e: Exception) -> dict:
    return {"ok": False, "error": str(e)}


# ------------------------------------------------------------------- tools
@mcp.tool()
def mainstage_status() -> dict:
    """Is MainStage running and which concert windows are open."""
    return macos.status()


@mcp.tool()
def list_concerts() -> dict:
    """List the .concert files in the configured concert folder(s)."""
    return {"folders": CFG.concerts_dirs,
            "concerts": [{"name": os.path.basename(f)[:-8], "path": f} for f in _concert_files()]}


@mcp.tool()
def list_patches(concert: Annotated[str, Field(description="Concert name or path")]) -> dict:
    """Patch list of a concert (in order, sets shown as nested entries)."""
    try:
        c = _open(concert)

        def conv(refs):
            out = []
            for r in refs:
                if r.is_set:
                    out.append({"set": r.name, "patches": conv(r.children)})
                else:
                    info = c.patch_info(r)
                    out.append({k: info[k] for k in ("name", "program_change", "tempo")} |
                               {"channels": [ch["name"] for ch in info["channels"]]})
            return out
        return {"concert": c.name, "path": c.path, "patches": conv(c.tree())}
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_patch(concert: str, patch: str) -> dict:
    """Details of one patch: tempo, time signature, channel strips with sound, dB, pan, mute, plug-ins."""
    try:
        c = _open(concert)
        return c.patch_info(c.find_patch(patch))
    except Exception as e:
        return _err(e)


@mcp.tool()
def search_sounds(query: Annotated[str, Field(description='Keywords, e.g. "rhodes", "synth brass", "B3 organ"')] = "",
                  category: Annotated[str, Field(description='Optional category filter, e.g. "Keyboard", "Synthesizer/Lead"')] = "",
                  limit: int = 25) -> dict:
    """Search the installed Logic/MainStage sound library (instrument patches)."""
    res = LIB.search(query, category, "Instrument", limit)
    return {"count": len(res), "sounds": [{"name": s.name, "category": s.category, "family": s.family, "rel": s.rel}
                                           for s in res]}


@mcp.tool()
def find_sound(query: Annotated[str, Field(description='What you are looking for, German or English, e.g. "Flöte", "flute", "warm pad", "Hammond"')],
               limit: int = 15) -> dict:
    """Where can I find a sound like this? Searches the sound library, the channel strips used in your
    concerts, exported patch files and installed plug-in names. German/English instrument names work."""
    lib = LIB.search(query, "", "", limit)
    plugins = list_plugins(CFG.plugin_dirs)
    result = {
        "query": query,
        "library": [{"name": s.name, "category": f"{s.kind}/{s.category}".strip("/"),
                     "family": s.family, "rel": s.rel} for s in lib],
        "in_your_concerts": sources.search_concerts(query, _concert_files(), limit),
        "patch_files": sources.search_patch_files(query, CFG.concerts_dirs, limit),
        "plugins_by_name": sources.search_plugins(query, plugins),
        "sample_players_installed": [p["name"] for p in plugins
                                     if any(k in p["name"].lower() for k in
                                            ("kontakt", "halion", "keys", "sampletank", "omnisphere",
                                             "keyscape", "numa", "pianoteq", "spitfire", "labs"))],
    }
    result["hint"] = ("Library sounds can be used directly in create_song_patch (use 'rel'). "
                      "Sounds inside third-party sample players (e.g. Kontakt) cannot be searched; "
                      "they are listed so you can suggest looking there.")
    return result


@mcp.tool()
def list_sound_categories() -> dict:
    """Categories of the sound library with the number of sounds in each."""
    return {"libraries": [r for r in LIB.roots if os.path.isdir(r)], "categories": LIB.categories()}


@mcp.tool()
def refresh_sound_library() -> dict:
    """Rescan the sound library (after installing new content)."""
    return {"sounds": LIB.refresh()}


@mcp.tool()
def list_installed_plugins() -> dict:
    """Third-party Audio Unit / VST plug-ins installed on this Mac (Apple's built-in instruments are not listed)."""
    return {"plugins": list_plugins(CFG.plugin_dirs)}


@mcp.tool()
def create_song_patch(
    concert: Annotated[str, Field(description="Concert name or path")],
    name: Annotated[str, Field(description="Patch name, usually the song title")],
    channels: Annotated[list[ChannelSpec], Field(description="Channel strips (sounds) of the patch")],
    tempo: Annotated[Optional[float], Field(description="Tempo in BPM")] = None,
    time_signature: Annotated[Optional[list[int]], Field(description="e.g. [4, 4] or [6, 8]")] = None,
    transpose: Annotated[int, Field(description="Patch transpose in semitones")] = 0,
    position: Annotated[Optional[int], Field(description="0-based position in the patch list; default: end")] = None,
    wait_seconds: Annotated[int, Field(description="Wait up to this long for the user to close the concert")] = 0,
) -> dict:
    """Create a new patch for a song with sounds from the library, tempo, time signature and mixer settings."""
    try:
        c = _open(concert)
        _writable(c, wait_seconds)
        specs = []
        for ch in channels:
            s = LIB.get(ch.sound)
            specs.append({"source_cst": s.cst, "label": ch.label or s.name, "volume_db": ch.volume_db,
                          "pan": ch.pan, "muted": ch.muted, "meta": LIB.plist_meta(s)})
        ts = tuple(time_signature) if time_signature else None
        res = c.create_patch(name, specs, tempo=tempo, time_signature=ts, transpose=transpose,
                             position=position)
        return {"ok": True, "concert": c.name, **res,
                "note": "Open the concert in MainStage to use the new patch."}
    except Exception as e:
        return _err(e)


@mcp.tool()
def set_channel(concert: str, patch: str,
                channel: Annotated[str, Field(description="Channel strip name (or 1-based number)")],
                volume_db: Optional[float] = None, pan: Optional[float] = None,
                muted: Optional[bool] = None, wait_seconds: int = 0) -> dict:
    """Change fader (dB), pan (-1…+1) or mute of a channel strip in a patch."""
    try:
        c = _open(concert)
        _writable(c, wait_seconds)
        return {"ok": True, **c.set_channel(patch, channel, volume_db=volume_db, pan=pan, muted=muted)}
    except Exception as e:
        return _err(e)


@mcp.tool()
def set_patch_settings(concert: str, patch: str, tempo: Optional[float] = None,
                       remove_tempo: bool = False, time_signature: Optional[list[int]] = None,
                       transpose: Optional[int] = None, wait_seconds: int = 0) -> dict:
    """Change tempo, time signature or transpose of an existing patch."""
    try:
        c = _open(concert)
        _writable(c, wait_seconds)
        ts = tuple(time_signature) if time_signature else None
        return {"ok": True, **c.set_patch(patch, tempo=tempo, clear_tempo=remove_tempo,
                                          time_signature=ts, transpose=transpose)}
    except Exception as e:
        return _err(e)


@mcp.tool()
def find_audio_files(directory: Annotated[str, Field(description="Folder to search (any folder the user names)")],
                     query: Annotated[str, Field(description="Words from the song title or file name")] = "",
                     limit: int = 20) -> dict:
    """Find audio files (mp3, wav, aiff, m4a, …) in a folder, e.g. backing tracks for a song."""
    try:
        return {"files": playback.find_audio_files(directory, query, limit)}
    except Exception as e:
        return _err(e)


@mcp.tool()
def add_playback(concert: str, patch: str,
                 audio_file: Annotated[str, Field(description="Absolute path of the audio file")],
                 label: Optional[str] = None, volume_db: float = 0.0, muted: bool = False,
                 wait_seconds: int = 0) -> dict:
    """Add a Playback channel strip playing the given audio file to a patch.

    Uses an existing Playback channel strip (from your concerts or MAINSTAGE_PLAYBACK_TEMPLATE)
    as template, so output routing and plug-in settings follow your usual setup.
    """
    try:
        c = _open(concert)
        _writable(c, wait_seconds)
        audio = os.path.abspath(os.path.expanduser(audio_file))
        tpl = playback.find_template(CFG.concerts_dirs, CFG.playback_template)
        url, bookmark = macos.file_bookmark(audio)
        spec = {"source_cst": tpl.cst_path, "transform": playback.make_transform(tpl, url, bookmark),
                "label": label or ("Playback " + os.path.splitext(os.path.basename(audio))[0])[:60],
                "volume_db": volume_db, "pan": 0.0, "muted": muted,
                "plist_template": tpl.plist_channel,
                "meta": {"Channel_chaStrName": "Playback", "Channel_chaStrCategory": ""}}
        return {"ok": True, "template": tpl.cst_path, **c.add_channel(patch, spec)}
    except Exception as e:
        return _err(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
