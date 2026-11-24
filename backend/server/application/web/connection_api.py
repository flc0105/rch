class WebConnectionApi:
    """
    Web 连接子外观。

    职责：
    - 暴露 connection payload 查询
    - 暴露 connection 生命周期相关能力
    - 暴露面向调用方的连接序列化能力
    - 暴露 machine 级设备分组管理能力
    """

    def __init__(self, connection_service, device_group_store=None, bind_connector=None, saved_bind_target_store=None):
        self.connection_service = connection_service
        self.device_group_store = device_group_store
        self.bind_connector = bind_connector
        self.saved_bind_target_store = saved_bind_target_store

    def connect_bind_client(self, host: str, port: int, server_web_base_url: str = '', name: str = ''):
        session, reused = self.bind_connector.connect_with_status(
            host, port, server_web_base_url=server_web_base_url,
        )
        target = self.saved_bind_target_store.save(
            host, port, server_web_base_url, name=name, session=session,
        )
        session.saved_bind_target_id = target['target_id']
        return {'client_id': session.session_info.client_id,
                'target_id': target['target_id'],
                'status': 'already_connected' if reused else 'connected'}

    def list_saved_bind_targets(self):
        return self.saved_bind_target_store.list_targets()

    def save_bind_target(self, host, port, server_web_base_url, name='', target_id=''):
        return self.saved_bind_target_store.save(
            host, port, server_web_base_url, name=name, target_id=target_id,
        )

    def remove_bind_target(self, target_id):
        return self.connection_service.remove_saved_connection(
            target_id, self.saved_bind_target_store, self.bind_connector,
        )

    def disconnect_connection(self, client_id: str):
        return self.connection_service.disconnect_connection(client_id, self.bind_connector)

    def kill_instance(self, client_id: str):
        return self.connection_service.kill_instance(client_id)

    def reconnect_connection(self, client_id: str):
        return self.connection_service.reconnect_connection(client_id, self.bind_connector)

    def get_connections_payload(self):
        return self.connection_service.get_connections_payload()

    def get_client_revision_status(self, client_id: str):
        return self.connection_service.get_client_revision_status(client_id)

    def get_system_paths(self, client_id: str):
        return self.connection_service.get_system_paths(client_id)

    def serialize_connection(self, session):
        return self.connection_service.serialize_connection(session)

    def get_machine_connection_history(
        self, machine_id: str, *, limit: int = 20, offset: int = 0,
        client_id_search: str = '', integrity: str = '', launch_mode: str = '',
        termination_reason: str = '',
    ):
        return self.connection_service.get_machine_connection_history(
            machine_id, limit=limit, offset=offset, client_id_search=client_id_search,
            integrity=integrity, launch_mode=launch_mode, termination_reason=termination_reason,
        )

    def get_machine_connection_commands(self, machine_id: str, client_id: str, *, limit=None, cursor: str = ''):
        return self.connection_service.get_machine_connection_commands(
            machine_id,
            client_id,
            limit=limit,
            cursor=cursor,
        )

    def create_web_connection(self, transport, addr, info: dict):
        return self.connection_service.create_web_connection(transport, addr, info)

    def handle_connection_registered(self, session):
        self.connection_service.handle_connection_registered(session)

    def handle_connection_closed(self, session):
        self.connection_service.handle_connection_closed(session)

    def handle_replaced_connection_closed(self, session):
        self.connection_service.handle_replaced_connection_closed(session)

    def remove_connection(self, client_id: str, machine_id: str = ''):
        return self.connection_service.remove_connection(client_id, machine_id=machine_id)

    def update_connection_device_view_prefs(self, client_id: str = '', machine_id: str = '', patch: dict = None):
        return self.connection_service.update_connection_device_view_prefs(
            client_id=client_id,
            machine_id=machine_id,
            patch=patch or {},
        )

    def reorder_online_devices(self, machine_ids):
        return self.connection_service.reorder_online_devices(machine_ids)

    def _require_device_group_store(self):
        if self.device_group_store is None:
            raise ValueError('Device group store is unavailable')
        return self.device_group_store

    def get_device_groups(self):
        return self._require_device_group_store().get_state()

    def create_device_group(self, name: str):
        return self._require_device_group_store().create_group(name)

    def rename_device_group(self, group_id: str, name: str):
        return self._require_device_group_store().rename_group(group_id, name)

    def delete_device_group(self, group_id: str):
        return self._require_device_group_store().delete_group(group_id)

    def assign_machine_device_group(self, machine_id: str, group_id: str = ''):
        return self._require_device_group_store().assign_machine(machine_id, group_id)
