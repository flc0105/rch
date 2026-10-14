SCRIPT_METADATA = {
    "display_name": "Workspace Test",
    "params": [],
    "api_grants": [
        "workspace:read"
    ]
}

from client.runtime.sdk import workspace

print("=== Script SDK Workspace Test ===")

items = workspace.list()
paths = workspace.as_dict()

print("\n=== pinned paths ===")
print("workspace.list() =", items)
print("workspace.as_dict() =", paths)

print("\n=== pinned path lookup ===")
print("workspace.path('pics') =", workspace.path('pics'))

print("\n=== system paths ===")
print("workspace.system_paths() =", workspace.system_paths())

print("\n=== system path shortcuts ===")
print("workspace.root() =", workspace.root())
print("workspace.home() =", workspace.home())
print("workspace.desktop() =", workspace.desktop())
print("workspace.documents() =", workspace.documents())
print("workspace.downloads() =", workspace.downloads())
print("workspace.temp() =", workspace.temp())
print("workspace.executable() =", workspace.executable())
print("workspace.icloud() =", workspace.icloud())

print("\nPASS")