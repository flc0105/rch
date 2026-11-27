"""Persistent, manually managed TCP tunnel instances.

All entrypoints (builtin command and Web API) use the same validation,
configuration store, and lifecycle. Both exposure directions reuse the TCP relay.
"""
import re
import threading

from core.protocol.control import ControlDomain, TunnelAction
from server.application.preferences.settings_store import SettingsStore
from tunnel.exposure import manager_for

_NAME = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
_FIELDS = ('expose_on', 'listen_host', 'listen_port', 'target_host', 'target_port')
_DEFAULTS = {'expose_on': 'client', 'listen_host': '127.0.0.1', 'target_host': '127.0.0.1'}


def validate_name(name):
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError('Mapping name must be 1–32 lowercase letters, digits, - or _ (start with a letter)')
    return name


def validate_config(payload):
    if not isinstance(payload, dict):
        raise ValueError('Tunnel configuration must be an object')
    unknown = set(payload).difference((*_FIELDS, 'name'))
    if unknown:
        raise ValueError('Unknown tunnel option: ' + sorted(unknown)[0])
    config = {key: payload.get(key, default) for key, default in _DEFAULTS.items()}
    config.update({key: payload.get(key) for key in ('listen_port', 'target_port')})
    if config['expose_on'] not in ('server', 'client'):
        raise ValueError('Expose on must be server or client')
    for key in ('listen_host', 'target_host'):
        value = config[key]
        if (not isinstance(value, str) or not value or value != value.strip()
                or len(value) > 253 or any(char.isspace() for char in value)
                or any(char in '/\\@' for char in value)):
            raise ValueError(f'Invalid {key.replace("_", " ")}')
    for key in ('listen_port', 'target_port'):
        value = config[key]
        if type(value) is not int or not 1 <= value <= 65535:
            raise ValueError(f'{key.replace("_", " ")} must be a port between 1 and 65535')
    return {key: config[key] for key in _FIELDS}


class TunnelInstanceService:
    def __init__(self, server):
        self.server = server
        self.settings = SettingsStore(server.database, 'tunnel_instances')
        self.runtime = manager_for(server)
        self.lock = threading.RLock()

    def _all(self):
        return self.settings.read()

    def _client(self, client_id):
        value = str(client_id or '').strip()
        if not value:
            raise ValueError('client_id is required')
        return value

    def _configs(self, client_id):
        data = self._all().get(self._client(client_id), {})
        return {name: validate_config(config) for name, config in data.items()} if isinstance(data, dict) else {}

    def _save(self, client_id, configs):
        data = self._all()
        data[client_id] = configs
        self.settings.write(data)

    def _connection(self, client_id):
        try:
            conn = self.server.get_target_connection_by_client_id(client_id)
        except Exception as exc:
            raise ValueError('Client is offline; reconnect before managing running tunnels') from exc
        return conn

    def _check_conflicts(self, configs, name, config):
        for other_name, other in configs.items():
            if (other_name != name and other['expose_on'] == config['expose_on']
                    and other['listen_port'] == config['listen_port']
                    and other['listen_host'] == config['listen_host']):
                raise ValueError(f'Listen port {config["listen_port"]} already assigned to {other_name}')

    def list(self, client_id):
        client_id = self._client(client_id)
        with self.lock:
            configs = self._configs(client_id)
            runtime = self.runtime.list(client_id)
            running = {row['name'] for row in runtime['mappings']}
            rows = [dict(name=name, **config,
                         status=('running' if runtime['connected'] else 'error')
                         if name in running else 'stopped')
                    for name, config in sorted(configs.items())]
            return dict(client_id=client_id, instances=rows,
                        connected=runtime['connected'], streams=runtime['streams'],
                        last_error=runtime['last_error'])

    def status(self, client_id, name):
        name = validate_name(name)
        for instance in self.list(client_id)['instances']:
            if instance['name'] == name:
                return instance
        raise ValueError(f'No tunnel instance named {name}')

    def create(self, client_id, name, payload):
        client_id, name = self._client(client_id), validate_name(name)
        config = validate_config(payload)
        with self.lock:
            configs = self._configs(client_id)
            if name in configs:
                raise ValueError(f'Tunnel instance already exists: {name}')
            self._check_conflicts(configs, name, config)
            configs[name] = config
            self._save(client_id, configs)
            return self.status(client_id, name)

    def edit(self, client_id, name, payload):
        client_id, name = self._client(client_id), validate_name(name)
        with self.lock:
            configs = self._configs(client_id)
            if name not in configs:
                raise ValueError(f'No tunnel instance named {name}')
            if self.status(client_id, name)['status'] != 'stopped':
                raise ValueError('Stop the tunnel before editing')
            config = validate_config({**configs[name], **payload})
            self._check_conflicts(configs, name, config)
            configs[name] = config
            self._save(client_id, configs)
            return self.status(client_id, name)

    def remove(self, client_id, name):
        client_id, name = self._client(client_id), validate_name(name)
        with self.lock:
            configs = self._configs(client_id)
            if name not in configs:
                raise ValueError(f'No tunnel instance named {name}')
            if self.status(client_id, name)['status'] != 'stopped':
                raise ValueError('Stop the tunnel before deleting')
            del configs[name]
            self._save(client_id, configs)
            return {'name': name, 'deleted': True}

    @staticmethod
    def _control(remote, conn, action, payload):
        completion = remote.run_foreground_control(
            conn, ControlDomain.TUNNEL, action, payload,
            task_type='tunnel', source='tunnel',
        )
        if not completion.succeeded:
            raise RuntimeError(completion.event.get('message') or 'Tunnel control failed')

    def start(self, client_id, name, remote):
        client_id, name = self._client(client_id), validate_name(name)
        with self.lock:
            config = self._configs(client_id).get(name)
            if config is None:
                raise ValueError(f'No tunnel instance named {name}')
            if self.status(client_id, name)['status'] != 'stopped':
                raise ValueError('Tunnel is already running or needs recovery; stop it first')
            conn = self._connection(client_id)
            def dispatch(action, payload):
                self._control(remote, conn,
                              TunnelAction.START if action == 'start' else TunnelAction.STOP, payload)
            self.runtime.start(client_id, conn, name, config, dispatch)
            return self.status(client_id, name)

    def stop(self, client_id, name, remote):
        client_id, name = self._client(client_id), validate_name(name)
        with self.lock:
            snapshot = self.status(client_id, name)
            if snapshot['status'] == 'stopped':
                return snapshot
            conn = self._connection(client_id)
            def dispatch(action, payload):
                self._control(remote, conn,
                              TunnelAction.START if action == 'start' else TunnelAction.STOP, payload)
            self.runtime.stop(client_id, name, dispatch)
            return self.status(client_id, name)

    def restart(self, client_id, name, remote):
        client_id, name = self._client(client_id), validate_name(name)
        with self.lock:
            if self.status(client_id, name)['status'] != 'stopped':
                self.stop(client_id, name, remote)
            return self.start(client_id, name, remote)

    def stop_all(self, client_id, remote):
        names = [row['name'] for row in self.list(client_id)['instances'] if row['status'] != 'stopped']
        for name in names:
            self.stop(client_id, name, remote)
        return {'stopped': names}


_service_lock = threading.Lock()


def instance_service_for(server):
    """Lazy shared instance service; nothing is started on Server boot."""
    with _service_lock:
        if not hasattr(server, '_tunnel_instance_service'):
            server._tunnel_instance_service = TunnelInstanceService(server)
        return server._tunnel_instance_service
