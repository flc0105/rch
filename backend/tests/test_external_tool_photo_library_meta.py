"""Photo Library bundle metadata and optional directory parameter regressions."""
import json
from pathlib import Path
import unittest

from core.external_tools.meta import normalize_meta
from core.metadata.parameters import resolve_param_values
from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService

META = Path(__file__).resolve().parents[1] / 'server/resources/external_tools/metas/photo-library.json'


class PhotoLibraryExternalToolMetaTests(unittest.TestCase):
    def setUp(self):
        self.package = normalize_meta(json.loads(META.read_text(encoding='utf-8')))
        self.module = self.package['modules'][0]

    def test_web_daemon_python_bundle(self):
        self.assertEqual(self.module['tool_id'], 'photo-library.web')
        self.assertEqual(self.package['execs']['photo-library']['launcher']['type'], 'client_python')
        self.assertEqual(self.package['platform_packages']['common-all']['root'], '')
        self.assertEqual(self.module['runtime']['argv'][0], '{{bin_photo_library}}')

    def test_explicit_empty_paths_preserve_project_fallback(self):
        params = {'instance_name': 'demo', 'address': '127.0.0.1', 'port': 8081,
                  'data_dir': '', 'storage_dir': ''}
        result = resolve_param_values(self.module['params'], params,
                                      missing_required_message=lambda name: name,
                                      include_missing=True)
        self.assertEqual(result['data_dir'], '')
        self.assertEqual(result['storage_dir'], '')

    def test_unset_values_show_prefilled_paths(self):
        result = resolve_param_values(self.module['params'], {},
                                      missing_required_message=lambda name: name,
                                      include_missing=True)
        self.assertEqual(result['data_dir'], '/Volumes/T7/Projects/photo_library/data')
        self.assertEqual(result['storage_dir'], '/Volumes/T7/Projects/photo_library/storage')

    def test_previous_meta_without_allow_empty_keeps_its_defaults(self):
        other = [{'name': 'path', 'type': 'string', 'required': False, 'default': '/original'}]
        result = resolve_param_values(other, {'path': ''},
                                      missing_required_message=lambda name: name,
                                      include_missing=True)
        self.assertEqual(result['path'], '/original')


if __name__ == '__main__':
    unittest.main()
