import ast

SCRIPT_METADATA = {
    "name": "test_remote_file_picker_files",
    "display_name": "Test Remote File Picker - Multiple Files",
    "description": "测试 RemoteFilePicker 多文件选择，运行后逐行打印选中的文件路径。",
    "category": "Test",
    "tags": ["test", "remote-file-picker", "files"],
    "platforms": ["*"],
    "params": [
        {
            "name": "target_files",
            "type": "remote_files",
            "description": "选择一个或多个远程文件。",
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
    print(kwargs.get("target_files"))
    for path in normalize_paths(kwargs.get("target_files", [])):
        print(path)


if __name__ == "__main__":
    main()
