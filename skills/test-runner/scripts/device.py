#!/usr/bin/env python3
"""Measures the screen currently on the connected device against a Figma spec, as numbers, so the
agent never has to look at a screenshot. Maestro MCP drives the device; it has no way to measure dp
or read a pixel colour, which is the only reason this script exists.

  device.py nodes [substr]          the screen as one line per usable node: id | text | x,y wxh dp | flags
  device.py check <spec.tsv>        compare a Figma spec against the screen; exit 1 on any diff
  device.py crop <id> <out.png>     save just that node's pixels, to look at only when check fails

Stdlib only. Uses `adb` from PATH, else the Android Studio SDK default; one device (or ANDROID_SERIAL).
"""
import os
import shutil
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zlib


# Agent shells often lack the SDK on PATH; Android Studio's default install location is the fallback.
SDK_ROOT = (
    os.environ.get("ANDROID_HOME")
    or os.environ.get("ANDROID_SDK_ROOT")
    or os.path.expanduser("~/Library/Android/sdk" if sys.platform == "darwin" else "~/Android/Sdk")
)
ADB = shutil.which("adb") or os.path.join(SDK_ROOT, "platform-tools", "adb")


def adb(*args, binary=False):
    out = subprocess.run([ADB, *args], capture_output=True, check=True).stdout
    return out if binary else out.decode("utf-8", "replace")


def density():
    # An override (set by `wm density`) is what layout uses, so it wins over the physical value.
    lines = adb("shell", "wm", "density").splitlines()
    vals = {l.split(":")[0].strip(): int(l.split(":")[1]) for l in lines if ":" in l}
    return vals.get("Override density") or vals["Physical density"]


DRIVER = "dev.mobile.maestro"
DRIVER_PORT = "7001"  # Maestro's fixed host<->device gRPC port


def driver_running():
    return any(l.split()[-1] == DRIVER for l in adb("shell", "ps", "-A").splitlines() if l.strip())


