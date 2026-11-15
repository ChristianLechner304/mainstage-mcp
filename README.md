# mainstage-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant (Claude Desktop, or any
other MCP client) build **Apple MainStage** concerts for you.

Tell your assistant *"Add a patch for Jump by Van Halen to my band concert"* and it will:

- work out tempo, time signature and the keyboard sounds the song needs,
- pick matching sounds from your installed Logic Pro / MainStage sound library,
- create the patch in your concert with the right tempo, time signature, fader levels, pan and mute,
- optionally add a **Playback** channel strip with a backing track you point it to.

> 🇩🇪 Deutsche Anleitung: [README.de.md](README.de.md)

> **Unofficial project.** MainStage has no public API, so this server edits the concert package
> on disk. The file format was analysed by comparing files saved by MainStage. Every change is
> backed up first, and unknown file layouts are rejected instead of being modified. Still: keep
> your own backups of important concerts.

## Features

| Tool | What it does |
| --- | --- |
| `list_concerts` | Concerts in your concert folder(s) |
| `list_patches`, `get_patch` | Patch list, tempo, channel strips with sound, dB, pan, mute, Playback file |
| `find_sound` | "Where can I find a flute?" – searches the sound library, the channel strips in your concerts, exported patch files and plug-in names (German/English instrument names) |
| `search_sounds`, `list_sound_categories` | Search the installed Logic/MainStage sound library |
| `create_song_patch` | New patch with sounds, tempo, time signature, transpose, fader/pan/mute per channel |
| `set_channel` | Change fader (dB), pan or mute of a channel strip |
| `set_patch_settings` | Change tempo, time signature or transpose of a patch |
| `find_audio_files` | Find backing tracks in any folder you name |
| `add_playback` | Add a Playback channel strip with an audio file to a patch |
| `list_installed_plugins` | Third-party AU/VST plug-ins on the Mac |
| `mainstage_status` | Is MainStage running, which concert is open |

## Requirements

- macOS with **MainStage 3** (concerts saved with MainStage 3.2 or newer)
- The Logic Pro / MainStage **sound library** (MainStage ▸ Sound Library) for `search_sounds`
- **Python 3.10+** (`python3 --version`)
- An MCP client, e.g. [Claude Desktop](https://claude.ai/download)

## Installation

```bash
# 1. create an isolated environment
python3 -m venv ~/.mainstage-mcp

# 2. install the server from GitHub
~/.mainstage-mcp/bin/pip install "git+https://github.com/ChristianLechner304/mainstage-mcp.git"

# 3. check it starts (Ctrl+C to quit)
~/.mainstage-mcp/bin/mainstage-mcp
```

To update later: `~/.mainstage-mcp/bin/pip install --upgrade "git+https://github.com/ChristianLechner304/mainstage-mcp.git"`

## Connect it to Claude Desktop

Open **Claude Desktop ▸ Settings ▸ Developer ▸ Edit Config** and add the server to
`claude_desktop_config.json` (replace `YOUR_USER` with your macOS user name, `echo $HOME` shows it):

```json
{
  "mcpServers": {
    "mainstage": {
      "command": "/Users/YOUR_USER/.mainstage-mcp/bin/mainstage-mcp",
      "env": {
        "MAINSTAGE_CONCERTS_DIR": "/Users/YOUR_USER/Music/MainStage"
      }
    }
  }
}
```

Restart Claude Desktop. The MainStage tools appear in the tools menu of a new chat.
Other MCP clients use the same command (stdio transport).

### Configuration

All settings are optional environment variables in the `env` block:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAINSTAGE_CONCERTS_DIR` | `~/Music/MainStage` | Folder(s) containing your `.concert` files, separated by `:` |
| `MAINSTAGE_LIBRARY_DIRS` | standard Logic/MainStage library locations | Patch library folder(s), separated by `:` |
| `MAINSTAGE_PLUGIN_DIRS` | `/Library/Audio/Plug-Ins:~/Library/Audio/Plug-Ins` | Where `list_installed_plugins` looks |
| `MAINSTAGE_PLAYBACK_TEMPLATE` | *(auto)* | A `.cst` file used as template for Playback strips |
| `MAINSTAGE_BACKUP_DIR` | `~/Library/Application Support/mainstage-mcp/backups` | Backups of changed files; `off` disables them |

Concerts can always be addressed by full path too, and `find_audio_files` / `add_playback` accept
any folder or file you mention in the chat. Nothing user-specific is hard-coded.

### macOS permissions

- **Automation / System Events:** to detect whether MainStage has a concert open, the server reads
  MainStage's window titles. macOS asks once whether Claude may control "System Events"; allow it.
  Without this permission the server refuses to edit concerts while MainStage is running at all.
- **Files:** if your concerts or backing tracks live in a protected location (Desktop, Documents,
  Downloads, iCloud/OneDrive folders), macOS may ask for access the first time.

## Working with MainStage

1. **Close the concert in MainStage** (or quit MainStage) before asking for changes. MainStage keeps
   the concert in memory and would overwrite the changes when saving. The server checks this and
   tells the assistant to ask you to close it; with `wait_seconds` it waits until you have.
2. Ask your assistant, e.g.:
   - *"Which patches are in my concert 'Band 2026'?"*
   - *"I need a flute sound – where can I find one?"*
   - *"Add a patch for 'Jump' by Van Halen to 'Band 2026': synth brass for the riff, a lead for the solo (muted), faders at 0 dB."*
   - *"Set the solo lead in 'Jump' to -3 dB and unmute it."*
   - *"Add the backing track from ~/Music/Backing Tracks for 'Jump' as playback, muted."*
3. **Open the concert in MainStage.** New patches appear at the end of the patch list
   (or at the requested position) with the next free program change number.

### Playback tracks

`add_playback` copies an existing **Playback** channel strip and points it to a new audio file, so
routing (e.g. Output 3-4), effects and Playback settings follow your usual setup.

One-time setup: create one patch in any concert with a channel strip that uses the **Playback**
plug-in and has an audio file loaded, then save the concert. The server finds it automatically
in your concert folder, or you set `MAINSTAGE_PLAYBACK_TEMPLATE` to that `.cst` file
(inside the concert package: *Show Package Contents ▸ Concert.patch ▸ Patch.patch ▸ Channel.cst*).

Only use audio files you have the rights to use (purchased backing tracks, your own recordings or stems).

## Limitations

- Sounds come from single-channel-strip library patches (≈3,700 in the full library). Multi-strip
  "summing stack" patches are skipped.
- Plug-in parameters inside a channel strip (e.g. reverb amount, filter cutoff) cannot be edited;
  choose a fitting preset instead, or create your own library patches and point
  `MAINSTAGE_LIBRARY_DIRS` to them.
- Screen-control mappings, keyboard splits/layers and sets (folders) are not created yet.
  New patches copy the screen-control layout of an existing patch in the concert, so the concert
  needs at least one patch.
- Tested with MainStage 3 concerts on Apple Silicon. Other versions may use a different file
  layout; the server then refuses to edit instead of guessing.

## How it works

See [docs/FORMAT.md](docs/FORMAT.md) for what is known about the concert and channel-strip format.

## Development

```bash
git clone https://github.com/ChristianLechner304/mainstage-mcp.git
cd mainstage-mcp
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Contributions are welcome, especially file-format findings from other MainStage versions.
Never commit concerts, channel strips or audio files (Apple sound content and recordings are copyrighted).

## License

MIT. MainStage and Logic Pro are trademarks of Apple Inc. This project is not affiliated with Apple.
