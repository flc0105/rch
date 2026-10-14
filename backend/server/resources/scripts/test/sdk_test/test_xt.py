SCRIPT_METADATA = {
    "display_name": "External Tool Test",
    "params": [],
    "api_grants": [
        "external_tools:catalog",
    ]
}

from client.runtime.sdk import xt

print("=== External Tool SDK Test ===")

ffmpeg = xt.tool('ffmpeg')

print("tool_name =", "ffmpeg")
print("ffmpeg.is_installed =", ffmpeg.is_installed)

print("\n=== xt.tool('ffmpeg')('-version') ===")
result = ffmpeg('-version')
print("returncode =", result.returncode)
print("stdout =")
print(result.stdout or "<empty>")
print("stderr =")
print(result.stderr or "<empty>")

print("\n=== xt.ffmpeg('-version') ===")
result = xt.ffmpeg('-version')
print("xt.ffmpeg.is_installed =", xt.ffmpeg.is_installed)
print("returncode =", result.returncode)
print("stdout =")
print(result.stdout or "<empty>")
print("stderr =")
print(result.stderr or "<empty>")

print("\nPASS")