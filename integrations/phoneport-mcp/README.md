# Control a nearby iPhone from local Codex

This local MCP server gives Codex tools to check AirWindows, see the mirrored phone, tap, swipe, type, and go Home. It calls the existing `iosctl.exe` shipped with AirWindows RC5 or PhonePort. Python 3.10 or later is the only additional runtime dependency. The server communicates over standard input and output and opens no network listener.

Added on 2026-11-15 in this fork under GPL-3.0-or-later. See the repository's [license notices](../../LICENSE.md).

## Pair the phone first

1. On Windows, launch `Start-AirWindows.cmd` from the extracted RC5 package so it enables frame access. For a PhonePort installation, open its Start menu entry.
2. On the iPhone, open Control Center, tap **Screen Mirroring**, and choose your PC. Turn on **Settings → Accessibility → Touch → AssistiveTouch**.
3. In AirWindows, click **Pair Bluetooth**, pair from the iPhone's main **Settings → Bluetooth** page, then click the AirWindows phone button and select the iPhone. The green dot means the mirrored phone has a selected Bluetooth connection. With the phone unlocked, click a visible Calculator key inside the mirrored image to verify that the phone actually receives input. If the window's Home button fails, [assign AssistiveTouch Button 2 to Home](../../app/NATIVE-CONTROL.md#home-and-scrolling).

## Install the PhonePort desktop plugin

In PowerShell on the Windows laptop, run `py -3 .\install.py` from this directory. The installer copies the plugin to your local ChatGPT marketplace and preserves the existing marketplace entries. Restart ChatGPT, find **PhonePort** under your local source in **Plugins**, then click **Install**. Start a new local Codex session to use it. When AirWindows is open, the plugin finds the helper next to the running receiver. If needed, set the path explicitly with `py -3 .\install.py --iosctl 'C:\path\to\iosctl.exe'`.

## Register only the MCP server

Save `server.py` locally. In the same interactive Windows login that opened AirWindows, run the following in PowerShell, replacing both paths. Set `$python` to the full path to an installed `python.exe` if the command cannot resolve it.

```powershell
$python = (Get-Command python.exe).Source
$bridge = 'C:\path\to\server.py'
$iosctl = 'C:\path\to\AirWindows\iosctl.exe'
& $iosctl --doctor
codex mcp add phoneport -- $python $bridge --iosctl $iosctl
codex mcp list
```

With a local Codex client that reads a `config.toml` file, the equivalent configuration is below. Change the paths, then start a new local Codex session to load the tools.

```toml
[mcp_servers.phoneport]
command = 'C:\path\to\python.exe'
args = ['C:\path\to\server.py', '--iosctl', 'C:\path\to\AirWindows\iosctl.exe']
```

Ask the new session, “Use PhonePort to open Calculator on my iPhone and tap 2 + 2 =. Verify the result on the phone.” The local session must have the `phoneport` MCP tools in its tool list. Screenshots returned by `phone_look` become part of the session's tool context. The server uses temporary local capture files and removes them after each call.

## If the test fails

| What you see | What to check |
| --- | --- |
| `--doctor` cannot find a receiver even though you see the window | Run `--doctor` directly in PowerShell on your desktop. If that works, the original agent session lacks access to the interactive Windows receiver. Use local Codex in the same Windows login. The tools cannot be added retroactively to a running chat. |
| Receiver found, but frame access is unavailable | Use `Start-AirWindows.cmd` for RC5, or start the receiver with `--frames`. |
| Mirror visible, but a mouse click inside it does nothing | Check that AssistiveTouch is on, the phone is awake, and the correct iPhone is selected in the toolbar. If the pointer does not move, disconnect AirWindows' Bluetooth connection, remove its Bluetooth pairing, and pair it again using the AirWindows phone button. |
| The picture is static | `phone_look` can show a retained image and its age. For an input request the server uses `iosctl wake` when necessary, and `iosctl` requires a fresh frame before it sends the requested action. If that fails, touch the phone to refresh the screen and observe again. |

The bridge checks the receiver instance, selected phone, and screen geometry before input. Each input call uses one observation and requires a new observation before the next action. `iosctl` reports input submission. The visible result on the iPhone is the test of whether an action worked. Use the bridge only in a session with local desktop access to that Windows user. The AirPlay and Bluetooth connection still requires the iPhone to be near the receiver.
