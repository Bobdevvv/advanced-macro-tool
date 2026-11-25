# AMT technical documentation

How AMT works inside: architecture, data formats, the guarantees the code
makes, and how it is built and tested. For **using** AMT, read the
[user guide](GUIDE.md) instead (it is also the **Help** page inside the app).

**Contents:** [Architecture](#architecture) · [Features in depth](#features-in-depth) ·
[Guarantees](#guarantees) · [Technical notes](#technical-notes) ·
[Project structure](#project-structure) · [Requirements](#requirements) ·
[Dependencies](#dependencies) · [Building a standalone `.exe`](#building-a-standalone-exe) ·
[Testing](#testing)

---

## Architecture

```
src/core/     recording, playback, clicker, hotkeys, editing: pure Python, no Qt
src/models/   Macro / MacroEvent dataclasses and JSON (de)serialisation
src/storage/  macro files on disk
src/ui/       everything Qt: pages, widgets, theme, timeline
```

- **Threads.** The recorder, player, clicker and hotkey listener run on
  background threads (pynput listeners or daemon threads). They never touch
  widgets; they call plain callbacks that `_Bridge(QObject)` in
  `main_window.py` re-emits as queued Qt signals on the UI thread.
- **One place per change.** The loaded macro changes only through
  `LibraryPlayerTab.loaded_changed`; every Composer edit goes through
  `ComposerTab._apply`, which records it for undo.
- **Errors.** `src/ui/errors.py` installs `sys.excepthook` and
  `threading.excepthook`: an unexpected error is logged to
  `Documents\AdvancedMacroTool\logs\amt.log` (code locations only, never input) and
  shown as a message, and the app keeps running. Without it PyQt6 aborts the
  process on any exception in a slot.
- **Single instance.** A `QLockFile` in the AMT folder refuses a second copy
  (two copies would both react to every global hotkey); a crashed instance's
  lock is detected by process ID.

---

## Features in depth

### Interface
- Sidebar navigation with a live indicator: an entry turns red while its recording, playback or clicker is running
- The loaded macro is shown in the sidebar on every page, with its own Play/Stop button and progress bar
- Your current global hotkeys are always visible at the bottom of the sidebar
- Typing-friendly number fields: units sit beside the number, and time fields switch unit as you type (`250ms`, `2s`, `1m`, `5h`, `1d`)
- High-contrast text in every theme (secondary text ≥ 7:1, hints ≥ 4.8:1 against their background)
- An (i) icon next to most settings explains what it does on hover
- A **Help** page renders `docs/GUIDE.md` (the same file as on GitHub) with a contents list, working in-guide links and screenshots scaled to the window; `build.spec` bundles the guide and its images
- Scales to any window size: cards reflow into one or two columns, the sidebar collapses to icons in narrow windows, and Player & Library stacks vertically
- Pages that don't fit show a fade and a **More below** button, so extra options are never hidden
- Bundled fonts (Inter for text, JetBrains Mono for numbers and hotkeys) and Windows' own icon set, so it looks the same on every PC
- Sharp at any Windows display scaling (125 %, 150 %, …); remembers its window size and position

### Recording
- Records all mouse events: clicks (press & release), movement, and scroll wheel
- Records all keyboard events: key presses and releases, including held keys
- Toggle recording on/off via a configurable global hotkey (default: **F7**); the hotkey press itself is left out of the recording
- Live event counter and elapsed-time read-out while recording
- Optional: record clicks, scrolls and keys only, without mouse movement
- Mouse movement is throttled during recording (≥30 ms and ≥4 px between samples) to keep file sizes small
- New recordings are auto-named `Untitled-1`, `Untitled-2`, etc. in chronological order

### Playback
- Plays back any saved macro with accurate timing
- Adjustable playback speed (e.g. 0.5× slow motion, 2× fast forward)
- Configurable loop count, or infinite loop mode
- Safe stop: all held keys and mouse buttons are released on stop, preventing stuck input
- Toggle play/stop via a configurable global hotkey (default: **F8**)

### Humaniser
When enabled, replaces the raw recorded mouse path with smooth, naturally varied movement:

- **Checkpoint-based pathing** — the mouse path is reconstructed between every click and scroll position (recording start and end are also checkpoints). The original noisy move events are discarded entirely.
- **Cubic bezier curves** — each segment follows a cubic bezier arc with two randomly offset control points, creating the natural wrist-arc shape of real human movement. Curve arc % is adjustable.
- **Ease-in / ease-out** — the cursor accelerates out of each checkpoint and decelerates into the next, matching natural arm movement profiles.
- **Speed derived from the recording** — average cursor speed (px/s) is calculated from the full recorded path distance vs time, so humanised movement feels as fast or slow as the original user. Dwell time (pauses before clicks) is stripped out of the speed calculation.
- **Per-segment timing jitter** — each movement segment gets a small random duration offset (Gaussian) so no two playbacks are identical.
- **Mouse noise** — optional tiny Gaussian pixel offsets on each generated point add micro-tremor realism (off by default).
- **Typing rhythm** — `vary_typing` scales every gap between consecutive key events by its own Gaussian factor (clamped to 0.4–1.8×), which varies hold and flight times independently while never reordering key events (shortcuts stay intact). Typing bursts are squeezed back if they would run past the next click or scroll; mouse events are not touched.
- Controls: Timing jitter %, Curve arc %, Mouse noise (px), Typing variation %; editable whether or not humanising is switched on

### AutoClicker
- Configurable button (left / right / middle), click interval, and per-click jitter
- Optional hold duration per click
- Click limit (stop after N clicks, or run indefinitely)
- Fixed-position mode: lock clicks to a specific screen coordinate with a 3-second on-screen countdown picker
- Shows the resulting clicks per second and a live click counter
- Toggle start/stop via a configurable global hotkey (default: **F10**)

### Composer (timeline editor)
- Open any macro, or start a new one, on a zoomable timeline with Keyboard, Clicks & scroll, and Mouse movement tracks
- Actions are shown as you think of them: a held key is one bar, a click one marker, overlapping keys stack
- Select actions or a stretch of time; cut, copy, paste, delete, and drag to move, with full undo/redo
- Edits never leave a key or button held: releases move with their presses, and cutting the end of a hold releases it at the cut
- Inspector for exact start time, hold length and click position
- Optimise: shorten long pauses, remove mouse movement (whole macro or selection)
- Build from scratch: insert other macros (repeated N times), waits, key combinations and typed text; drag macros onto the timeline
- Test play without saving, also with a global hotkey (default **F9**) that works from any page or window; Save only overwrites the opened macro, and unsaved changes are never lost silently
- Editing shortcuts (Ctrl+Z/Y, Ctrl+X/C/V, Del, Ctrl+A) work anywhere on the page (`QShortcut` with `WidgetWithChildrenShortcut`), while focused text fields keep their own; a legend under the timeline lists them

### Player & Library
- Split-panel view: player on the left, library on the right (stacked, player first, in narrow windows)
- Filter the library by name
- Shows macro name, creation date, duration, event breakdown (mouse moves, clicks, scrolls, key presses/releases), and description
- Single-click to load; double-click to load and play immediately
- Rename, delete, and export macros directly from the library

### Themes
Seven built-in themes, picked from live previews in Settings:

| Theme | Style |
|-------|-------|
| **Terminal** *(default)* | Near-black with a gold accent; the same palette as the Bob Terminal site |
| **Graphite** | Neutral dark grey with a blue accent |
| **Midnight** | Deep navy with a bright blue accent |
| **Mocha** | Soft dark purple-grey with a lilac accent (was called *Dark*) |
| **Dracula** | Classic purple and pink |
| **Arctic** | Cool blue-grey with an icy accent |
| **Light** | Clean white with a blue accent |

### Settings
- Bind global hotkeys for record, play/stop, and autoclicker using a key-capture dialog (click Bind, press any key or combination)
- Every change applies and is saved immediately (`SettingsTab._commit`); there is no Save button
- An invalid or duplicate hotkey is marked and explained inline, and keeps its last valid value while every other change is still saved
- Choose a custom macro storage directory, and open it in Explorer
- *Load a new recording into the player* (`load_after_record`, on by default)
- `settings.json` values are kept only if they have the default's type (text or true/false), so a damaged file cannot crash start-up

---

## Guarantees

What the code promises, and the tests that hold it to that:

| Guarantee | How | Tests |
|---|---|---|
| A macro is never overwritten or deleted by accident | Taken names get ` (2)`; renaming onto a taken name is refused; case-only renames go via a temporary name | `tests/test_storage.py` |
| A crash mid-save never corrupts a macro | Write to a temporary file, `fsync`, then `os.replace` | `tests/test_storage.py` |
| Playback never leaves a key or button held | `try/finally` releases everything on stop, finish or error | `tests/test_engine.py` |
| Edits never leave a key held | `editing.normalize` after every edit; cuts release held keys at the cut | `tests/test_editing.py` |
| Shortcuts replay exactly | Keys replay by virtual key code | `tests/test_keyboard.py` |
| Hotkeys fire with any modifiers and layout | AMT's own matcher compares virtual key codes, exact modifiers, ignores simulated input | `tests/test_hotkeys.py` |
| AMT's own clicks and simulated input stay out of recordings | Start/stop clicks trimmed; `injected` events ignored | `tests/test_engine.py`, `tests/test_app.py` |
| An unexpected error does not close the app | Global exception hooks | `tests/test_app.py` (`CrashSafety`) |

---

## Technical Notes

- **Thread safety** — recorder, player, and autoclicker each run in daemon threads. All callbacks cross back to the Qt UI thread via a `_Bridge(QObject)` with `pyqtSignal`s, which Qt queues automatically and safely.
- **Key serialisation** — each key event stores a readable `key` (`'a'`, `'Key.space'`, or `'vk:67'` for keys without a printable character) plus `vk`, the physical key's virtual key code. Playback presses the physical key, so shortcuts replay exactly: with Ctrl held, Windows reports the C key as the control character `\x03`, and replaying that character would press Ctrl+Break instead of Ctrl+C. Recordings from older versions, which stored those control characters, are mapped back to their letter keys on playback.
- **Held keys** — a key is recorded as a press, Windows' auto-repeat presses while it is held, and one release, each with its own timestamp; playback reproduces the hold duration and the repeats.
- **Macro file format** — plain JSON with `name`, `description`, `created_at` (Unix timestamp), and an `events` array. Each event has `type`, `timestamp`, and whichever of `x`, `y`, `button`, `pressed`, `dx`, `dy`, `key` are relevant.

- **Hotkey matching** — pynput's `GlobalHotKeys` compares the *character* a key
  produces, which on Windows changes with the modifiers (Ctrl+R is `"\x12"`,
  Shift+1 is `"!"`), so such hotkeys never fire. `src/core/hotkey_manager.py`
  matches virtual key codes instead, requires the exact set of modifiers, fires
  once per press (not on auto-repeat) and ignores `injected` input.
- **Timeline editing** — `src/core/editing.py` groups raw events into
  *gestures* (a key hold including its auto-repeats, a click, a scroll burst, a
  stretch of movement) and implements every edit as a pure function returning
  a new event list, which makes undo a stack of lists.

---

## Project Structure

Naming: folders are `AdvancedMacroTool` (the repository and
`Documents\AdvancedMacroTool`), files are `AMT`/`amt` (`AMT.exe`, `amt.log`,
`amt.lock`, `amt.ico`). Both come from `src/brand.py`.

```
AdvancedMacroTool/
├── main.py                        # Entry point: DPI policy, error handler, single instance
├── build.spec                     # PyInstaller build config -> dist/AMT.exe
├── requirements.txt / requirements-dev.txt
├── pyproject.toml                 # ruff (lint) configuration
├── .github/
│   ├── workflows/ci.yml           # lint + tests on Windows, Python 3.11–3.13
│   ├── workflows/release.yml      # tag v* -> test, build AMT.exe, publish a release
│   └── RELEASE_NOTES.md           # text shown on every release page
├── assets/
│   ├── amt.ico / amt.png          # the logo (made by scripts/make_icon.py)
│   └── fonts/                     # Inter + JetBrains Mono (OFL, licences alongside)
├── docs/
│   ├── GUIDE.md                   # User guide
│   ├── QA-CHECKLIST.md            # Manual release checks (real input, monitors, scaling)
│   └── images/                    # Screenshots used by the guide and README
├── tests/                         # unittest suite; isolated temp AMT_HOME, fake input
├── scripts/
│   ├── docs_screenshots.py        # regenerates docs/images from demo macros
│   └── make_icon.py               # writes assets/amt.ico and amt.png from ui/logo.py
└── src/
    ├── brand.py                   # Name, folder name, version, author, licence, repo URL
    ├── app_paths.py               # Where files live; moves the pre-1.0 data folder
    ├── models/
    │   └── macro.py               # MacroEvent + Macro, validated loading, atomic save
    ├── core/                      # No Qt imports — pure logic, runs on worker threads
    │   ├── recorder.py            # pynput listeners, throttling, start/stop-click clean-up
    │   ├── player.py              # timed event replay, held-key safety
    │   ├── humanizer.py           # bezier path generation, speed-based timing
    │   ├── autoclicker.py         # configurable click loop
    │   ├── editing.py             # timeline edits: cut/paste/move, gestures, optimise
    │   └── hotkey_manager.py      # global hotkeys matched by virtual key code
    ├── storage/
    │   └── macro_store.py         # safe names, no-overwrite saves, case-safe renames
    └── ui/                        # All Qt lives here
        ├── main_window.py         # sidebar + page stack, config I/O, thread→UI signal bridge
        ├── errors.py              # unexpected errors: log + message instead of a crash
        ├── inputs.py              # NumberEdit, DurationEdit (typed units), CountEdit
        ├── widgets.py             # shared building blocks: Page, Card, ResponsiveGrid,
        │                          #   Pill, KeyCombo, StatTile, Segmented, ScrollHint
        ├── theme.py               # 7 palettes → stylesheet, QPalette and SVG assets
        ├── fonts.py               # registers the bundled fonts
        ├── icons.py               # theme-aware icons from the Windows icon font
        ├── logo.py                # the AMT logo, drawn in code at any size
        ├── recorder_tab.py        # Record page
        ├── library_player_tab.py  # Player & Library page
        ├── composer_tab.py        # Composer page (timeline editor, undo/redo)
        ├── timeline.py            # the timeline widget (tracks, zoom, selection, drag)
        ├── autoclicker_tab.py     # Auto Click page
        ├── settings_tab.py        # Settings page, theme swatches, key-capture dialog
        └── styles.py              # thin re-export shim over theme.py
```

---

## Requirements

| | |
|---|---|
| **OS** | Windows 10 or 11. The app is Windows-only: `pynput`'s global listeners are imported through the `_win32` backends, and the PyInstaller spec pins those hidden imports. |
| **Python** | 3.11 or newer (3.11–3.13 recommended; see the note on newer releases under [Troubleshooting](../README.md#troubleshooting)) |
| **Disk** | ~200 MB, almost all of it PyQt6 and its Qt runtime |

No compiler, no system packages, and no admin rights are needed to install — see
[Troubleshooting](../README.md#troubleshooting) for the one case where running as admin matters.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| [PyQt6](https://pypi.org/project/PyQt6/) ≥ 6.4 | GUI framework |
| [pynput](https://pypi.org/project/pynput/) ≥ 1.7.6 | Global input recording and hotkeys |
| [PyInstaller](https://pypi.org/project/pyinstaller/) ≥ 5.13 | Packaging to `.exe` |

Bundled, not installed: the [Inter](https://rsms.me/inter/) and
[JetBrains Mono](https://www.jetbrains.com/lp/mono/) fonts, both under the SIL
Open Font License (licence texts in `assets/fonts/`).

---

## Building a standalone `.exe`

```bash
pip install -r requirements.txt
pyinstaller build.spec
```

The executable lands in `dist/AMT.exe` and needs no Python installation on
the target machine. The bundled fonts, the icon, and the user guide with its
images are packed into it (see `datas` in `build.spec`). Its name, version and
author in Explorer's Properties dialog come from `src/brand.py`. The icon,
`assets/amt.ico`, is drawn by `python scripts/make_icon.py`.

### Publishing a release

Releases are built by [`.github/workflows/release.yml`](../.github/workflows/release.yml),
never on a personal machine, so the published exe is reproducible from the
tagged source and carries no local paths:

1. Raise `VERSION` in `src/brand.py` and commit.
2. Tag and push: `git tag v1.0.1 && git push origin v1.0.1`.
3. The workflow checks the tag matches `VERSION`, runs lint and the full test
   suite, builds `AMT.exe`, and attaches it and `AMT.exe.sha256` to a new
   GitHub Release, with `.github/RELEASE_NOTES.md` as the text.

> **Note:** Windows Defender and other antivirus products frequently flag
> PyInstaller-packaged executables, and an app that installs a global keyboard
> hook is doubly likely to trip heuristics. This is a known false positive with
> PyInstaller bundles — build from source yourself if you want to verify there is
> nothing harmful in it.

`build/` and `dist/` are both git-ignored, deliberately: PyInstaller writes the
absolute path of every analysed file into `build/*.toc` and
`build/xref-build.html`, which would otherwise publish your Windows username,
your Python version, and a full inventory of your installed packages.

---

## Testing

```powershell
pip install -r requirements-dev.txt
python -m ruff check .
python -m unittest discover -s tests -t .
```

The suite runs against a temporary `AMT_HOME`, so it never touches real macros
or settings, stubs out the system-wide input hooks, and replaces the mouse and
keyboard with recording fakes. CI runs it on Windows for Python 3.11–3.13. The
definition of done and the list of failure modes this project has hit are in
[CONTRIBUTING.md](../CONTRIBUTING.md); release checks that need a real desktop
are in [QA-CHECKLIST.md](QA-CHECKLIST.md).
