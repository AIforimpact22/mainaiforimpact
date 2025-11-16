#!/usr/bin/env python3
# restart_tunnel_only.py
# Robust restart for a Windows service (Cloudflare tunnel), with auto-elevation and fallbacks.

import os
import re
import sys
import time
import ctypes
import subprocess

# ====== CONFIG ======
SERVICE = os.getenv("TUNNEL_SERVICE", "lafi-tunnel")   # change if your service name differs
STOP_TIMEOUT_S  = 60
START_TIMEOUT_S = 60
POLL_INTERVAL_S = 1.0
KILL_ON_STUCK   = True   # last resort: taskkill the old PID if stop doesn't work

# ====== helpers ======
def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def relaunch_as_admin():
    """Relaunch this script elevated via UAC and exit current process."""
    script = os.path.abspath(sys.argv[0])
    params = " ".join(['"%s"' % script] + [arg for arg in sys.argv[1:] if arg != "--elevated"] + ["--elevated"])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    if rc <= 32:
        print("[!] Elevation was denied or failed (ShellExecuteW rc=%r). Please run as Administrator." % rc, file=sys.stderr)
        sys.exit(5)
    sys.exit(0)

def run(cmd:list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, shell=False)

def sc_query(name: str, extended: bool = False) -> str:
    cmd = ["sc", "queryex" if extended else "query", name]
    return run(cmd).stdout

def parse_state(sc_output: str) -> str:
    # MS format: "STATE              : 4  RUNNING" or "STOPPED"
    m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", sc_output, re.I)
    return m.group(1).upper() if m else "UNKNOWN"

def parse_pid(sc_output: str):
    m = re.search(r"PID\s*:\s*(\d+)", sc_output, re.I)
    try:
        return int(m.group(1))
    except Exception:
        return None

def wait_for_state(name: str, target: str, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        out = sc_query(name)
        state = parse_state(out)
        if state == target:
            return True
        time.sleep(POLL_INTERVAL_S)
    return False

def stop_service(name: str) -> tuple[bool, int|None]:
    """Try to stop service gracefully; fallback to Stop-Service; optionally kill PID."""
    out0 = sc_query(name, extended=True)
    if not out0.strip():
        print(f"[!] Service '{name}' not found.", file=sys.stderr)
        return False, None

    st0 = parse_state(out0)
    pid0 = parse_pid(out0)
    print(f"[i] Current state: {st0}{f' (PID {pid0})' if pid0 else ''}")

    if st0 != "RUNNING":
        return True, pid0  # already not running

    print("[i] Stopping service (sc stop)...")
    res = run(["sc", "stop", name])
    if res.returncode != 0:
        # Often sc writes to stdout not stderr; print both for diagnostics.
        print(f"[!] sc stop rc={res.returncode}", file=sys.stderr)
        if res.stdout.strip(): print("    out:", res.stdout.strip(), file=sys.stderr)
        if res.stderr.strip(): print("    err:", res.stderr.strip(), file=sys.stderr)

    if wait_for_state(name, "STOPPED", STOP_TIMEOUT_S):
        return True, pid0

    # Fallback 1: PowerShell Stop-Service -Force
    print("[!] Service did not reach STOPPED; trying PowerShell Stop-Service -Force ...")
    ps = run(["powershell", "-NoProfile", "-NonInteractive",
              "-Command", f"Stop-Service -Name '{name}' -Force -ErrorAction Stop"])
    if ps.returncode == 0 and wait_for_state(name, "STOPPED", int(STOP_TIMEOUT_S/2)):
        return True, pid0

    # Fallback 2: kill the PID if still running
    outx = sc_query(name, extended=True)
    stx = parse_state(outx)
    pidx = parse_pid(outx)

    if KILL_ON_STUCK and pidx:
        print(f"[!] Forcing kill of PID {pidx} (taskkill /T /F) ...")
        tk = run(["taskkill", "/PID", str(pidx), "/T", "/F"])
        # Ignore rc; just wait a bit and re-check
        time.sleep(3)
        if wait_for_state(name, "STOPPED", int(STOP_TIMEOUT_S/2)):
            return True, pid0

    # Final state check
    outf = sc_query(name)
    print("[!] Could not stop the service cleanly. Current state:", parse_state(outf), file=sys.stderr)
    return False, pid0

def start_service(name: str) -> tuple[bool, int|None]:
    print("[i] Starting service (sc start)...")
    res = run(["sc", "start", name])
    if res.returncode != 0:
        print(f"[!] sc start rc={res.returncode}", file=sys.stderr)
        if res.stdout.strip(): print("    out:", res.stdout.strip(), file=sys.stderr)
        if res.stderr.strip(): print("    err:", res.stderr.strip(), file=sys.stderr)

    if not wait_for_state(name, "RUNNING", START_TIMEOUT_S):
        print("[!] Did not reach RUNNING in time.", file=sys.stderr)
        out = sc_query(name, extended=True)
        print(out)
        return False, parse_pid(out)

    out1 = sc_query(name, extended=True)
    return True, parse_pid(out1)

# ====== main ======
def main():
    if "--elevated" not in sys.argv and not is_admin():
        print("[i] Elevation required. Prompting for Administrator...")
        relaunch_as_admin()

    print(f"[i] Restarting tunnel service: {SERVICE}")

    stopped, old_pid = stop_service(SERVICE)
    if not stopped:
        sys.exit(2)

    ok, new_pid = start_service(SERVICE)
    if not ok:
        sys.exit(3)

    # If we had an old PID, confirm it changed (best-effort)
    if old_pid and new_pid and old_pid == new_pid:
        print(f"[!] Warning: PID did not change ({new_pid}). Service claims RUNNING but may not have restarted cleanly.")
    else:
        print(f"[✓] Service RUNNING (PID {new_pid})")

if __name__ == "__main__":
    main()
