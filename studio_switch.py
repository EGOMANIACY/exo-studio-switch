import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

NAME = "EXO Studio Switch"
SERVER = os.environ.get("EXO_STUDIO_SWITCH_URL", "http://207.127.92.128:8787/studio-switch")
POLL_SECONDS = 10
WARNING_SECONDS = 30
PLACE = re.compile(r"placeId[: ](\d+)", re.I)
UNIVERSE = re.compile(r"universeId[: ](\d+)", re.I)
GOLD = "#C9A227"
DARK = "#111111"
WINDOWS = sys.platform == "win32"

if WINDOWS:
    import ctypes
    import winreg

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    NO_WINDOW = subprocess.CREATE_NO_WINDOW
    DATA = Path(os.environ["APPDATA"]) / NAME
else:
    import fcntl

    NO_WINDOW = 0
    CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    AUTOSTART = CONFIG / "autostart" / "exo-studio-switch.desktop"
    DATA = CONFIG / "exo-studio-switch"

DATA.mkdir(parents=True, exist_ok=True)
SETTINGS = DATA / "settings.json"
LOG = DATA / "log.txt"
logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(message)s")


@dataclass
class Studio:
    pid: int
    place_id: str
    universe_id: str


def command() -> list[str]:
    return [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]


def open_path(target: str):
    if WINDOWS:
        os.startfile(target)
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def starts_with_system() -> bool:
    if not WINDOWS:
        return AUTOSTART.exists()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, NAME)
            return True
    except FileNotFoundError:
        return False


def set_starts_with_system(on: bool):
    if not WINDOWS:
        if on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            line = " ".join(f'"{part}"' for part in command())
            AUTOSTART.write_text(f"[Desktop Entry]\nType=Application\nName={NAME}\nExec={line}\nX-GNOME-Autostart-enabled=true\n")
        else:
            AUTOSTART.unlink(missing_ok=True)
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, " ".join(f'"{part}"' for part in command()))
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass


def first_run():
    if SETTINGS.exists():
        if starts_with_system():
            set_starts_with_system(True)
        return
    set_starts_with_system(True)
    SETTINGS.write_text(json.dumps({"firstRun": time.time()}))


def already_running() -> bool:
    if WINDOWS:
        return bool(ctypes.windll.kernel32.CreateMutexW(None, False, "EXO.StudioSwitch")) and ctypes.windll.kernel32.GetLastError() == 183
    global LOCK
    LOCK = open(DATA / "running.lock", "w")
    try:
        fcntl.flock(LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True


def publishing() -> list[dict]:
    with urllib.request.urlopen(SERVER, timeout=10) as response:
        return json.load(response).get("publishing", [])


def studio_lines() -> list[tuple[int, str]]:
    if not WINDOWS:
        found = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                line = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if "RobloxStudio" in line:
                found.append((int(entry.name), line))
        return found
    query = "Get-CimInstance Win32_Process -Filter \"Name like 'RobloxStudio%'\" | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", query], capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    if not out:
        return []
    found = json.loads(out)
    return [(p["ProcessId"], p.get("CommandLine") or "") for p in (found if isinstance(found, list) else [found])]


def studios() -> list[Studio]:
    result = []
    for pid, line in studio_lines():
        place = PLACE.search(line)
        universe = UNIVERSE.search(line)
        if place:
            result.append(Studio(pid, place.group(1), universe.group(1) if universe else ""))
    return result


def warn(names: list[str], seconds: int):
    window = tk.Tk()
    window.title(NAME)
    window.configure(bg=DARK, padx=28, pady=22)
    window.attributes("-topmost", True)
    window.resizable(False, False)
    tk.Label(window, text=f"EXO is publishing {', '.join(names)}", fg=GOLD, bg=DARK, font=("Segoe UI Semibold", 13)).pack(anchor="w")
    tk.Label(
        window,
        text="Studio has to close for it to go through. Team Create keeps your edits and script drafts,\nand Studio opens the place again when the publish is done.",
        fg="#D8D8D8", bg=DARK, font=("Segoe UI", 10), justify="left",
    ).pack(anchor="w", pady=(6, 14))
    count = tk.Label(window, fg="#FFFFFF", bg=DARK, font=("Segoe UI Semibold", 11))
    count.pack(anchor="w")
    tk.Button(window, text="Close Studio now", command=window.destroy, bg=GOLD, fg=DARK, relief="flat", padx=12, pady=4).pack(anchor="e", pady=(14, 0))
    left = {"seconds": seconds}

    def tick():
        if left["seconds"] <= 0:
            window.destroy()
            return
        count.config(text=f"Closing in {left['seconds']} s")
        left["seconds"] -= 1
        window.after(1000, tick)

    window.protocol("WM_DELETE_WINDOW", lambda: None)
    tick()
    window.mainloop()


def close(studio: Studio):
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(studio.pid), "/F"], capture_output=True, creationflags=NO_WINDOW)
    else:
        try:
            os.kill(studio.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    logging.info("closed Studio %s on place %s", studio.pid, studio.place_id)


def reopen(studio: Studio):
    open_path(f"roblox-studio:1+launchmode:edit+task:EditPlace+placeId:{studio.place_id}+universeId:{studio.universe_id}")
    logging.info("reopened place %s", studio.place_id)


def watch(stop: threading.Event):
    closed: dict[int, list[Studio]] = {}
    while not stop.is_set():
        try:
            runs = {run["run"]: run for run in publishing()}
            for run_id, run in runs.items():
                targets = {place["id"]: place["name"] for place in run["places"]}
                blocking = [s for s in studios() if s.place_id in targets]
                if blocking:
                    warn(sorted({targets[s.place_id] for s in blocking}), WARNING_SECONDS)
                    for studio in blocking:
                        close(studio)
                    closed.setdefault(run_id, []).extend(blocking)
            for run_id in list(closed.keys() - runs.keys()):
                for studio in {s.place_id: s for s in closed.pop(run_id)}.values():
                    reopen(studio)
        except Exception:
            logging.exception("check failed")
        stop.wait(POLL_SECONDS)


def icon_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 60, 60), radius=12, fill=DARK, outline=GOLD, width=4)
    draw.rectangle((22, 18, 42, 24), fill=GOLD)
    draw.rectangle((22, 29, 38, 35), fill=GOLD)
    draw.rectangle((22, 40, 42, 46), fill=GOLD)
    draw.rectangle((22, 18, 28, 46), fill=GOLD)
    return image


def tray(stop: threading.Event):
    import pystray

    def quit_app(icon):
        stop.set()
        icon.stop()

    pystray.Icon(
        NAME,
        icon_image(),
        f"{NAME}: closes Studio for EXO publishes",
        pystray.Menu(
            pystray.MenuItem("Start with Windows" if WINDOWS else "Start on login", lambda: set_starts_with_system(not starts_with_system()), checked=lambda _: starts_with_system()),
            pystray.MenuItem("Open log", lambda: open_path(str(LOG))),
            pystray.MenuItem("Quit", quit_app),
        ),
    ).run()


def main():
    if "--test-warning" in sys.argv:
        warn(["Burial Grounds"], 10)
        return
    if "--check" in sys.argv:
        print(studios())
        print(publishing())
        return
    if already_running():
        return
    first_run()
    stop = threading.Event()
    threading.Thread(target=watch, args=(stop,), daemon=True).start()
    logging.info("watching %s", SERVER)
    try:
        tray(stop)
    except Exception:
        logging.exception("no tray icon, running without one")
        stop.wait()


if __name__ == "__main__":
    main()
