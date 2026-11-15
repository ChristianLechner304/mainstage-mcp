"""Configuration via environment variables (set them in the MCP client config).

MAINSTAGE_CONCERTS_DIR      folder(s) with your .concert files, separated by ":"
                            default: ~/Music/MainStage
MAINSTAGE_LIBRARY_DIRS      patch library folder(s), separated by ":"
                            default: the standard Logic Pro / MainStage locations
MAINSTAGE_PLUGIN_DIRS       plug-in folders, separated by ":"
                            default: /Library/Audio/Plug-Ins:~/Library/Audio/Plug-Ins
MAINSTAGE_PLAYBACK_TEMPLATE optional .cst file used as template for Playback strips
MAINSTAGE_BACKUP_DIR        where changed files are backed up before writing
                            default: ~/Library/Application Support/mainstage-mcp/backups
                            set to "off" to disable backups
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _paths(var: str, default: list[str]) -> list[str]:
    raw = os.environ.get(var, "").strip()
    items = [p for p in raw.split(os.pathsep) if p.strip()] if raw else default
    return [os.path.abspath(os.path.expanduser(p.strip())) for p in items]


DEFAULT_LIBRARIES = [
    "~/Music/Logic Pro Library.bundle/Patches",           # Logic Pro / MainStage sound library
    "/Library/Application Support/Logic/Patches",         # older system-wide installs
    "~/Music/Audio Music Apps/Patches",                   # user patches saved from Logic/MainStage
]


@dataclass
class Config:
    concerts_dirs: list[str] = field(default_factory=list)
    library_dirs: list[str] = field(default_factory=list)
    plugin_dirs: list[str] = field(default_factory=list)
    playback_template: str | None = None
    backup_dir: str | None = None

    @classmethod
    def from_env(cls) -> "Config":
        backup = os.environ.get("MAINSTAGE_BACKUP_DIR",
                                "~/Library/Application Support/mainstage-mcp/backups")
        return cls(
            concerts_dirs=_paths("MAINSTAGE_CONCERTS_DIR", ["~/Music/MainStage"]),
            library_dirs=_paths("MAINSTAGE_LIBRARY_DIRS", DEFAULT_LIBRARIES),
            plugin_dirs=_paths("MAINSTAGE_PLUGIN_DIRS",
                               ["/Library/Audio/Plug-Ins", "~/Library/Audio/Plug-Ins"]),
            playback_template=os.environ.get("MAINSTAGE_PLAYBACK_TEMPLATE") or None,
            backup_dir=None if backup.lower() in ("off", "none", "0", "")
            else os.path.abspath(os.path.expanduser(backup)),
        )
