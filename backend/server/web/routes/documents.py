"""Authenticated Server-local Markdown document endpoints."""
from flask import Blueprint, request

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_documents_blueprint(server_instance):
    blueprint = Blueprint('documents', __name__)
    library = server_instance.web_service.document_library_api
    responder = WebApiResponder()

    @blueprint.get('/api/documents/roots')
    def roots():
        return responder.json_endpoint(library.list_roots)

    @blueprint.get('/api/documents/tree')
    def tree():
        return responder.json_endpoint(lambda: library.list_tree(
            request.args.get('root_id', ''), request.args.get('path', '')))

    @blueprint.get('/api/documents/content')
    def content():
        return responder.json_endpoint(lambda: library.read_document(
            request.args.get('root_id', ''), request.args.get('path', '')))

    @blueprint.put('/api/documents/content')
    def save():
        def perform():
            data = get_json_payload()
            return library.save_document(data.get('root_id'), data.get('path'),
                                         data.get('content'), data.get('encoding'), data.get('sha256'))
        return responder.json_endpoint(perform)

    @blueprint.post('/api/documents/files')
    def create_file():
        def perform():
            data = get_json_payload()
            return library.create_document(data.get('root_id'), data.get('path'))
        return responder.json_endpoint(perform)

    @blueprint.post('/api/documents/directories')
    def create_dir():
        def perform():
            data = get_json_payload()
            return library.create_directory(data.get('root_id'), data.get('path'))
        return responder.json_endpoint(perform)

    return blueprint
