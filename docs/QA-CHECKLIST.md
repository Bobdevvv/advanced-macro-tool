# Manual QA checklist

The automated tests cover logic, storage and the interface, but they replace
the real mouse, keyboard and system-wide hooks with fakes. This list covers
what only a person at a real Windows desktop can confirm. Run it before a
release, and the relevant sections after any change to recording, playback,
hotkeys or the clicker.

Use a scratch window (Notepad and an empty desktop area) as the target, never
a real application.

## Start-up

- [ ] Opens with no white flash; the title bar matches the theme (dark themes
      dark, Light light).
- [ ] Starting a second copy shows "already running" and does not open a
      second window.
- [ ] Window size and position are restored from the last session.

## Recording

- [ ] F7 starts and stops; the macro appears in Player & Library.
- [ ] Neither the F7 press nor the Start/Stop button click is in the recording
      (play it back: nothing toggles, nothing clicks AMT's own button).
- [ ] "Record mouse movement" off: playback clicks at the right places.
- [ ] Recording while a macro plays or the clicker runs does not capture the
      simulated input.
- [ ] Closing the window while recording saves the recording.
- [ ] Recording with a name that already exists creates "name (2)".
- [ ] A finished recording is loaded straight away (F8 plays it); with the
      Behaviour switch off, the previous macro stays loaded.

## Keyboard in recordings

In Notepad, record and play back each of these:

- [ ] Ctrl+A, Ctrl+C, then End and Ctrl+V: the text is duplicated.
- [ ] Ctrl+Z undoes; Ctrl+S opens the save dialog.
- [ ] Shift+letters and Shift+digits type capitals and symbols (`A`, `!`).
- [ ] Holding a letter for about 2 seconds types a run of that letter, about
      as long as when recorded.
- [ ] Holding Shift while clicking (Shift+click selection) is reproduced.
- [ ] A macro recorded with an older version that used Ctrl shortcuts now
      replays them correctly.

## Playback

- [ ] Plays the loaded macro; F8 stops immediately, even during a long wait.
- [ ] No key or mouse button stays held after Stop (try stopping mid-drag and
      while a key is held).
- [ ] Speed 0.5× and 2× visibly change the pace.
- [ ] Loops: 2 plays twice; Forever repeats until stopped.
- [ ] Humanise: paths curve, clicks land on the same spots.
- [ ] Humanise with typing: a typed sentence comes out identical, with a
      slightly different rhythm each run; Ctrl shortcuts still work.
- [ ] Selecting a different macro while one plays does not change the
      controls until playback ends.

## Composer

- [ ] Open a real recording: keys, clicks and movement appear on the right
      tracks; hovering shows the right details.
- [ ] Drag-select a stretch, delete it, Test play: the rest plays without it.
- [ ] Drag a selected stretch to another place; Test play confirms the new
      order.
- [ ] Cut the end off a held key, Test play: the key is not left held.
- [ ] Shorten pauses on a slow recording: noticeably faster, typing intact.
- [ ] Build a macro from Text + Key combination (Ctrl+A, Ctrl+C) + Wait,
      play it in Notepad: it types, selects and copies.
- [ ] Save after renaming keeps the original; Save without renaming
      updates it (and the Player shows the change).
- [ ] Unsaved changes: opening another macro or closing AMT asks first.
- [ ] Zoom in on a long macro and scroll sideways; nothing lags.
- [ ] Ctrl+Z / Ctrl+Y undo and redo with the focus on a button or the library
      list, not only on the timeline; in the name field they edit the text.
- [ ] Ctrl + mouse wheel over the timeline zooms around the pointer.
- [ ] F9 from another application plays the Composer's current (unsaved)
      edit there; F9 again stops it.

## Help

- [ ] Scrolling the guide moves the highlight in the contents list along.
- [ ] Help opens the guide; the contents list jumps to each section.
- [ ] Links inside the guide jump to their section; screenshots fit the
      window when it is made narrower.
- [ ] Readable in every theme (tables, links, headings).
- [ ] In the built `.exe`, Help shows the guide with its screenshots.

## Auto Click

- [ ] F10 starts and stops; the buttons on the page follow.
- [ ] Stop after N clicks stops at exactly N.
- [ ] Pick + fixed point works on **every monitor**, including one left of or
      above the main monitor (negative coordinates).
- [ ] At **125 % and 150 % display scaling**, Pick hits exactly the picked
      spot.

## Hotkeys

- [ ] Bind captures F-keys, Ctrl+letter, Shift+digit, Ctrl+Shift+punctuation.
- [ ] Each of those bindings actually fires from another application.
- [ ] Changing a hotkey or theme saves by itself (no Save button); a duplicate
      or invalid hotkey turns red with the reason under the hotkeys.
- [ ] Ctrl+F7 does not trigger a plain F7 binding.

## Library and files

- [ ] Delete and Backspace in the macro list ask (Enter = Yes, Esc = No), then delete; the next
      macro is highlighted. Backspace in the filter box only edits the text.
- [ ] Rename by letter case only ("test" to "Test") keeps the macro.
- [ ] Rename onto an existing name is refused.
- [ ] A damaged `.json` in the macro folder is listed with a warning sign and
      opening it shows a clear error; the rest of the library still works.
- [ ] Export, then **Import…** (and dragging the file onto the list)
      round-trips; importing a name that exists creates "name (2)"; a
      non-macro .json is refused with a message.
- [ ] After Unload, clicking the selected macro loads it again.
- [ ] Settings → macro folder on another drive works; an unusable one is
      refused and the old folder stays in use.

## Display

- [ ] Every theme: text readable, nothing invisible, focus outlines visible.
- [ ] Narrow window (about 760 px): sidebar collapses, nothing is cut off,
      "More below" appears where pages scroll.
- [ ] (i) icons show their explanation instantly and hide on leave.
