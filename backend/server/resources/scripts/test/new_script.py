import json

from client.runtime.sdk import context


SCRIPT_METADATA = {
    "name": "parameter_schema_smoke_script",
    "display_name": "Parameter Schema Smoke Script",
    "description": "Read-only smoke test for the unified Script/Job/External Tool parameter schema.",
    "category": "test",
    "tags": ["test", "schema", "smoke"],
    "platforms": ["*"],
    "params": [
        {
            "name": "required_text",
            "label": "Required Text",
            "type": "string",
            "required": True,
            "description": "Required string; verifies required + label + description.",
        },
        {
            "name": "notes",
            "label": "Notes / Textarea",
            "type": "textarea",
            "default": "line 1\nline 2",
            "rows": 4,
            "description": "Multiline text; verifies textarea rendering and defaults.",
        },
        {
            "name": "count",
            "label": "Count (1-5)",
            "type": "integer",
            "required": True,
            "min": 1,
            "max": 5,
            "description": "Required integer with min/max validation.",
        },
        {
            "name": "ratio",
            "type": "number",
            "default": 1.25,
            "min": 0.1,
            "max": 10.0,
            "description": "Number field; label intentionally omitted to test label=name fallback.",
        },
        {
            "name": "enabled",
            "type": "boolean",
            "default": True,
            "description": "Boolean switch; label intentionally omitted.",
        },
        {
            "name": "mode",
            "label": "Mode",
            "type": "select",
            "default": "safe",
            "options": ["fast", "safe", "debug"],
            "description": "Select field; invalid values should be rejected before execution.",
        },
        {
            "name": "remote_file",
            "label": "Remote File",
            "type": "remote_file",
            "description": "Optional single remote file path.",
        },
        {
            "name": "remote_files",
            "label": "Remote Files",
            "type": "remote_files",
            "description": "Optional multiple remote files; canonical value must be a JSON array/list.",
        },
        {
            "name": "remote_folder",
            "label": "Remote Folder",
            "type": "remote_folder",
            "description": "Optional single remote folder path.",
        },
        {
            "name": "remote_folders",
            "label": "Remote Folders",
            "type": "remote_folders",
            "description": "Optional multiple remote folders; canonical value must be a JSON array/list.",
        },
        {
            "name": "optional_text",
            "label": "Optional Text",
            "type": "string",
            "description": "No default; verifies an omitted optional field stays omitted.",
        },
    ],
}


PARAM_NAMES = [
    "required_text",
    "notes",
    "count",
    "ratio",
    "enabled",
    "mode",
    "remote_file",
    "remote_files",
    "remote_folder",
    "remote_folders",
    "optional_text",
]


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _describe(name):
    present = name in kwargs
    value = kwargs.get(name)
    return {
        "name": name,
        "present": present,
        "python_type": type(value).__name__ if present else "<missing>",
        "value": value if present else None,
    }


print("=== Parameter Schema Smoke Script ===")
print(
    "context:",
    _json({
        "client_id": context.client_id(),
        "hostname": context.hostname(),
        "os_alias": context.os_alias(),
        "arch": context.arch(),
        "script_name": context.script_name(),
    }),
)

for param_name in PARAM_NAMES:
    print(_json(_describe(param_name)))

print("all_params:", _json({name: kwargs[name] for name in PARAM_NAMES if name in kwargs}))
print("=== Script smoke test completed ===")
