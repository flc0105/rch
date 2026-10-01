import json
import os
import unittest

from core.external_tools.meta import normalize_meta
from core.metadata.parameters import normalize_param_specs
from server.application.external_tools.external_tool_runtime_base import ExternalToolRuntimeBase


class ParameterSchemaUnificationV133Tests(unittest.TestCase):
    def test_external_tool_uses_shared_schema_shape(self):
        specs = normalize_param_specs([
            {'name': 'mode', 'type': 'select', 'options': ('fast', 'safe')},
            {'name': 'notes', 'type': 'text', 'label': 'Notes'},
            {'name': 'paths', 'type': 'remote_files'},
        ])
        self.assertEqual('mode', specs[0]['label'])
        self.assertEqual(['fast', 'safe'], specs[0]['options'])
        self.assertEqual('textarea', specs[1]['type'])
        self.assertEqual('Notes', specs[1]['label'])
        self.assertTrue(specs[2]['multiple'])

    def test_external_tool_runtime_uses_shared_select_limits_and_textarea(self):
        runtime = ExternalToolRuntimeBase(None, None)
        meta = {
            'params': [
                {'name': 'mode', 'type': 'select', 'options': ['fast', 'safe'], 'required': True},
                {'name': 'count', 'type': 'integer', 'min': 1, 'max': 3},
                {'name': 'ratio', 'type': 'number'},
                {'name': 'notes', 'type': 'textarea'},
                {'name': 'paths', 'type': 'remote_files'},
                {'name': 'optional', 'type': 'string'},
            ],
        }
        resolved = runtime.resolve_params(meta, {
            'mode': 'safe',
            'count': '2',
            'ratio': '1.5',
            'notes': '  keep whitespace\n',
            'paths': ['/a', '/b'],
        })
        self.assertEqual('safe', resolved['mode'])
        self.assertEqual(2, resolved['count'])
        self.assertEqual(1.5, resolved['ratio'])
        self.assertEqual('  keep whitespace\n', resolved['notes'])
        self.assertEqual(['/a', '/b'], resolved['paths'])
        self.assertEqual('', resolved['optional'])

        with self.assertRaisesRegex(ValueError, 'Invalid option for mode: other'):
            runtime.resolve_params(meta, {'mode': 'other'})
        with self.assertRaisesRegex(ValueError, 'must be <= 3'):
            runtime.resolve_params(meta, {'mode': 'fast', 'count': '4'})
        with self.assertRaisesRegex(ValueError, 'Invalid path list param: paths'):
            runtime.resolve_params(meta, {'mode': 'fast', 'paths': '/a,/b'})

    def test_external_tool_required_policy_is_preserved_without_compat_layer(self):
        runtime = ExternalToolRuntimeBase(None, None)
        meta = {'params': [{'name': 'token', 'type': 'string', 'required': True}]}
        with self.assertRaisesRegex(ValueError, 'param token is required'):
            runtime.resolve_params(meta, {}, require_required=True)
        self.assertEqual({'token': ''}, runtime.resolve_params(meta, {}, require_required=False))

    def test_existing_external_tool_meta_files_load_without_changes(self):
        meta_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'server', 'resources', 'external_tools', 'metas',
        )
        loaded = 0
        for name in sorted(os.listdir(meta_dir)):
            if not name.endswith('.json'):
                continue
            path = os.path.join(meta_dir, name)
            with open(path, 'r', encoding='utf-8') as file_obj:
                source = json.load(file_obj)
            normalized = normalize_meta(source, path=path)
            self.assertTrue(normalized['modules'])
            for spec in normalized.get('params') or []:
                self.assertTrue(spec.get('label'))
            for module in normalized.get('modules') or []:
                for spec in module.get('params') or []:
                    self.assertTrue(spec.get('label'))
            loaded += 1
        self.assertGreater(loaded, 0)


if __name__ == '__main__':
    unittest.main()
