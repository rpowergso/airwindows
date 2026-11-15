# SPDX-License-Identifier: GPL-3.0-or-later
"""Local stdio MCP tools for the Windows AirWindows/PhonePort receiver."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


def tool(name, description, properties=None, required=(), read_only=True):
    return {
        "name": name, "description": description,
        "inputSchema": {"type": "object", "properties": properties or {},
                        "required": list(required), "additionalProperties": False},
        "annotations": {"readOnlyHint": read_only, "openWorldHint": False},
    }


COORDINATE = {"type": "integer", "minimum": 0, "maximum": 4095}
TOKEN = {"type": "integer", "minimum": 1}
TOOLS = [
    tool("phone_status", "Check local receiver, AirPlay video and Bluetooth input readiness."),
    tool("phone_look", "Observe the mirrored iPhone and return its native-size image and observation number. Read the image before choosing an action."),
    tool("phone_tap", "Tap one visible point on the last observed iPhone. Observe again to verify.",
         {"observation": TOKEN, "x": COORDINATE, "y": COORDINATE}, ("observation", "x", "y"), False),
    tool("phone_swipe", "Swipe between two visible points. Observe again to verify.",
         {"observation": TOKEN, **dict.fromkeys(("x1", "y1", "x2", "y2"), COORDINATE)},
         ("observation", "x1", "y1", "x2", "y2"), False),
    tool("phone_type", "Type into a visibly focused field. Observe again to verify.",
         {"observation": TOKEN, "text": {"type": "string", "minLength": 1, "maxLength": 1024}},
         ("observation", "text"), False),
    tool("phone_home", "Press Home if AssistiveTouch Button 2 is mapped to Home. Observe again to verify.",
         {"observation": TOKEN}, ("observation",), False),
]
SCHEMAS = {item["name"]: item["inputSchema"] for item in TOOLS}
BINDING_FIELDS = ("receiver_pid", "instance", "generation", "width", "height",
                  "control_epoch", "control_peer", "control_sender")
VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}


class BridgeError(Exception):
    pass


def text_result(value):
    return {"type": "text", "text": value if isinstance(value, str) else json.dumps(value)}


def quote(value):
    # iosctl escapes a quote with a backslash. Keep terminal backslashes
    # outside the quoted segment so they cannot escape the closing delimiter.
    body = value.rstrip("\\")
    return '"' + body.replace('"', '\\"') + '"' + value[len(body):]


def check_args(name, args):
    schema = SCHEMAS.get(name)
    if schema is None:
        raise BridgeError("Unknown phone tool.")
    if not isinstance(args, dict) or set(args) != set(schema["required"]):
        raise BridgeError("Pass exactly the arguments listed for this tool.")
    for key, value in args.items():
        if key == "text":
            if not isinstance(value, str) or not re.fullmatch(r"[\x20-\x7e\t\n]{1,1024}", value):
                raise BridgeError("Typing supports up to 1,024 ASCII characters, tabs and newlines.")
        elif type(value) is not int or value < (1 if key == "observation" else 0):
            raise BridgeError(f"Invalid integer for {key}.")


class Phone:
    def __init__(self, executable):
        self.executable = executable
        self.observation = None
        self.next_id = 0

    def find_iosctl(self):
        if self.executable:
            return str(self.executable)
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        probe = "$p = Get-Process -Name PhonePort,AirWindowsNative,AirWindows -ErrorAction SilentlyContinue; $p | ForEach-Object { $_.Path }"
        try:
            result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", probe],
                                    capture_output=True, text=True, timeout=5,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BridgeError("Could not inspect running receivers. Pass --iosctl to configure the helper directly.") from exc
        for path in result.stdout.splitlines():
            helper = Path(path.strip()).with_name("iosctl.exe") if path.strip() else None
            if helper and helper.is_file():
                self.executable = helper
                return str(helper)
        raise BridgeError("Start AirWindows or PhonePort in the same Windows login, or configure --iosctl with its full path.")

    def run(self, *args):
        try:
            result = subprocess.run([self.find_iosctl(), *args], capture_output=True,
                                    text=True, encoding="utf-8-sig", errors="replace", timeout=15,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise BridgeError("iosctl timed out. The action outcome may be unknown. Observe before retrying.") from exc
        except OSError as exc:
            raise BridgeError("Could not start iosctl in this Windows session.") from exc
        try:
            messages = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        except ValueError as exc:
            raise BridgeError("iosctl returned unexpected output. Check its version with --doctor.") from exc
        return result.returncode, messages

    def doctor(self):
        _, messages = self.run("--doctor")
        if not messages:
            raise BridgeError("iosctl did not report a receiver status.")
        status = messages[-1]
        if not isinstance(status, dict):
            raise BridgeError("iosctl returned an invalid receiver status.")
        if status.get("code") == "receiver_selection" and not status.get("receivers"):
            status["host_check"] = ("If the mirror is visible on the desktop, run Codex as the same "
                                    "interactive Windows user that launched AirWindows. Start it with frame access.")
        return status

    def receiver(self):
        code, receivers = self.run("--list")
        if code or len(receivers) != 1:
            raise BridgeError(json.dumps(self.doctor()))
        return receivers[0]["pid"]

    def capture(self, pid):
        with tempfile.TemporaryDirectory(prefix="phoneport-") as folder:
            path = Path(folder) / "screen.png"
            code, messages = self.run("--pid", str(pid), "snapshot " + quote(str(path)))
            if code or not path.is_file() or not path.with_suffix(".json").is_file():
                raise BridgeError(json.dumps(messages or self.doctor()))
            meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8-sig"))
            if meta.get("source") != "airplay" or meta.get("receiver_pid") != pid:
                raise BridgeError("No live AirPlay phone frame for the selected receiver.")
            return meta, path.read_bytes()

    def look(self):
        self.observation = None
        meta, png = self.capture(self.receiver())
        self.next_id += 1
        self.observation = self.next_id, time.monotonic(), meta
        summary = {key: meta.get(key) for key in ("width", "height", "frame_age_ms", "frame_fresh", "control_ready")}
        summary["observation"] = self.next_id
        return [text_result(summary), {"type": "image", "mimeType": "image/png",
                                       "data": base64.b64encode(png).decode("ascii")}]

    def act(self, name, args):
        prior, self.observation = self.observation, None
        if not prior or prior[0] != args["observation"] or time.monotonic() - prior[1] > 30:
            raise BridgeError("Call phone_look again to get a current observation.")
        observed = prior[2]
        pid = observed["receiver_pid"]
        if not observed.get("control_ready"):
            raise BridgeError("AirPlay picture is visible, but Bluetooth input is not ready. Choose the phone in AirWindows and enable AssistiveTouch.")
        current, _ = self.capture(pid)
        if any(key not in observed or key not in current or observed[key] != current[key] for key in BINDING_FIELDS):
            raise BridgeError("The receiver, phone binding or screen geometry changed. Observe again.")
        if not current.get("control_ready"):
            raise BridgeError("Bluetooth control was lost. Reconnect the phone before trying again.")

        def point(x_key, y_key):
            x, y = args[x_key], args[y_key]
            if not (x < min(current["width"], 4096) and y < min(current["height"], 4096)):
                raise BridgeError("Action coordinates are outside the native phone image.")
            return f"{x} {y}"

        if name == "phone_tap":
            action = "tap " + point("x", "y")
        elif name == "phone_swipe":
            action = "swipe " + point("x1", "y1") + " " + point("x2", "y2")
        elif name == "phone_type":
            action = "type " + quote(args["text"])
        else:
            action = "home"
        if not current.get("frame_fresh"):
            action = "wake; " + action
        code, messages = self.run("--pid", str(pid), action)
        return code, [text_result({"exit_code": code, "iosctl": messages,
                                  "next": "Call phone_look to verify the result before sending more input."})]


def dispatch(phone, request):
    method, params = request.get("method"), request.get("params", {})
    if method == "initialize":
        version = params.get("protocolVersion")
        return {"protocolVersion": version if version in VERSIONS else "2025-11-25",
                "capabilities": {"tools": {}}, "serverInfo": {"name": "phoneport", "version": "0.1.0"},
                "instructions": "Use phone_status for setup and phone_look before each user-authorized input. Inspect a new image after each action."}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method != "tools/call":
        raise LookupError("Method not found")
    try:
        name, args = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str):
            raise BridgeError("Provide a phone tool name.")
        check_args(name, args)
        if name == "phone_status":
            return {"content": [text_result(phone.doctor())]}
        if name == "phone_look":
            return {"content": phone.look()}
        code, content = phone.act(name, args)
        return {"isError": bool(code), "content": content}
    except (BridgeError, OSError, ValueError, KeyError) as exc:
        return {"isError": True, "content": [text_result(str(exc))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iosctl", default=os.environ.get("PHONEPORT_IOSCTL") or shutil.which("iosctl.exe"),
                        help="Path to the receiver's iosctl.exe")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run the PhonePort plugin in an interactive Windows session.")
    if args.iosctl and not Path(args.iosctl).is_file():
        parser.error("--iosctl must point to the installed iosctl.exe.")
    phone = Phone(Path(args.iosctl).resolve() if args.iosctl else None)
    for line in sys.stdin.buffer:
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise TypeError("Invalid JSON-RPC request")
            if "id" not in request:
                continue
            request_id = request["id"]
            reply = {"result": dispatch(phone, request)}
        except json.JSONDecodeError:
            reply = {"error": {"code": -32700, "message": "Parse error"}}
        except (TypeError, AttributeError):
            reply = {"error": {"code": -32600, "message": "Invalid request"}}
        except LookupError:
            reply = {"error": {"code": -32601, "message": "Method not found"}}
        print(json.dumps({"jsonrpc": "2.0", "id": request_id, **reply}), flush=True)


if __name__ == "__main__":
    main()
