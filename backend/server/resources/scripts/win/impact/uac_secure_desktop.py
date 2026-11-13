import sys
import winreg


SCRIPT_METADATA = {
    "display_name": "UAC Secure Desktop",
    "description": "Show, enable, or disable Windows PromptOnSecureDesktop for UAC elevation prompts.",
    "category": "Windows",
    "tags": ["windows", "uac", "admin"],
    "platforms": ["win"],
    "params": [
        {
            "name": "action",
            "type": "select",
            "required": True,
            "default": "status",
            "control": "button_group",
            "options": ["status", "disable", "enable"],
            "description": (
                "status = show current value; "
                "disable = UAC prompts stay on the interactive desktop; "
                "enable = restore secure desktop prompts."
            ),
        },
    ],
}


REGISTRY_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
VALUE_NAME = "PromptOnSecureDesktop"


def _registry_access(mask):
    # 始终操作系统策略所在的 64-bit registry view。
    return mask | getattr(winreg, "KEY_WOW64_64KEY", 0)


def _read_value():
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            REGISTRY_PATH,
            0,
            _registry_access(winreg.KEY_READ),
        ) as key:
            value, value_type = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None

    if value_type != winreg.REG_DWORD:
        raise RuntimeError(
            f"Unexpected registry type for {VALUE_NAME}: "
            f"{value_type}; expected REG_DWORD"
        )

    return int(value)


def _format_state(value):
    if value is None:
        return "not set (Windows default: enabled)"

    if value == 0:
        return "disabled (UAC prompts use the interactive desktop)"

    if value == 1:
        return "enabled (UAC prompts use the secure desktop)"

    return f"unexpected value: {value}"


def _write_value(value):
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            REGISTRY_PATH,
            0,
            _registry_access(winreg.KEY_SET_VALUE),
        ) as key:
            winreg.SetValueEx(
                key,
                VALUE_NAME,
                0,
                winreg.REG_DWORD,
                int(value),
            )
    except PermissionError as exc:
        raise RuntimeError(
            "Administrator privileges are required to change "
            "PromptOnSecureDesktop. Run rchclient as administrator "
            "and try again."
        ) from exc


def main():
    if sys.platform != "win32":
        raise RuntimeError("This script only supports Windows")

    action = str(
        kwargs.get("action", "status") or "status"
    ).strip().lower()

    if action not in {"status", "disable", "enable"}:
        raise RuntimeError(f"Unsupported action: {action}")

    before = _read_value()

    print(
        f"Registry: "
        f"HKLM\\{REGISTRY_PATH}\\{VALUE_NAME}"
    )
    print(f"Current: {_format_state(before)}")

    if action == "status":
        return

    target_value = 0 if action == "disable" else 1

    if before == target_value:
        print(f"No change: already {_format_state(before)}")
        return

    _write_value(target_value)

    after = _read_value()

    if after != target_value:
        raise RuntimeError(
            f"Registry write verification failed: "
            f"expected {target_value}, got {after}"
        )

    print(f"Updated: {_format_state(after)}")

    if target_value == 0:
        print(
            "WARNING: UAC elevation prompts are no longer isolated "
            "on the secure desktop."
        )
    else:
        print("Secure desktop prompting restored.")


main()