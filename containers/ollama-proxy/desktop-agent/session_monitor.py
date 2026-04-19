"""
Runs as a Task Scheduler job under the logged-in user account.
Polls Win32 GetLastInputInfo and writes idle time to a shared state file
that desktop_agent.py reads to decide whether a user is actively at the machine.
"""

import ctypes
import json
import sys
import time
from pathlib import Path

from config import config


class LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def getSecondsSinceLastInput() -> float:
    """Use Win32 GetLastInputInfo to measure how long input devices have been idle."""
    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(LastInputInfo)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    ticksNow = ctypes.windll.kernel32.GetTickCount()
    idleMilliseconds = (ticksNow - info.dwTime) & 0xFFFFFFFF  # handle tick counter wraparound
    return idleMilliseconds / 1000.0


def main():
    if sys.platform != "win32":
        raise RuntimeError("session_monitor must run on Windows")

    stateFile: Path = config.paths.stateFile
    stateFile.parent.mkdir(parents=True, exist_ok=True)

    while True:
        stateFile.write_text(json.dumps({
            "secondsSinceInput": getSecondsSinceLastInput(),
            "timestamp": time.time(),
            "userLoggedIn": True,
        }))
        time.sleep(config.monitor.pollIntervalSeconds)


if __name__ == "__main__":
    main()
