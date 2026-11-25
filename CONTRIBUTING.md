# Contributing

Thanks for taking a look. This is a small single-maintainer project, so the bar
is "does it work, does it fit the existing shape" rather than a formal process.

## Development setup

See [README → Setup](README.md#setup) for the full walkthrough. The short form:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Windows only. `pynput`'s global listeners go through its `_win32` backends, and
several behaviours (elevated-window focus, DPI scaling of recorded coordinates)
have no cross-platform equivalent.

### Checks

```powershell
pip install -r requirements-dev.txt            # once: adds ruff
python -m ruff check .                         # lint: undefined names, likely bugs
python -m unittest discover -s tests -t .      # ~90 tests, about 15 seconds
```

After a change to how a page looks, regenerate the documentation images
with `python scripts/docs_screenshots.py` (demo macros, temporary folder, so
nothing personal ends up in them) and look at every image before committing.

The tests never touch your real macros or settings: `tests/support.py` points
`AMT_HOME` at a temporary folder before anything is imported, stubs out the
system-wide input hooks, and replaces the mouse and keyboard with recording
fakes, so they never move your cursor or type anything. CI
(`.github/workflows/ci.yml`) runs both commands on Windows for every push.

## Definition of done

A change is finished when **all** of these are true, not when the happy path
works once:

1. `ruff check .` and the full test suite pass.
2. **Every bug fix comes with a test that fails without the fix.** Check it:
   undo the fix, watch the test fail, redo it.
3. New behaviour has tests for its edges, not only its middle (see the
   checklist below).
4. Anything the tests cannot reach is walked through by hand using
   [docs/QA-CHECKLIST.md](docs/QA-CHECKLIST.md) (real playback, real hotkeys,
   multiple monitors, display scaling).
5. Every statement in the README, the guide and the tooltips about what the
   change does has been checked against the code, not written from memory.

### Failure modes this project has actually hit

Each of these shipped at least once. Before calling a change done, go through
the ones that apply.

| Area | Check |
|---|---|
| **Qt layout** | Widgets created on a page that is not on screen yet have no real size. Anything positioned by hand (overlays, labels inside fields) must also position itself in `showEvent`, and must test with `isHidden()`, not `isVisible()`. Test the page *after* switching to it. |
| **Qt text** | `&` in a button or label is a keyboard-shortcut marker; write `&&`. |
| **Qt lifetime** | `deleteLater()` only takes effect in the event loop: remove a widget from its layout with `setParent(None)` if it must be gone now. Dialogs and timers created per click must be deleted or reused. |
| **Qt event filters** | Never override `eventFilter` on a `QScrollArea` (every `Page` is one): Qt routes its own viewport events through it, even during `__init__`, and an error there aborts the process silently. Install a separate small `QObject` filter instead. |
| **Qt shortcuts** | Never bind the same key twice in one scope (e.g. Ctrl+Y plus the standard Redo, which also contains Ctrl+Y): Qt treats it as ambiguous and fires *neither*. Window shortcuts only fire in the active window, so tests must activate it (`QTest.qWaitForWindowActive`) or they pass without testing anything. |
| **Shutdown order** | At exit Qt destroys top-level and shared widgets in no fixed order. Code in `hideEvent`/`leaveEvent` that touches a shared object must check `sip.isdeleted` first. Test it deterministically (delete the object, then trigger the event), because ordering bugs only show up some of the time. |
| **Qt errors** | An exception escaping a slot used to kill the app. `src/ui/errors.py` now catches it, but expected failures (file I/O, user input) still need their own specific message. |
| **Threads** | Worker loops wrap their body in `try/finally` that releases held input and reports "finished". Widgets are only touched on the UI thread (via `_Bridge`). |
| **Timing** | A label that promises a rate must use the same formula as the loop that produces it, and a loop's waits add up (a hold plus an interval is not the interval). Schedule from a clock, not by sleeping after each step, and test the rate. On Windows a wait lasts at least one 15.6 ms timer tick unless the resolution is raised. |
| **Input values** | Test every unit and the *limits* of every field: below minimum, above maximum, a unit the field does not offer, comma decimals, empty and invalid text. |
| **Screen coordinates** | They can be **negative** (monitors left of or above the main one). pynput uses physical pixels; Qt (`QCursor.pos()`, widget geometry) uses scaled pixels. Never mix them. |
| **Keyboard** | pynput reports the *character*, which changes with modifiers (Ctrl+R is `"\x12"`, Shift+1 is `"!"`). This applies everywhere keys are handled: hotkey matching **and** recording/playback. Identify and replay keys by virtual key code. Ignore `injected` (simulated) input in listeners. Test with modifiers held, not only plain keys. A pynput listener does not stop a key reaching other programs; that takes `win32_event_filter` plus `suppress_event()`, and a suppressed event never reaches `on_press`. |
| **Files on Windows** | Names are case-insensitive (`test` and `Test` are one file); `CON`, `NUL`, `COM1`… are devices; trailing dots and spaces are stripped. Never overwrite without asking; write atomically (temp file + `os.replace`). |
| **Busy states** | Check every action *while* recording, playing and clicking: browsing, deleting, renaming, closing the window. |
| **Screenshots** | A page taller than the window needs a second, scrolled screenshot, or the guide shows only its top half. `scripts/docs_screenshots.py` makes them; `tests/test_docs.py` checks that it still runs, that every image is used and that every referenced image exists. |
| **Claims** | Tooltips and docs describe behaviour, so they are part of the change and need checking like code. `tests/test_docs.py` checks every link; the content itself still needs reading. The user guide stays non-technical; implementation details go in `docs/TECHNICAL.md`. |
| **Tooling** | Scripts containing backslashes must be written to a file, not passed through a shell heredoc, which silently rewrites `\\` and `\n`. |

## The one rule that matters

**Never commit a recorded macro, and never commit `settings.json`.**

A macro is a literal keystroke log — see
[SECURITY.md](SECURITY.md). `settings.json` contains this machine's absolute
macro-storage path. `.gitignore` already excludes `macros/`, `*.macro.json`,
`Untitled-*.json` and `settings.json`; do not relax those patterns to include a
sample file. If you need a fixture, hand-write the JSON so nothing that touched
a real keyboard is published.

The same applies to `build/`, `dist/` and `__pycache__/`: PyInstaller `.toc`
files and `.pyc` files both embed the absolute build path, which discloses your
Windows username and folder layout. They are git-ignored for that reason. Run
`git status --short` before committing and make sure nothing from those
directories is staged.

## Architecture

```
src/core/     pure logic, no Qt imports, runs on daemon threads
src/models/   Macro / MacroEvent dataclasses + JSON serialisation
src/storage/  macro file persistence
src/ui/       everything Qt
```

Keep that split. If a core module needs to tell the UI something, it takes a
plain callable — it does not import Qt.

### Threading

The recorder, player, and autoclicker all run on daemon threads. Qt widgets may
only be touched from the UI thread, so every callback crosses back through
`_Bridge(QObject)` in `main_window.py`, which re-emits it as a `pyqtSignal`. Qt
queues those across threads automatically.

**Do not call a widget method directly from a worker thread.** Add a signal to
`_Bridge` and connect it.

### Adding a page

1. Create `src/ui/<name>_tab.py` with a subclass of `Page` (from
   `src/ui/widgets.py`; it gives you the title header, scrolling and the
   "More below" hint) that exposes `pyqtSignal`s for anything the app needs to
   act on. Build the content from `Card`s, inside a `ResponsiveGrid` if they
   should sit side by side on wide windows.
2. Import it in `main_window.py`, instantiate it, add a `(label, glyph)` entry
   to `MainWindow._NAV` and the page to the stack in `_build_shell()`, in the
   same position.
3. Wire its signals in `MainWindow._connect_all`, not inside the page.

### Adding a theme

Add a palette dict to `_PALETTES` in `src/ui/theme.py` with every token the
existing palettes define. `_TEMPLATE.format(**tokens)` raises `KeyError` on a
missing key. `THEME_NAMES` and the Settings swatches populate themselves from
the dict.

**Look:** pages are divided by *ruled sections* (a `Card` with a title: hairline
rule, small uppercase mono title, no box), not by bordered boxes. A filled
*panel* (a `Card` without a title, or `panel=True`) is reserved for things that
need emphasis, such as live read-outs. No icons in front of section titles.
Corners stay small (3–6 px); only chips such as pills are fully round.

**Styling rules:** style rules go in `_TEMPLATE` only, using tokens. Widgets opt
in with an object name (`Card`, `PageTitle`, …) or a dynamic property
(`variant="primary"`, `tone="danger"`); change a property at runtime with
`widgets.set_prop()` so the style is re-applied. Never hard-code a colour in a
widget, or it will break in six themes. Icons follow the theme automatically
when assigned with `icons.bind()`.

### Macro file format

`name`, `description`, `created_at` (Unix timestamp), and `events[]`. Each event
has `type` and `timestamp` plus whichever of `x`, `y`, `button`, `pressed`,
`dx`, `dy`, `key` apply — `MacroEvent.to_dict()` drops `None` fields.

Key events carry `key`, a readable name: the character (`"a"`), a named
special key (`"Key.space"`), or a virtual key code (`"vk:67"`) when the
character is missing or unprintable. Character keys also carry `vk`, the
physical key's virtual key code, and `_event_key()` in `src/core/player.py`
replays that physical key: the character alone is ambiguous (Ctrl+C reports
`"\x03"`). Files without `vk`, from older versions, still play;
`_str_to_key()` maps their control characters back to letter keys.
**If you change this encoding, keep the reader backwards-compatible** —
people have saved macro libraries.

## Style

Match the surrounding code: `from __future__ import annotations`, type hints on
signatures, dataclasses for data, and the aligned-comment/section-banner comment
style already in use. `ruff check .` must pass (configured in `pyproject.toml`);
no formatter is enforced.

## Pull requests

One change per PR. Say what you changed, which tests cover it, and what you
checked by hand from the QA checklist. Bug fixes
and small features are welcome as PRs directly; for anything that reshapes the
UI or the macro format, open an issue first so the design can be agreed on
before you write it.
