"""Pilote de recette : Microsoft Edge sans fenêtre, commandé par le protocole DevTools.

Vrais événements souris et clavier, tailles d'écran réelles, captures pleine
taille. Profil Edge temporaire : le profil de l'utilisateur n'est jamais touché.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

EDGE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"

VK = {"Enter": 13, "Escape": 27, "Tab": 9, "Backspace": 8, "Delete": 46, "ArrowLeft": 37, "ArrowRight": 39,
      "ArrowUp": 38, "ArrowDown": 40, "Home": 36, "End": 35, "PageDown": 34, "PageUp": 33}


class Edge:
    def __init__(self, width: int = 1280, height: int = 720, port: int = 9333):
        self.profile = tempfile.mkdtemp(prefix="destripdf-edge-")
        self.port = port
        self.proc = subprocess.Popen([
            str(EDGE), "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
            "--hide-scrollbars=false", f"--window-size={width},{height}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        targets = []
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json") as resp:
                    targets = [t for t in json.load(resp) if t.get("type") == "page"]
                if targets:
                    break
            except OSError:
                time.sleep(0.2)
        if not targets:
            raise RuntimeError("Edge ne répond pas")
        self.ws = websocket.create_connection(targets[0]["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
        self._id = 0
        self.console: list[str] = []
        self.call("Runtime.enable")
        self.call("Page.enable")
        self.call("Log.enable")
        self.viewport(width, height)

    # -- protocole --

    def call(self, method: str, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._event(msg)

    def _event(self, msg):
        method = msg.get("method")
        if method == "Runtime.consoleAPICalled":
            args = msg["params"].get("args", [])
            text = " ".join(str(a.get("value", a.get("description", ""))) for a in args)
            self.console.append(f"{msg['params'].get('type')}: {text}")
        elif method == "Runtime.exceptionThrown":
            details = msg["params"]["exceptionDetails"]
            self.console.append(f"EXCEPTION: {details.get('exception', {}).get('description') or details.get('text')}")
        elif method == "Log.entryAdded":
            entry = msg["params"]["entry"]
            if entry.get("level") in ("error", "warning"):
                self.console.append(f"{entry['level']}: {entry.get('text')} {entry.get('url', '')}")

    def pump(self, seconds: float = 0.2):
        """Laisse passer les événements (console, exceptions) pendant un court instant."""
        end = time.time() + seconds
        self.ws.settimeout(0.05)
        try:
            while time.time() < end:
                try:
                    self._event(json.loads(self.ws.recv()))
                except websocket.WebSocketTimeoutException:
                    pass
        finally:
            self.ws.settimeout(60)

    # -- page --

    def viewport(self, width: int, height: int):
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)

    def goto(self, url: str, wait: float = 1.5):
        self.call("Page.navigate", url=url)
        self.wait_for("document.readyState === 'complete'")
        time.sleep(wait)

    def js(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description") or result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, timeout: float = 10.0, interval: float = 0.1):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.js(f"Boolean({expression})"):
                    return True
            except RuntimeError:
                pass
            time.sleep(interval)
        raise TimeoutError(expression)

    def center(self, selector: str):
        box = self.js(f"""(() => {{ const n = document.querySelector({json.dumps(selector)}); if (!n) return null;
            const r = n.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")
        if not box:
            raise LookupError(selector)
        return box

    def shot(self, path: str | Path):
        data = self.call("Page.captureScreenshot", format="png")["data"]
        Path(path).write_bytes(base64.b64decode(data))
        return path

    # -- entrées --

    def mouse(self, kind: str, x: float, y: float, buttons: int = 0, click_count: int = 0, modifiers: int = 0):
        params = {"type": kind, "x": x, "y": y, "modifiers": modifiers}
        if kind in ("mousePressed", "mouseReleased"):
            params.update(button="left", clickCount=click_count or 1)
        if buttons:
            params["buttons"] = buttons
            if kind == "mouseMoved":
                params["button"] = "left"  # glisser : la sélection de texte de Chrome l'exige
        self.call("Input.dispatchMouseEvent", **params)

    def click(self, x: float, y: float, count: int = 1):
        self.mouse("mouseMoved", x, y)
        for i in range(1, count + 1):
            self.mouse("mousePressed", x, y, buttons=1, click_count=i)
            self.mouse("mouseReleased", x, y, click_count=i)

    def click_on(self, selector: str, count: int = 1):
        x, y = self.center(selector)
        self.click(x, y, count)
        return x, y

    def drag(self, points: list[tuple[float, float]], steps: int = 6):
        x0, y0 = points[0]
        self.mouse("mouseMoved", x0, y0)
        self.mouse("mousePressed", x0, y0, buttons=1, click_count=1)
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            for k in range(1, steps + 1):
                t = k / steps
                self.mouse("mouseMoved", ax + (bx - ax) * t, ay + (by - ay) * t, buttons=1)
        xn, yn = points[-1]
        self.mouse("mouseReleased", xn, yn, click_count=1)

    def type(self, text: str):
        self.call("Input.insertText", text=text)

    def key(self, key: str, modifiers: int = 0, text: str | None = None):
        code = VK.get(key, ord(key.upper()) if len(key) == 1 else 0)
        params = {"key": key, "windowsVirtualKeyCode": code, "modifiers": modifiers}
        down = dict(params, type="keyDown" if text is None else "keyDown")
        if text is not None:
            down["text"] = text
        self.call("Input.dispatchKeyEvent", **down)
        self.call("Input.dispatchKeyEvent", **dict(params, type="keyUp"))

    def close(self):
        try:
            self.call("Browser.close")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


CTRL = 2
SHIFT = 8
