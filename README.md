# EXO Studio Switch

Roblox won't publish a place while someone has it open in Studio. When the EXO publisher is about to publish a place you have open, this app warns you for 30 seconds, closes that Studio window, and opens it again when the publish is done. Your other Studio windows aren't touched.

Team Create already has your map edits and Studio keeps your script drafts, so a close loses nothing except edits from the last second or two.

## Install
1. Download **EXO.Studio.Switch.exe** from the [latest release](../../releases/latest).
2. Run it. Windows may say "Windows protected your PC" because the app isn't code-signed: click **More info**, then **Run anyway**.
3. It sits in the system tray (the gold E). It starts with Windows from then on.

Right-click the tray icon to turn **Start with Windows** off, open the log, or quit.

## How it works
Every 10 seconds the app asks the EXO publisher bot which places are being published right now (`/studio-switch` on the bot's server). That list only holds place IDs and names. If Roblox Studio on this PC has one of those places open, the app shows the warning, then ends that Studio process. Once the publish is no longer listed, it opens the place again with a `roblox-studio:` link.

The app holds no keys or tokens. Its settings and log are in `%APPDATA%\EXO Studio Switch`.

## Building
Push a tag like `v1.0.0`, and the Build workflow makes the exe and attaches it to a release. To run from source: `pip install -r requirements.txt`, then `python studio_switch.py`.
