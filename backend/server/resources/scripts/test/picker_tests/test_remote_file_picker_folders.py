import ast

SCRIPT_METADATA = {
    "name": "test_remote_file_picker_folders",
    "display_name": "Test Remote File Picker - Multiple Folders",
    "description": "测试 RemoteFilePicker 多目录选择，运行后逐行打印选中的目录路径。",
    "category": "Test",
    "tags": ["test", "remote-file-picker", "folders"],
    "platforms": ["*"],
    "params": [
        {
            "name": "target_folders",
            "type": "remote_folders",
            "description": "选择一个或多个远程目录。",
            "required": True,
            "multiple": True,
            "initial_path": "/"
        }
    ]
}


def normalize_paths(value):
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            parsed = None
        if isinstance(parsed, (list, tuple, set)):
            return [str(item) for item in parsed if str(item).strip()]
        return [text]

    return []


def main():
    for path in normalize_paths(kwargs.get("target_folders", [])):
        print(path)


if __name__ == "__main__":
    main()
