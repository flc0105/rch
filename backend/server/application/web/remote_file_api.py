class WebRemoteFileApi:
    """
    Web 远程文件子外观。

    职责：
    - 提供 remote file 浏览/创建/重命名/删除
    - 提供 remote file 预览/下载/压缩下载
    - 提供 remote file 读取/保存

    说明：
    - 不负责 HTTP 参数解析
    - 不负责响应封装
    - 统一 remote file 相关 Web 应用动作
    """

    def __init__(self, remote_file_service):
        self.remote_file_service = remote_file_service

    def browse_remote_directory(
        self,
        client_id: str,
        path: str = '',
        page: int = 1,
        page_size: int = 100,
        show_hidden: bool = False,
        search_keyword: str = '',
        recursive_search: bool = False,
    ):
        return self.remote_file_service.browse_directory(
            client_id,
            path,
            page=page,
            page_size=page_size,
            show_hidden=show_hidden,
            search_keyword=search_keyword,
            recursive_search=recursive_search,
        )

    def create_remote_directory(self, client_id: str, path: str):
        return self.remote_file_service.create_directory(client_id, path)

    def rename_remote_path(self, client_id: str, old_path: str, new_name: str):
        return self.remote_file_service.rename_path(client_id, old_path, new_name)

    def delete_remote_path(self, client_id: str, path: str):
        return self.remote_file_service.delete_path(client_id, path)

    def delete_remote_paths(self, client_id: str, paths: list[str]):
        return self.remote_file_service.delete_paths(client_id, paths)


    def paste_remote_paths(self, client_id: str, paths: list[str], destination_dir: str, operation: str = 'copy'):
        return self.remote_file_service.paste_paths(client_id, paths, destination_dir, operation)

    def preview_remote_file(
        self,
        client_id: str,
        path: str,
        history_entry_id: str = '',
        tab_id: str = '',
    ):
        return self.remote_file_service.preview_file(
            client_id,
            path,
            history_entry_id=history_entry_id,
            tab_id=tab_id,
        )

    def download_remote_file(
        self,
        client_id: str,
        path: str,
        history_entry_id: str = '',
        tab_id: str = '',
    ):
        return self.remote_file_service.download_file(
            client_id,
            path,
            history_entry_id=history_entry_id,
            tab_id=tab_id,
        )

    def download_remote_paths_as_zip(
        self,
        client_id: str,
        paths: list[str],
        archive_name: str = '',
        history_entry_id: str = '',
        tab_id: str = '',
    ):
        return self.remote_file_service.download_paths_as_zip(
            client_id,
            paths,
            archive_name=archive_name,
            history_entry_id=history_entry_id,
            tab_id=tab_id,
        )

    def create_remote_zip(
        self,
        client_id: str,
        paths: list[str],
        destination_dir: str,
        archive_name: str = '',
    ):
        return self.remote_file_service.create_zip_from_paths(
            client_id,
            paths,
            destination_dir,
            archive_name=archive_name,
        )

    def peek_remote_zip(self, client_id: str, path: str):
        return self.remote_file_service.peek_zip(client_id, path)

    def read_remote_zip_entry(self, client_id: str, path: str, entry_name: str):
        return self.remote_file_service.read_zip_entry(client_id, path, entry_name)

    def extract_remote_zip(self, client_id: str, path: str, destination_dir: str):
        return self.remote_file_service.extract_zip(client_id, path, destination_dir)

    def read_remote_file(
        self,
        client_id: str,
        path: str,
        encoding: str = 'utf-8',
        max_bytes: int = 200000,
    ):
        return self.remote_file_service.get_file_content(client_id, path)

    def save_remote_file(
        self,
        client_id: str,
        path: str,
        content: str,
        encoding: str = 'utf-8',
    ):
        return self.remote_file_service.save_file_content(
            client_id,
            path,
            content,
            encoding=encoding,
        )