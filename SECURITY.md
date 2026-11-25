# Security Policy

## What this software is

AMT (Advanced Macro Tool) records global keyboard and mouse input and replays it as synthetic
OS-level input. Two properties follow from that, and neither is a bug:

1. **A macro file is a plaintext keystroke log.** `src/models/macro.py` stores
   each key as the character that was actually typed. Anything typed during a
   recording — passwords, card numbers, recovery phrases, 2FA codes — is in that
   `.json` verbatim.
2. **Playback types with your privileges.** A macro is executable input. Playing
   back a file you did not record is equivalent to letting its author use your
   keyboard.

Reports that amount to "this program can log keystrokes" or "a macro file
contains what I typed" describe the tool working as designed, and are documented
in the README under [Safety and privacy](README.md#safety-and-privacy).

## Design boundaries

- **No network.** The application has no HTTP client, socket, telemetry, crash
  reporter, or update check. Its only third-party imports are `PyQt6` and
  `pynput`. Verify with `grep -rn "requests\|urllib\|http\|socket" src/ main.py`.
- **No account, no cloud, no background service.** The app runs only while its
  window is open, and stores only local files.
- **Files written:** macro `.json` files and `settings.json`, by default under
  `%USERPROFILE%\Documents\AdvancedMacroTool\`. The macro directory is configurable in
  Settings. Files are written with default filesystem permissions and are not
  encrypted — anything running as your user account can read them.
- **Listener lifetime:** the recording listeners exist only between "start
  recording" and "stop recording". The hotkey listener runs for the app's
  lifetime but matches only the bound combinations.

## Reporting a vulnerability

Please report anything that breaks the boundaries above — for example:

- input captured outside an explicit recording session
- any outbound network connection
- a macro file written outside the configured macro directory
- path traversal through a macro name or filename
- code execution triggered by loading or importing a crafted macro `.json`

Open a report through **GitHub Security Advisories** ("Report a vulnerability"
on the Security tab), which keeps the discussion private until a fix exists. If
that is unavailable, open a regular issue **without** a working exploit and ask
for a private channel.

Please include the OS build, Python version, the steps to reproduce, and what
you expected instead. Do not attach a real recorded macro — hand-write a minimal
`.json` that demonstrates the issue.

This is a hobby project maintained by one person; there is no formal SLA, but
reports will be looked at and credited.

## Supported versions

Fixes land on the default branch. There are no maintained release branches —
pull the latest `main` and rebuild.
