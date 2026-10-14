SCRIPT_METADATA = {
    "name": "test_remote_file_picker_file",
    "display_name": "Test Remote File Picker - File",
    "description": "测试 RemoteFilePicker 单文件选择，运行后直接打印选中的文件路径。",
    "category": "Test",
    "tags": ["test", "remote-file-picker", "file"],
    "platforms": ["*"],
    "params": [
        {
            "name": "target_file",
            "type": "remote_file",
            "description": "选择一个远程文件。",
            "required": True,
            "initial_path": "/"
        }
    ]
}


def main():
    print(kwargs.get("target_file", ""))


if __name__ == "__main__":
    main()
