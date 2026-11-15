# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage the PhonePort plugin in the current user's local ChatGPT marketplace."""

import argparse
import json
from pathlib import Path
import sys
import tempfile


def write_file(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(contents)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def encode_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def install(home, python, helper):
    source = Path(__file__).resolve().parent
    target = home / ".codex/plugins/airwindows-phoneport"
    marketplace_path = home / ".agents/plugins/marketplace.json"
    marketplace = {"name": "local-plugins", "interface": {"displayName": "Local Plugins"}, "plugins": []}
    if marketplace_path.is_file():
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8-sig"))
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or not isinstance(marketplace.get("name"), str):
        raise ValueError("The existing marketplace does not have the expected format.")

    entry = {"name": "phoneport", "source": {"source": "local", "path": "./.codex/plugins/airwindows-phoneport"},
             "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}
    matches = [item for item in plugins if item.get("name") == "phoneport"]
    if len(matches) > 1 or (matches and matches[0].get("source") != entry["source"]):
        raise ValueError("The marketplace already has another plugin named phoneport.")
    if not matches:
        plugins.append(entry)

    config = json.loads((source / "mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["phoneport"]
    server.update(command=str(python), args=["${PLUGIN_ROOT}/server.py"])
    if helper:
        server["args"].extend(("--iosctl", str(helper)))

    for name in ("server.py", ".codex-plugin/plugin.json"):
        write_file(target / name, (source / name).read_bytes())
    write_file(target / "mcp.json", encode_json(config))
    if not matches:
        write_file(marketplace_path, encode_json(marketplace))
    return marketplace.get("interface", {}).get("displayName", marketplace["name"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iosctl", type=Path, help="Optional full path to iosctl.exe")
    args = parser.parse_args()
    helper = args.iosctl.resolve() if args.iosctl else None
    if helper and (helper.name.lower() != "iosctl.exe" or not helper.is_file()):
        parser.error("--iosctl must point to an existing iosctl.exe.")
    try:
        marketplace = install(Path.home(), Path(sys.executable), helper)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Could not prepare PhonePort: {exc}\n")
    print(f"Restart ChatGPT, open Plugins, choose {marketplace}, and install PhonePort.")


if __name__ == "__main__":
    main()
