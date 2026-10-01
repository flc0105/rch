import unittest

from core.metadata.parameters import coerce_path_list, normalize_param_spec
from core.platform.normalization import is_platform_supported, normalize_platforms
from core.utils.job_metadata import (
    coerce_job_param_value,
    is_platform_supported as is_job_platform_supported,
    normalize_job_execution_allowed,
    normalize_job_execution_mode,
    normalize_job_metadata,
    normalize_job_platform,
    read_job_metadata_from_source,
    resolve_job_params,
)
from core.utils.script_metadata import (
    coerce_script_param_value,
    normalize_script_metadata,
    normalize_script_platform,
    read_script_metadata_from_source,
    resolve_script_params,
)


class ScriptJobMetadataRound4Tests(unittest.TestCase):
    def test_shared_param_spec_normalizes_label_options_and_textarea(self):
        spec = normalize_param_spec({
            'name': ' notes ',
            'type': 'multiline',
            'label': ' Notes ',
            'options': ('a', 'b'),
        })
        self.assertEqual('notes', spec['name'])
        self.assertEqual('Notes', spec['label'])
        self.assertEqual('textarea', spec['type'])
        self.assertEqual(['a', 'b'], spec['options'])

        default_label = normalize_param_spec({'name': 'mode', 'type': 'select', 'options': ('a', 'b')})
        self.assertEqual('mode', default_label['label'])
        self.assertEqual(['a', 'b'], default_label['options'])

    def test_script_and_job_share_boolean_number_and_limit_semantics(self):
        for coerce in (coerce_script_param_value, coerce_job_param_value):
            self.assertTrue(coerce({'name': 'enabled', 'type': 'bool'}, 'yes'))
            self.assertEqual(3, coerce({'name': 'count', 'type': 'int', 'min': 1, 'max': 5}, '3'))
            self.assertEqual(3.5, coerce({'name': 'ratio', 'type': 'number'}, '3.5'))
            with self.assertRaisesRegex(ValueError, 'Invalid boolean param: enabled'):
                coerce({'name': 'enabled', 'type': 'bool'}, 'maybe')
            with self.assertRaisesRegex(ValueError, 'must be >= 2'):
                coerce({'name': 'count', 'type': 'int', 'min': 2}, '1')

    def test_script_and_job_share_select_validation(self):
        spec = {'name': 'mode', 'type': 'select', 'options': ['a', 'b']}
        for coerce in (coerce_script_param_value, coerce_job_param_value):
            self.assertEqual('a', coerce(spec, 'a'))
            with self.assertRaisesRegex(ValueError, 'Invalid option for mode: c'):
                coerce(spec, 'c')

    def test_remote_path_lists_are_canonical_arrays_only(self):
        self.assertEqual(['/a', '/b'], coerce_path_list(['/a', '/b'], 'paths'))
        with self.assertRaisesRegex(ValueError, 'Invalid path list param: paths'):
            coerce_path_list(('/a', '/b'), 'paths')
        with self.assertRaisesRegex(ValueError, 'Invalid path list param: paths'):
            coerce_path_list('/a,/b', 'paths')
        with self.assertRaisesRegex(ValueError, 'Invalid path list param: paths'):
            coerce_path_list('["/a", "/b"]', 'paths')

        meta = {'params': [{'name': 'paths', 'type': 'remote_files'}]}
        self.assertEqual({'paths': ['/a', '/b']}, resolve_script_params(meta, {'paths': ['/a', '/b']}))
        self.assertEqual({'paths': ['/a', '/b']}, resolve_job_params(meta, {'paths': ['/a', '/b']}))
        with self.assertRaisesRegex(ValueError, 'Invalid path list param: paths'):
            resolve_script_params(meta, {'paths': '/a,/b'})
        with self.assertRaisesRegex(ValueError, 'Invalid path list param: paths'):
            resolve_job_params(meta, {'paths': '/a,/b'})

    def test_required_error_messages_and_extra_params_are_preserved(self):
        script_meta = {'params': [{'name': 'count', 'type': 'int', 'required': True}]}
        job_meta = {'params': [{'name': 'count', 'type': 'int', 'required': True}]}

        with self.assertRaisesRegex(ValueError, 'Missing required script param: count'):
            resolve_script_params(script_meta, {})
        with self.assertRaisesRegex(ValueError, 'Missing required job param: count'):
            resolve_job_params(job_meta, {})

        self.assertEqual({'count': 3, 'extra': 'x'}, resolve_script_params(script_meta, {'count': '3', 'extra': 'x'}))
        self.assertEqual({'count': 3, 'extra': 'x'}, resolve_job_params(job_meta, {'count': '3', 'extra': 'x'}))

    def test_platform_lists_use_canonical_shared_normalization(self):
        self.assertEqual(['mac', 'linux', '*'], normalize_platforms(['Darwin', 'Ubuntu', 'all', 'macOS']))
        self.assertEqual('linux', normalize_script_platform('Ubuntu'))
        self.assertEqual('linux', normalize_job_platform('Ubuntu'))
        self.assertTrue(is_platform_supported('linux', ['Ubuntu']))
        self.assertTrue(is_job_platform_supported('Darwin', ['macOS']))
        self.assertFalse(is_job_platform_supported('win', ['mac']))

    def test_script_metadata_source_and_param_behavior(self):
        source = '''\nSCRIPT_METADATA = {\n    "name": "demo",\n    "platforms": ["Darwin", "Ubuntu"],\n    "params": [\n        {"name": "count", "type": "int", "required": True, "min": 1, "max": 5},\n        {"name": "mode", "type": "select", "options": ("a", "b"), "default": "a"},\n        {"name": "notes", "type": "textarea", "label": "Notes"},\n        {"name": "paths", "type": "remote_files"},\n    ],\n}\n'''
        metadata = read_script_metadata_from_source(source)
        self.assertEqual(['mac', 'linux'], metadata['platforms'])
        self.assertEqual(['a', 'b'], metadata['params'][1]['options'])
        self.assertEqual('Notes', metadata['params'][2]['label'])
        self.assertEqual(
            {'count': 3, 'mode': 'b', 'notes': ' hello\nworld ', 'paths': ['/a', '/b']},
            resolve_script_params(metadata, {
                'count': '3',
                'mode': 'b',
                'notes': ' hello\nworld ',
                'paths': ['/a', '/b'],
            }),
        )

    def test_job_execution_mode_aliases_remain_job_specific(self):
        self.assertEqual('inproc', normalize_job_execution_mode('threaded'))
        self.assertEqual('subprocess', normalize_job_execution_mode('process'))
        self.assertEqual(['subprocess', 'inproc'], normalize_job_execution_allowed(['process', 'thread', 'subprocess']))
        with self.assertRaisesRegex(ValueError, 'Unsupported background job execution mode'):
            normalize_job_execution_mode('unknown')

    def test_job_metadata_source_class_and_execution_policy_stay_job_specific(self):
        source = '''\nclass DemoJob:\n    JOB_METADATA = {\n        "name": "demo-job",\n        "platforms": ["macOS"],\n        "execution": {"default": "subprocess", "allowed": ["inproc", "subprocess"]},\n        "params": [\n            {"name": "count", "type": "int", "required": True, "min": 1, "max": 5},\n            {"name": "mode", "type": "select", "options": ["fast", "safe"]},\n            {"name": "notes", "type": "textarea", "label": "Notes"},\n            {"name": "paths", "type": "remote_files"},\n        ],\n    }\n'''
        metadata = read_job_metadata_from_source(source)
        self.assertEqual('subprocess', metadata['execution_mode'])
        self.assertEqual(['inproc', 'subprocess'], metadata['allowed'])
        self.assertEqual(['mac'], metadata['platforms'])
        self.assertEqual(['fast', 'safe'], metadata['params'][1]['options'])
        self.assertEqual('Notes', metadata['params'][2]['label'])
        self.assertEqual(
            {'count': 3, 'mode': 'safe', 'notes': 'notes', 'paths': ['/a', '/b']},
            resolve_job_params(metadata, {
                'count': '3',
                'mode': 'safe',
                'notes': 'notes',
                'paths': ['/a', '/b'],
            }),
        )

    def test_normalized_metadata_retains_existing_shape(self):
        script = normalize_script_metadata({'name': 's', 'tags': [' x '], 'category': ' c '})
        self.assertEqual('s', script['display_name'])
        self.assertEqual(['x'], script['tags'])
        self.assertEqual('c', script['category'])

        job = normalize_job_metadata({'name': 'j'})
        self.assertEqual('j', job['display_name'])
        self.assertEqual('inproc', job['execution_mode'])
        self.assertEqual(['inproc', 'subprocess'], job['allowed'])


if __name__ == '__main__':
    unittest.main()
