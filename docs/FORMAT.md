# MainStage file format notes

Everything here was found by saving concerts in MainStage 3 before and after changing a single
setting and comparing the files. It is not official documentation and may differ between versions.

## Concert package

```
Name.concert/
├── data.plist                 document/window settings (binary plist)
├── base.plistZ
├── workspace.layout/          layout (screen controls)
├── Samples/, Sampler Instruments/, Alchemy Samples/   consolidated content
└── Concert.patch/
    ├── data.plist             concert channels (aux, outputs, master, metronome)
    │                          + "nodes": ordered list of patch/set folder names
    ├── *.cst                  concert-level channel strips
    └── Song.patch/
        ├── data.plist         patch: "patch" -> "engineNode", "channels"
        └── *.cst              one file per channel strip
```

A **set** is a `.patch` folder whose `data.plist` has its own `nodes` list.

### Patch `data.plist` → `patch.engineNode`

| Key | Meaning |
| --- | --- |
| `name` | patch name |
| `hasTempo`, `tempo` | patch tempo on/off, BPM (float) |
| `hasTimeSignature`, `TimeSignatureNumerator`, `TimeSignatureDenominator` | denominator stored as exponent: 2 → quarter notes |
| `hasProgramChange`, `patchChangeNum` | program change number |
| `globalTranspose` | transpose in semitones |
| `uiPluginDataDict`, `parameterMappingMap` | screen-control mappings |

### Patch `data.plist` → `channels[]`

| Key | Meaning |
| --- | --- |
| `Filename` | channel strip file in the patch folder |
| `Channel_name` | displayed name |
| `Channel_chaStrName`, `Channel_chaStrCategory`, `Channel_chaStrFullPath` | library origin, `@BASE@` = library `Patches` folder |
| `Channel_instID` | unique id within the concert (MainStage uses steps of 4) |
| `UUID` | channel id |
| `volume` | fader value as 8.24 fixed point (see below) |
| `Channel_pan` | -1.0 … +1.0 |
| `Channel_isMuted`, `Channel_isSolo` | flags |
| `Channel_outputIndex` | output routing |

MainStage reads fader, pan and mute **from the `.cst` file**; the plist values are written as well
so both stay consistent.

## Channel strip (`.cst`)

Binary, starts with magic `OCuA`, followed by chunks (`UCuA`, `GAMETSPP`, binary plists, …).
Fixed offsets in the channel header:

| Offset | Size | Meaning |
| --- | --- | --- |
| 121 | 1 | integer part of the fader value |
| 124 | 1 | solo |
| 125 | 1 | pan, 0 … 127, 64 = centre |
| 126 | 1 | mute |
| 152 | 4 | fader value, unsigned 8.24 fixed point, little endian |

The server only writes when byte 121 equals the integer part of the value at 152, which guards
against unknown layouts.

### Fader law

```
dB = 40 · log10(value / 90)        value = 90 · 10^(dB / 40)
```

90 = 0 dB, 127 = +6 dB (maximum), e.g. 63.7 ≈ −6 dB, 50.6 ≈ −10 dB.

### Audio file reference (Playback)

The Playback plug-in stores its file in a chunk tagged `ELIF` (`FILE` little endian):

```
"ELIF" | uint32 total length (incl. 8 byte header) | binary plist
    CFileRef_Bookmark  macOS bookmark data (NSURL bookmarkData)
    CFileRef_URL       file:// URL
```

Enclosing chunks carry uint32 size fields that must change by the same amount when the chunk is
resized. They sit at fixed distances from the `Playback` plug-in name: −128, +32, +52 (common
layout) or −128, +880 (extended layout).
