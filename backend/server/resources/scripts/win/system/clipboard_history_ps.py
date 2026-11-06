SCRIPT_METADATA = {
    "name": "win/recon/clipboard_history_ps",
    "display_name": "Clipboard History (PowerShell)",
    "description": "Read Windows clipboard history via WinRT Clipboard.GetHistoryItemsAsync, executed in Windows PowerShell 5.1.",
    "platforms": ["win"],
    "category": "Recon",
    "params": []
}

import base64
import json
import subprocess
import sys

if sys.platform != "win32":
    raise RuntimeError("Windows only")


POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'

function Write-B64Json($obj) {
    $json = $obj | ConvertTo-Json -Compress -Depth 4
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    [Console]::Out.Write($b64)
}

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

    function Await($WinRtTask, $ResultType) {
        $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        $netTask.Wait(-1) | Out-Null
        $netTask.Result
    }

    $null = [Windows.ApplicationModel.DataTransfer.Clipboard, Windows.ApplicationModel.DataTransfer, ContentType=WindowsRuntime]

    $op = [Windows.ApplicationModel.DataTransfer.Clipboard]::GetHistoryItemsAsync()
    $result = Await ($op) ([Windows.ApplicationModel.DataTransfer.ClipboardHistoryItemsResult])

    if ($result.Status -ne 0) {
        $statusName = switch ($result.Status) {
            1 { 'AccessDenied' }
            2 { 'ClipboardHistoryDisabled' }
            default { "Unknown($($result.Status))" }
        }
        Write-B64Json @{ error = "GetHistoryItemsAsync failed: $statusName" }
        return
    }

    $items = @()
    foreach ($item in $result.Items) {
        try {
            $textOp = $item.Content.GetTextAsync()
            $text = Await ($textOp) ([String])
            $items += @{ type = 'text'; text = $text }
        } catch {
            $items += @{ type = 'unknown'; error = $_.Exception.Message }
        }
    }

    Write-B64Json @{ count = $items.Count; items = $items }
}
catch {
    Write-B64Json @{ error = $_.Exception.Message }
}
"""


def _run_powershell(script):
    # -EncodedCommand 要求 UTF-16LE + Base64，避免 cmdline 转义/中文路径问题
    encoded_script = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
        capture_output=True,
        timeout=30,
        shell=False,
        # stdout 是 Base64（ASCII 子集），UTF-8 解码安全；
        # stderr 可能是 GBK 中文，errors="replace" 兜底不崩
        encoding="utf-8",
        errors="replace",
    )

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if not stdout:
        return {
            "error": "no output from powershell.exe",
            "stderr": stderr[:500] if stderr else None,
        }

    try:
        decoded = base64.b64decode(stdout).decode("utf-8")
        result = json.loads(decoded)

        # PowerShell 5.1 ConvertTo-Json 对单元素数组会退化为对象，这里兜底
        items = result.get("items")
        if items is None:
            items = []
        elif isinstance(items, dict):
            items = [items]
        if "items" in result:
            result["items"] = items
            result["count"] = len(items)

        return result
    except Exception as e:
        return {
            "error": f"failed to decode/parse output: {type(e).__name__}: {e}",
            "raw_stdout": stdout[:300],
            "stderr": stderr[:500] if stderr else None,
        }


def main():
    try:
        result = _run_powershell(POWERSHELL_SCRIPT)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "powershell.exe timed out after 30s"}, ensure_ascii=False))
    except FileNotFoundError:
        print(json.dumps({"error": "powershell.exe not found"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()