def restart_driver():
    # The Maestro MCP keeps its gRPC channel open and does not respawn a killed driver: every `run`
    # after a force-stop fails with "Device server died ... UNAVAILABLE". So whoever stops the driver
    # starts it again, the way `maestro` itself does: forward the port, then run the driver instrumentation.
    adb("forward", f"tcp:{DRIVER_PORT}", f"tcp:{DRIVER_PORT}")
    if driver_running():
        return
    subprocess.Popen(
        [ADB, "shell", "am", "instrument", "-w", "-e", "debug", "false", "-e", "class",
         f"{DRIVER}.MaestroDriverService#grpcServer", f"{DRIVER}.test/androidx.test.runner.AndroidJUnitRunner"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(20):
        time.sleep(0.5)
        if driver_running():
            time.sleep(1)  # the process is up a moment before its gRPC server accepts
            return
    sys.exit("device.py: the Maestro driver did not come back; Maestro `run` will fail with UNAVAILABLE")


def dump():
    # Maestro's on-device driver holds the UiAutomation connection, and `uiautomator dump` dies
    # (exit 137) while it does. So stop it for the dump and always bring it back, even if the dump fails.
    adb("shell", "am", "force-stop", DRIVER)
    adb("shell", "am", "force-stop", f"{DRIVER}.test")
    try:
        adb("shell", "uiautomator", "dump", "/sdcard/test-runner.xml")
        return ET.fromstring(adb("exec-out", "cat", "/sdcard/test-runner.xml"))
    finally:
        restart_driver()


def short_id(node):
    # XML views publish "pkg:id/name"; Compose test tags publish the bare name.
    rid = node.get("resource-id", "")
    return rid.split(":id/")[-1] if rid else ""


def bounds(node):
    l, t, r, b = map(int, node.get("bounds").replace("][", ",").strip("[]").split(","))
    return l, t, r, b


def texts(node):
    # Compose puts a row's label on a child node, not on the node carrying the id.
    return [n.get("text") or n.get("content-desc") for n in node.iter() if n.get("text") or n.get("content-desc")]


def find(root, rid):
    if rid == "root":  # the whole window, for insets measured from the screen edge
        return root.find("node"), 1
    hits = [n for n in root.iter("node") if short_id(n) == rid]
    return (hits[0], len(hits)) if hits else (None, 0)


def screencap():
    # Raw RGBA, not PNG: a fixed header then w*h*4 bytes, so a pixel is an offset, no decoding.
    raw = adb("exec-out", "screencap", binary=True)
    w, h = struct.unpack_from("<II", raw)
    header = len(raw) - w * h * 4
    return w, raw[header:]


def pixel(cap, x, y):
    w, px = cap
    i = (y * w + x) * 4
    return "#%02X%02X%02X" % tuple(px[i:i + 3])


def cmd_nodes(substr=""):
    # Keeps only what a selector or an assertion can use: the id, the visible text, the bounds in
    # dp, and the state flags that differ from the default. Layout-only containers are dropped.
    root, dpi = dump(), density()
    d = lambda v: round(v * 160 / dpi)
    for n in root.iter("node"):
        rid, txt, desc = short_id(n), n.get("text", ""), n.get("content-desc", "")
        flags = [f for f in ("clickable", "scrollable", "checked", "selected", "focused") if n.get(f) == "true"]
        if n.get("enabled") == "false":
            flags.append("disabled")
        if not (rid or txt or desc or flags) or (substr and substr not in rid + txt + desc):
            continue
        l, t, r, b = bounds(n)
        label = " ".join(x for x in (txt, f"[{desc}]" if desc and desc != txt else "") if x)
        print(f"{rid or '-'} | {label[:60]} | {d(l)},{d(t)} {d(r - l)}x{d(b - t)} | {','.join(flags)}")


def cmd_check(spec_path):
    root, dpi, cap = dump(), density(), screencap()
    dp = lambda px: px * 160 / dpi
    # Layout snaps every edge to whole pixels, so one physical pixel is the error a correct build
    # can still show against a Figma value.
    tol = 160 / dpi
    fails = 0
    print(f"density {dpi}dpi, tolerance {tol:.2f}dp")
    for line in open(spec_path):
        if not line.strip() or line.startswith("#"):
            continue
        rid, prop, expected, *_ = line.rstrip("\n").split("\t")
        node, count = find(root, rid)
        if node is None:
            print(f"✗ {rid:28} {prop:18} no node on screen"); fails += 1; continue
        l, t, r, b = bounds(node)
        got, ok = None, False
        if prop in ("w", "h"):
            got = dp(r - l if prop == "w" else b - t)
            ok = abs(got - float(expected)) <= tol
        elif prop.startswith(("gap_below:", "gap_right:", "inset_left:", "inset_top:")):
            kind, other_id = prop.split(":", 1)
            other, _ = find(root, other_id)
            if other is None:
                print(f"✗ {rid:28} {prop:18} no node '{other_id}'"); fails += 1; continue
            ol, ot, orr, ob = bounds(other)
            got = dp({"gap_below": ot - b, "gap_right": ol - r, "inset_left": l - ol, "inset_top": t - ot}[kind])
            ok = abs(got - float(expected)) <= tol
        elif prop.startswith("fill"):
            fx, fy = map(float, prop.split("@")[1].split(",")) if "@" in prop else (0.5, 0.5)
            got = pixel(cap, int(l + (r - l) * fx), int(t + (b - t) * fy))
            ok = got.upper() == expected.upper()
        elif prop == "text":
            got = " / ".join(texts(node))
            ok = expected in texts(node)
        else:
            print(f"? {rid:28} {prop:18} unknown prop"); fails += 1; continue
        shown = f"{got:.1f}" if isinstance(got, float) else got
        note = f"  ({count} matches, first used)" if count > 1 else ""
        print(f"{'✓' if ok else '✗'} {rid:28} {prop:18} figma {expected:10} device {shown}{note}")
        fails += not ok
    sys.exit(1 if fails else 0)


def cmd_crop(rid, out):
    root, cap = dump(), screencap()
    node, _ = find(root, rid)
    if node is None:
        sys.exit(f"no node '{rid}'")
    l, t, r, b = bounds(node)
    w, px = cap
    rows = b"".join(b"\0" + px[(y * w + l) * 4:(y * w + r) * 4] for y in range(t, b))
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", r - l, b - t, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    open(out, "wb").write(png)
    print(f"{out}  {r - l}×{b - t}px")


if __name__ == "__main__":
    cmds = {"nodes": cmd_nodes, "check": cmd_check, "crop": cmd_crop}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]](*sys.argv[2:])
