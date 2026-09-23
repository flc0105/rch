import os

from flask import Blueprint, request, send_file

from server.web.api_response import WebApiResponder
from server.web.auth_guard import allow_anonymous
from server.web.request_parsers import get_json_payload, get_optional_tab_id


def create_external_tool_blueprint(server_instance):
    blueprint = Blueprint('external_tools', __name__)
    external_tool_api = server_instance.web_service.external_tool_api
    request_context = external_tool_api.request_context
    catalog_api = external_tool_api.catalog
    client_lifecycle_api = external_tool_api.client_lifecycle
    param_preset_api = external_tool_api.param_presets
    responder = WebApiResponder()

    @blueprint.get('/api/external-tools/catalog')
    def list_external_tools():
        return responder.json_endpoint(
            lambda: catalog_api.list_catalog(),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/external-tools/catalog')
    def list_client_external_tools(client_id):
        def _execute():
            platform_alias, arch = request_context.resolve_client_target(client_id, get_json_payload())
            return catalog_api.list_client_catalog(
                client_id,
                tab_id=get_optional_tab_id(),
                platform_alias=platform_alias,
                arch=arch,
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/external-tools/<tool_id>')
    def get_external_tool(tool_id):
        return responder.json_endpoint(
            lambda: catalog_api.get_tool(tool_id),
            default_error_status=500,
        )

    @blueprint.get('/api/external-tools/<tool_id>/param-presets')
    def list_external_tool_param_presets(tool_id):
        return responder.json_endpoint(
            lambda: param_preset_api.list_presets(tool_id),
            default_error_status=500,
        )

    @blueprint.post('/api/external-tools/<tool_id>/param-presets')
    def create_external_tool_param_preset(tool_id):
        def _execute():
            payload = get_json_payload()
            return param_preset_api.create_preset(
                tool_id,
                str(payload.get('name') or ''),
                payload.get('params'),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.put('/api/external-tools/<tool_id>/param-presets/<preset_id>')
    def update_external_tool_param_preset(tool_id, preset_id):
        def _execute():
            payload = get_json_payload()
            params = payload.get('params') if 'params' in payload else None
            return param_preset_api.update_preset(
                tool_id,
                preset_id,
                name=str(payload.get('name') or ''),
                params=params,
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/external-tools/<tool_id>/param-presets/<preset_id>')
    def delete_external_tool_param_preset(tool_id, preset_id):
        return responder.json_endpoint(
            lambda: param_preset_api.delete_preset(tool_id, preset_id),
            default_error_status=500,
        )

    @blueprint.get('/api/external-tools/<tool_id>/meta/content')
    def read_external_tool_meta(tool_id):
        return responder.json_endpoint(
            lambda: catalog_api.read_meta_content(tool_id),
            default_error_status=500,
        )

    @blueprint.post('/api/external-tools/<tool_id>/meta/content')
    def save_external_tool_meta(tool_id):
        def _execute():
            payload = get_json_payload()
            return catalog_api.save_meta_content(tool_id, str(payload.get('content') or ''))
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/external-tools/<tool_id>/download')
    @allow_anonymous
    def download_external_tool_by_id(tool_id):
        try:
            platform_alias, arch = request_context.target_from_query(request.args)
            filename = catalog_api.get_package_download_filename(tool_id, platform_alias=platform_alias, arch=arch)
            file_path = catalog_api.get_package_path(filename)
            return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))
        except Exception as e:
            return responder.map_common_error(e)

    @blueprint.get('/api/external-tools/packages/<filename>')
    @allow_anonymous
    def download_external_tool_package(filename):
        try:
            file_path = catalog_api.get_package_path(filename)
            return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))
        except Exception as e:
            return responder.map_common_error(e)

    # Client lifecycle. These endpoints submit commands to the target client.
    @blueprint.post('/api/connections/<client_id>/external-tools/instances')
    def list_all_client_instances(client_id):
        return responder.json_endpoint(
            lambda: client_lifecycle_api.list_all_client_instances(
                client_id,
                tab_id=get_optional_tab_id(),
            ),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/instances')
    def list_client_instances(client_id, tool_id):
        return responder.json_endpoint(
            lambda: client_lifecycle_api.list_client_instances(
                client_id,
                tool_id,
                tab_id=get_optional_tab_id(),
            ),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/launcher')
    def resolve_client_launcher(client_id, tool_id):
        def _execute():
            ctx = request_context.client_payload(client_id, get_json_payload(), tab_id=get_optional_tab_id())
            return client_lifecycle_api.resolve_client_launcher(
                client_id,
                tool_id,
                tab_id=ctx.tab_id,
                platform_alias=ctx.platform_alias,
                arch=ctx.arch,
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/instances/start')
    def start_client_instance(client_id, tool_id):
        def _execute():
            ctx = request_context.client_payload(client_id, get_json_payload(), tab_id=get_optional_tab_id())
            return client_lifecycle_api.start_client_instance(
                client_id,
                tool_id,
                params=ctx.params,
                instance_id=ctx.instance_id,
                tab_id=ctx.tab_id,
                platform_alias=ctx.platform_alias,
                arch=ctx.arch,
                launcher_override=ctx.payload.get('launcher_override'),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/instances/preview-command')
    def preview_client_instance_command(client_id, tool_id):
        def _execute():
            ctx = request_context.client_payload(client_id, get_json_payload(), tab_id=get_optional_tab_id())
            return client_lifecycle_api.preview_client_instance_command(
                client_id,
                tool_id,
                params=ctx.params,
                instance_id=ctx.instance_id,
                tab_id=ctx.tab_id,
                platform_alias=ctx.platform_alias,
                arch=ctx.arch,
                launcher_override=ctx.payload.get('launcher_override'),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/oneshot')
    def run_client_oneshot(client_id, tool_id):
        def _execute():
            ctx = request_context.client_payload(client_id, get_json_payload(), tab_id=get_optional_tab_id())
            return client_lifecycle_api.run_client_oneshot(
                client_id,
                tool_id,
                params=ctx.params,
                tab_id=ctx.tab_id,
                platform_alias=ctx.platform_alias,
                arch=ctx.arch,
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/install')
    def install_client_tool(client_id, tool_id):
        def _execute():
            ctx = request_context.client_payload(client_id, get_json_payload(), tab_id=get_optional_tab_id())
            return client_lifecycle_api.install_client_tool(
                client_id,
                tool_id,
                params=ctx.params,
                instance_id=ctx.instance_id,
                tab_id=ctx.tab_id,
                platform_alias=ctx.platform_alias,
                arch=ctx.arch,
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/install-status')
    def client_install_status(client_id, tool_id):
        def _execute():
            ctx = request_context.client_payload(client_id, get_json_payload(), tab_id=get_optional_tab_id())
            return client_lifecycle_api.client_install_status(
                client_id,
                tool_id,
                params=ctx.params,
                instance_id=ctx.instance_id,
                tab_id=ctx.tab_id,
                platform_alias=ctx.platform_alias,
                arch=ctx.arch,
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/uninstall')
    def uninstall_client_tool(client_id, tool_id):
        def _execute():
            ctx = request_context.client_payload(client_id, get_json_payload(), tab_id=get_optional_tab_id())
            return client_lifecycle_api.uninstall_client_tool(
                client_id,
                tool_id,
                params=ctx.params,
                instance_id=ctx.instance_id,
                tab_id=ctx.tab_id,
                platform_alias=ctx.platform_alias,
                arch=ctx.arch,
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/clear-cache')
    def clear_client_package_cache(client_id, tool_id):
        def _execute():
            ctx = request_context.client_payload(client_id, get_json_payload(), tab_id=get_optional_tab_id())
            return client_lifecycle_api.clear_client_package_cache(
                client_id,
                tool_id,
                params=ctx.params,
                instance_id=ctx.instance_id,
                tab_id=ctx.tab_id,
                platform_alias=ctx.platform_alias,
                arch=ctx.arch,
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/instances/<instance_id>/stop')
    def stop_client_instance(client_id, tool_id, instance_id):
        def _execute():
            ctx = request_context.payload(get_json_payload())
            return client_lifecycle_api.stop_client_instance(
                client_id,
                tool_id,
                instance_id=instance_id,
                params=ctx.params,
                tab_id=get_optional_tab_id(),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/instances/<instance_id>/status')
    def status_client_instance(client_id, tool_id, instance_id):
        return responder.json_endpoint(
            lambda: client_lifecycle_api.status_client_instance(
                client_id,
                tool_id,
                instance_id=instance_id,
                tab_id=get_optional_tab_id(),
            ),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/instances/<instance_id>/logs')
    def read_client_instance_logs(client_id, tool_id, instance_id):
        def _execute():
            payload = get_json_payload()
            max_bytes = request_context.max_bytes_from_payload(payload)
            return client_lifecycle_api.read_client_logs(
                client_id,
                tool_id,
                instance_id=instance_id,
                max_bytes=max_bytes,
                tab_id=get_optional_tab_id(),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/instances/<instance_id>/remove')
    def remove_client_instance(client_id, tool_id, instance_id):
        return responder.json_endpoint(
            lambda: client_lifecycle_api.remove_client_instance(
                client_id,
                tool_id,
                instance_id=instance_id,
                tab_id=get_optional_tab_id(),
            ),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/external-tools/<tool_id>/instances/<instance_id>/clear-logs')
    def clear_client_instance_logs(client_id, tool_id, instance_id):
        return responder.json_endpoint(
            lambda: client_lifecycle_api.clear_client_logs(
                client_id,
                tool_id,
                instance_id=instance_id,
                tab_id=get_optional_tab_id(),
            ),
            default_error_status=500,
        )

    return blueprint
