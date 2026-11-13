import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import winreg
from dataclasses import dataclass
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

NAME = "EXO Studio Switch"
SERVER = os.environ.get("EXO_STUDIO_SWITCH_URL", "http://207.127.92.128:8787/studio-switch")
POLL_SECONDS = 10
WARNING_SECONDS = 30
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PLACE = re.compile(r"placeId[: ](\d+)", re.I)
UNIVERSE = re.compile(r"universeId[: ](\d+)", re.I)
NO_WINDOW = subprocess.CREATE_NO_WINDOW
GOLD = "#C9A227"
DARK = "#111111"

DATA = Path(os.environ["APPDATA"]) / NAME
DATA.mkdir(parents=True, exist_ok=True)
SETTINGS = DATA / "settings.json"
logging.basicConfig(filename=DATA / "log.txt", level=logging.INFO, format="%(asctime)s %(message)s")


@dataclass
class Studio:
    pid: int
    place_id: str
    universe_id: str


def command() -> str:
    return f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'


def starts_with_windows() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, NAME)
            return True
    except FileNotFoundError:
        return False


def set_start_with_windows(on: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass


def first_run():
    if SETTINGS.exists():
        if starts_with_windows():
            set_start_with_windows(True)
        return
    set_start_with_windows(True)
    SETTINGS.write_text(json.dumps({"firstRun": time.time()}))


def publishing() -> list[dict]:
    with urllib.request.urlopen(SERVER, timeout=10) as response:
        return json.load(response).get("publishing", [])


def studios() -> list[Studio]:
    query = "Get-CimInstance Win32_Process -Filter \"Name like 'RobloxStudio%'\" | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", query], capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    if not out:
        return []
    found = json.loads(out)
    result = []
    for process in found if isinstance(found, list) else [found]:
        line = process.get("CommandLine") or ""
        place = PLACE.search(line)
        universe = UNIVERSE.search(line)
        if place:
            result.append(Studio(process["ProcessId"], place.group(1), universe.group(1) if universe else ""))
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
    subprocess.run(["taskkill", "/PID", str(studio.pid), "/F"], capture_output=True, creationflags=NO_WINDOW)
    logging.info("closed Studio %s on place %s", studio.pid, studio.place_id)


def reopen(studio: Studio):
    os.startfile(f"roblox-studio:1+launchmode:edit+task:EditPlace+placeId:{studio.place_id}+universeId:{studio.universe_id}")
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


def main():
    if "--test-warning" in sys.argv:
        warn(["Burial Grounds"], 10)
        return
    if "--check" in sys.argv:
        print(studios())
        print(publishing())
        return
    if ctypes.windll.kernel32.CreateMutexW(None, False, "EXO.StudioSwitch") and ctypes.windll.kernel32.GetLastError() == 183:
        return
    first_run()
    stop = threading.Event()
    threading.Thread(target=watch, args=(stop,), daemon=True).start()
    logging.info("watching %s", SERVER)

    def quit_app(icon: pystray.Icon):
        stop.set()
        icon.stop()

    pystray.Icon(
        NAME,
        icon_image(),
        f"{NAME}: closes Studio for EXO publishes",
        pystray.Menu(
            pystray.MenuItem("Start with Windows", lambda: set_start_with_windows(not starts_with_windows()), checked=lambda _: starts_with_windows()),
            pystray.MenuItem("Open log", lambda: os.startfile(DATA / "log.txt")),
            pystray.MenuItem("Quit", quit_app),
        ),
    ).run()


if __name__ == "__main__":
    main()
