SCRIPT_METADATA = {
    "name": "test_remote_file_picker_folder",
    "display_name": "Test Remote File Picker - Folder",
    "description": "测试 RemoteFilePicker 单目录选择，运行后直接打印选中的目录路径。",
    "category": "Test",
    "tags": ["test", "remote-file-picker", "folder"],
    "platforms": ["*"],
    "params": [
        {
            "name": "target_folder",
            "type": "remote_folder",
            "description": "选择一个远程目录。",
            "required": True,
            "initial_path": "/"
        }
    ]
}


def main():
    print(kwargs.get("target_folder", ""))


if __name__ == "__main__":
    main()
