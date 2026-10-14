SCRIPT_METADATA = {
    "display_name": "Context Test",
    "params": [],
    "api_grants": []
}

from client.runtime.sdk import context

print("=== Script SDK Context Test ===")

ctx = globals().get('kwargs', {}).get('__context__', {})
#ctx = kwargs.get('__context__', {})

print("\n=== raw __context__ ===")
print("__context__.client_id =", ctx.get('client_id'))
print("__context__.command_id =", ctx.get('command_id'))
print("__context__ =", ctx)

print("\n=== context sdk ===")
print("context.client_id() =", context.client_id())
print("context.command_id() =", context.command_id())
print("context.hostname() =", context.hostname())
print("context.machine_id() =", context.machine_id())
print("context.script_name() =", context.script_name())
print("context.arch() =", context.arch())
print("context.os_type() =", context.os_type())
print("context.os_alias() =", context.os_alias())
print("context.os_ver() =", context.os_ver())

print("\nPASS")