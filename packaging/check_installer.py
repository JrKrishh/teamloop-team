"""Install Super Agents from its Setup.exe the way a new user would, check what they get, open it twice, then uninstall
it and check it's gone. CI runs this on a clean Windows machine:  python packaging/check_installer.py dist/SuperAgents-Setup.exe"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import winreg
from pathlib import Path

SETUP = Path(sys.argv[1]).resolve()
APP = Path(os.environ["LOCALAPPDATA"]) / "TeamLoop"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{A16697DB-3F8E-4480-860F-95FE57C36965}_is1"
failed = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail else ""), flush=True)
    if not ok:
        failed.append(name)


def folder(name):  # the user's Start-menu Programs and Desktop folders, wherever Windows keeps them
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
        return Path(os.path.expandvars(winreg.QueryValueEx(k, name)[0]))


def on_path():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        try:
            path = winreg.QueryValueEx(k, "Path")[0]
        except FileNotFoundError:
            path = ""
    return str(APP).lower() in [p.lower() for p in path.split(";")]


def listed():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL) as k:
            return {n: winreg.QueryValueEx(k, n)[0] for n in ("DisplayName", "DisplayVersion")}
    except FileNotFoundError:
        return None


def until(pred, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(1)
    return False


shortcuts = [folder("Programs") / "Super Agents.lnk", folder("Desktop") / "Super Agents.lnk"]
r = subprocess.run([str(SETUP), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=900)
check("the installer runs to the end, no admin", r.returncode == 0, f"exit {r.returncode}")
check("the app and the CLI are in %LOCALAPPDATA%\\TeamLoop", (APP / "SuperAgents.exe").exists() and (APP / "teamloop.exe").exists())
check("teamloop runs from there", subprocess.run([str(APP / "teamloop.exe"), "status"], capture_output=True).returncode == 0)
check("Start-menu and desktop shortcuts", all(s.exists() for s in shortcuts), ", ".join(str(s) for s in shortcuts))
check("teamloop is on the user's PATH", on_path())
check("listed in Settings > Apps, with its version", (listed() or {}).get("DisplayName") == "Super Agents", json.dumps(listed()))

# Open it, then open it again: the second launch hands over to the open window and quits
opened = Path(os.environ["USERPROFILE"]) / ".teamloop" / "window.json"
opened.unlink(missing_ok=True)
first = subprocess.Popen([str(APP / "SuperAgents.exe")])
answer = None
if until(opened.exists, 90):
    info = json.loads(opened.read_text(encoding="utf-8"))
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/boot", headers={"X-App-Key": info["key"]})
    with urllib.request.urlopen(req, timeout=15) as res:
        answer = res.status
check("the app opens and its local server answers", answer == 200, "" if answer else "it never said where it was")
second = subprocess.Popen([str(APP / "SuperAgents.exe")])
try:
    code = second.wait(timeout=60)
except subprocess.TimeoutExpired:
    second.kill()
    code = None
check("a second launch shows the open window and quits", code == 0 and first.poll() is None,
      f"second exited {code}; the first is {'still open' if first.poll() is None else 'gone'}")
first.kill()
first.wait(timeout=60)

subprocess.run([str(APP / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=600)
check("uninstalling removes the app and its Settings entry",  # the uninstaller carries on from a copy in %TEMP%
      until(lambda: not (APP / "SuperAgents.exe").exists() and listed() is None, 180))
check("and its shortcuts", not any(s.exists() for s in shortcuts))
check("and its PATH entry", not on_path())
print(f"{'all checks pass' if not failed else str(len(failed)) + ' failed: ' + ', '.join(failed)}")
sys.exit(1 if failed else 0)
