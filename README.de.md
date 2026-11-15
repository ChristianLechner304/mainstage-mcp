# mainstage-mcp (Deutsch)

Ein [MCP](https://modelcontextprotocol.io)-Server, mit dem ein KI-Assistent (z. B. Claude Desktop)
**Apple-MainStage**-Concerts für dich aufbaut.

Sag deinem Assistenten *„Leg in meinem Band-Concert einen Patch für Jump von Van Halen an“* und er

- ermittelt Tempo, Taktart und die Keyboard-Sounds des Songs,
- sucht passende Sounds in deiner installierten Logic-Pro-/MainStage-Soundbibliothek,
- legt den Patch mit Tempo, Taktart, Fader, Pan und Mute im Concert an,
- fügt auf Wunsch einen **Playback**-Channelstrip mit einem Backing Track aus einem Ordner deiner Wahl hinzu.

> **Inoffizielles Projekt.** MainStage hat keine öffentliche Schnittstelle. Der Server bearbeitet die
> Concert-Datei direkt; das Format wurde durch Vergleich von MainStage-Dateien ermittelt. Vor jeder
> Änderung wird eine Sicherung angelegt, unbekannte Dateiaufbauten werden nicht verändert.
> Wichtige Concerts trotzdem selbst sichern.

## Werkzeuge

| Werkzeug | Funktion |
| --- | --- |
| `find_sound` | „Wo finde ich einen Flötensound?“ – sucht in der Soundbibliothek, in den Channelstrips deiner Concerts, in exportierten Patch-Dateien und in Plug-in-Namen (deutsche und englische Instrumentennamen) |
| `search_sounds`, `list_sound_categories` | Suche in der Logic/MainStage-Soundbibliothek |
| `create_song_patch` | Neuer Patch mit Sounds, Tempo, Taktart, Transponierung, Fader/Pan/Mute |
| `set_channel`, `set_patch_settings` | Fader, Pan, Mute bzw. Tempo, Taktart, Transponierung ändern |
| `list_concerts`, `list_patches`, `get_patch` | Concerts und Patches auslesen |
| `find_audio_files`, `add_playback` | Backing Tracks in einem beliebigen Ordner finden und als Playback einfügen |
| `list_installed_plugins`, `mainstage_status` | Installierte Plug-ins, Status von MainStage |

## Voraussetzungen

- macOS mit **MainStage 3** (Concerts ab MainStage 3.2 gespeichert)
- Die Logic-Pro-/MainStage-**Soundbibliothek** (MainStage ▸ Soundbibliothek)
- **Python 3.10+** (`python3 --version`)
- Ein MCP-Client, z. B. [Claude Desktop](https://claude.ai/download)

## Installation

```bash
python3 -m venv ~/.mainstage-mcp
~/.mainstage-mcp/bin/pip install "git+https://github.com/ChristianLechner304/mainstage-mcp.git"
~/.mainstage-mcp/bin/mainstage-mcp     # Starttest, mit Ctrl+C beenden
```

Update: `~/.mainstage-mcp/bin/pip install --upgrade "git+https://github.com/ChristianLechner304/mainstage-mcp.git"`

## In Claude Desktop einbinden

**Claude Desktop ▸ Einstellungen ▸ Entwickler ▸ Konfiguration bearbeiten** und in
`claude_desktop_config.json` eintragen (`DEIN_USER` durch deinen macOS-Benutzernamen ersetzen,
`echo $HOME` zeigt ihn an):

```json
{
  "mcpServers": {
    "mainstage": {
      "command": "/Users/DEIN_USER/.mainstage-mcp/bin/mainstage-mcp",
      "env": {
        "MAINSTAGE_CONCERTS_DIR": "/Users/DEIN_USER/Music/MainStage"
      }
    }
  }
}
```

Claude Desktop neu starten. Die MainStage-Werkzeuge erscheinen in einem neuen Chat im Werkzeug-Menü.

### Einstellungen (optional, im `env`-Block)

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `MAINSTAGE_CONCERTS_DIR` | `~/Music/MainStage` | Ordner mit deinen `.concert`-Dateien, mehrere mit `:` trennen |
| `MAINSTAGE_LIBRARY_DIRS` | Standard-Orte der Logic/MainStage-Bibliothek | Patch-Bibliotheken, mit `:` trennen |
| `MAINSTAGE_PLUGIN_DIRS` | `/Library/Audio/Plug-Ins:~/Library/Audio/Plug-Ins` | Plug-in-Ordner |
| `MAINSTAGE_PLAYBACK_TEMPLATE` | *(automatisch)* | `.cst`-Datei als Vorlage für Playback-Channelstrips |
| `MAINSTAGE_BACKUP_DIR` | `~/Library/Application Support/mainstage-mcp/backups` | Sicherungen; `off` schaltet sie ab |

Concerts lassen sich auch per vollem Pfad ansprechen; für Backing Tracks nennst du im Chat einfach
den jeweiligen Ordner. Es sind keine persönlichen Pfade fest eingebaut.

### macOS-Berechtigungen

- **Automation / System Events:** Um zu erkennen, ob MainStage ein Concert geöffnet hat, liest der
  Server die Fenstertitel. macOS fragt einmal, ob Claude „System Events“ steuern darf – erlauben.
  Ohne diese Freigabe verweigert der Server Änderungen, solange MainStage überhaupt läuft.
- **Dateien:** Liegen Concerts oder Backing Tracks in geschützten Ordnern (Schreibtisch, Dokumente,
  Downloads, iCloud/OneDrive), fragt macOS beim ersten Zugriff nach.

## Arbeiten mit MainStage

1. **Concert in MainStage schließen** (oder MainStage beenden), bevor du Änderungen anforderst.
   Sonst überschreibt MainStage sie beim nächsten Speichern. Der Server prüft das und fordert dich
   über den Assistenten auf, das Concert zu schließen; mit `wait_seconds` wartet er darauf.
2. Beispiele:
   - *„Welche Patches hat mein Concert ‚Band 2026‘?“*
   - *„Ich brauche einen Flötensound – wo finde ich einen?“*
   - *„Leg in ‚Band 2026‘ einen Patch für ‚Jump‘ von Van Halen an: Synth-Brass für das Riff, ein Lead fürs Solo (stumm), Fader auf 0 dB.“*
   - *„Stell das Solo in ‚Jump‘ auf −3 dB und heb die Stummschaltung auf.“*
   - *„Füg den Backing Track für ‚Jump‘ aus ~/Music/Playbacks als Playback hinzu, stumm.“*
3. **Concert in MainStage öffnen.** Neue Patches stehen am Ende der Patch-Liste (oder an der
   gewünschten Position) mit der nächsten freien Program-Change-Nummer.

### Playbacks

`add_playback` kopiert einen vorhandenen **Playback**-Channelstrip und tauscht die Audiodatei aus.
Routing (z. B. Output 3–4), Effekte und Playback-Einstellungen entsprechen damit deinem gewohnten Setup.

Einmalig nötig: In irgendeinem Concert einen Patch mit einem Channelstrip anlegen, der das
**Playback**-Plug-in mit geladener Audiodatei nutzt, und speichern. Der Server findet ihn
automatisch, oder du gibst die `.cst`-Datei über `MAINSTAGE_PLAYBACK_TEMPLATE` an.

Bitte nur Audiodateien verwenden, an denen du die Rechte hast (gekaufte Backing Tracks, eigene Aufnahmen, Stems).

## Grenzen

- Sounds stammen aus Bibliotheks-Patches mit einem Channelstrip (≈3.700 in der vollen Bibliothek);
  Mehrfach-Channelstrip-Patches („Summing Stacks“) werden übersprungen.
- Plug-in-Parameter innerhalb eines Channelstrips (Hallanteil, Filter …) sind nicht editierbar –
  dafür passende Presets wählen oder eigene Bibliotheks-Patches anlegen.
- Screen-Control-Zuweisungen, Keyboard-Splits/Layer und Sets (Ordner) werden noch nicht angelegt.
  Neue Patches übernehmen das Screen-Control-Layout eines vorhandenen Patches; das Concert braucht
  daher mindestens einen Patch.

Technische Details: [docs/FORMAT.md](docs/FORMAT.md)
