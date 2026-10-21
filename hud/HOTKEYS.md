# Irene's global hotkeys

Registered in `src-tauri/src/lib.rs`. A global hotkey is taken from **every** app
while Irene runs, so each one here was checked two ways:

- **on this PC**: `core/scripts/hotkey_probe.py` asks Windows to register each
  combination and lets it go at once (no keys are pressed or sent). "Taken" means
  another running app already owns it globally.
- **in common apps**: shortcuts that live inside an app (Word, Google Docs,
  browsers, Explorer) are invisible to the probe; those come from each app's
  documented shortcuts.

## Everyday

| Keys | Does | Checked |
|---|---|---|
| Ctrl+Alt+I | summon her | free on this PC. Word uses it for print preview (rarely) |
| Ctrl+Alt+T | type to her (the command bar) | free |
| Ctrl+Alt+Esc | hide her | free (Task Manager is Ctrl+**Shift**+Esc) |
| Ctrl+Alt+D | toggle click-through | free on this PC. Word: insert endnote |
| Ctrl+Alt+Shift+O | screens-off mode: monitors off, PC awake, she keeps listening (config/power.yaml enables it) | free on this PC |
| Ctrl+Alt+Shift+S | study mode on/off - no voice needed; studies the last subject, or the Sicilian the first time | free on this PC (probed 2026-10-18). Photoshop (legacy): Save for Web |
| Ctrl+Alt+Shift+M | shiai on/off - no voice needed ("M" for match) | free on this PC (probed 2026-10-18) |
| Ctrl+Alt+Shift+L | lecture capture on/off - she transcribes what the PC plays (core/irene/lecture.py); off by default | free on this PC (registered at launch) |
| Ctrl+Alt+H | hand control on/off - his hand as the system-wide pointer (off = mouse only) | free on this PC. Word: highlight (some builds) |
| Ctrl+Alt+A | cycle her activity (debug) | free on this PC. QQ/WeChat screenshot while they run |

## Operator, captures, corpus - all Ctrl+Alt+Shift

| Keys | Does | Was | Why it moved |
|---|---|---|---|
| Ctrl+Alt+Shift+R | voice corpus recorder | Ctrl+Alt+R | **taken on this PC** by the screenshot tool |
| Ctrl+Alt+Shift+P | pin her on top of everything / unpin (default: an ordinary window - she is on top only from a summon until another window is activated) | (new) | free on this PC (probed) |
| Ctrl+Alt+Shift+K | skit mode: start the newest config/skits/ file (mid-skit: start it over) | (new) | free on this PC (probed) |
| Ctrl+Alt+Shift+X | skit mode: abort the take | (new) | free on this PC (probed) |
| Ctrl+Alt+Shift+C | summon gesture capture | Ctrl+Alt+C | Word types (c); AltGr+C on European layouts |
| Ctrl+Alt+Shift+1..5 | zoom / keiko captures | Ctrl+Alt+1..5 | Google Docs and Word: Heading 1-5 |
| Ctrl+Alt+Shift+6..7 | keiko_kamae / keiko_confusers captures | (new) | free on this PC (probed) |
| Ctrl+Alt+Shift+8 | zoom_panel capture (zoom at the panel's distance) | (new) | free on this PC (probed) |
| Ctrl+Alt+Shift+9 | keiko_strikes capture: men, kote, gyaku-dou and their confusers (core/scripts/strike_train.py) | (new) | free on this PC (probed 2026-10-12) |
| Ctrl+Alt+Shift+0 | hits capture: seated chisai men at her and every fast desk movement that isn't one - a measurement of what the camera sees at the desk (core/scripts/hits_diagnose.py); nothing trains on it | (new) | free on this PC (probed 2026-10-17) |
| Ctrl+Alt+Shift+F6 | cycle state | F6 | browsers: address bar; Office: next pane |
| Ctrl+Alt+Shift+F7 | panel debug push | F7 | Chrome/Edge: caret browsing; Word: spelling |
| Ctrl+Alt+Shift+F8 | cycle emotion | F8 | Word: extend selection |
| Ctrl+Alt+Shift+F9 | debug overlay | F9 | Word: update fields |
| Ctrl+Alt+Shift+F10 | calibration | F10 | every Windows app: the menu bar |
| Ctrl+Alt+Shift+F11 | preview everything | F11 | browsers, Explorer: full screen |

Plain F9 / F10 still work while the HUD itself has focus (a window keydown, not a
global hotkey), so they take nothing from other apps.

## Given up

- **Ctrl+Alt+Space** - it was the spec for the command bar, but it is the Claude
  desktop app's quick entry (**taken on this PC**). Irene no longer registers it:
  when she started first she took it from Claude. Ctrl+Alt+T does the job.

## Only during a corpus session

- **Space** (redo the take) and **Esc** (stop) are held globally while a session
  runs - he reads from a metre away and the HUD never has focus - and released
  the moment it ends.

## Not usable

- **F12**: Windows reserves it for the debugger; it can never be a global hotkey.
- **Win+anything**: Windows' own.

Probe again after installing something new (HUD closed, or her own keys show taken):

    core\.venv\Scripts\python core\scripts\hotkey_probe.py
