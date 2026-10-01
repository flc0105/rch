import unittest

from core.metadata.parameters import (
    coerce_path_list_csv_or_sequence,
    coerce_path_list_literal_or_single,
    normalize_param_spec,
)
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
    def test_shared_param_spec_keeps_script_option_normalization_policy(self):
        spec = {'name': ' mode ', 'type': 'select', 'options': ('a', 'b')}
        script_spec = normalize_param_spec(spec, normalize_options=True)
        job_spec = normalize_param_spec(spec, normalize_options=False)

        self.assertEqual('mode', script_spec['name'])
        self.assertEqual(['a', 'b'], script_spec['options'])
        self.assertEqual(('a', 'b'), job_spec['options'])

    def test_script_and_job_share_boolean_number_and_limit_semantics(self):
        for coerce in (coerce_script_param_value, coerce_job_param_value):
            self.assertTrue(coerce({'name': 'enabled', 'type': 'bool'}, 'yes'))
            self.assertEqual(3, coerce({'name': 'count', 'type': 'int', 'min': 1, 'max': 5}, '3'))
            with self.assertRaisesRegex(ValueError, 'Invalid boolean param: enabled'):
                coerce({'name': 'enabled', 'type': 'bool'}, 'maybe')
            with self.assertRaisesRegex(ValueError, 'must be >= 2'):
                coerce({'name': 'count', 'type': 'int', 'min': 2}, '1')

    def test_script_select_validation_remains_script_specific(self):
        spec = {'name': 'mode', 'type': 'select', 'options': ['a', 'b']}
        self.assertEqual('a', coerce_script_param_value(spec, 'a'))
        with self.assertRaisesRegex(ValueError, 'Invalid option for mode: c'):
            coerce_script_param_value(spec, 'c')
        self.assertEqual('c', coerce_job_param_value(spec, 'c'))

    def test_remote_path_list_policies_remain_intentionally_different(self):
        self.assertEqual(['/a', '/b'], coerce_path_list_literal_or_single('["/a", "/b"]', 'paths'))
        self.assertEqual(['/a,/b'], coerce_path_list_literal_or_single('/a,/b', 'paths'))
        self.assertEqual(['/a', '/b'], coerce_path_list_csv_or_sequence('/a,/b', 'paths'))
        self.assertEqual(['["/a"', '"/b"]'], coerce_path_list_csv_or_sequence('["/a", "/b"]', 'paths'))

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
        source = '''\nSCRIPT_METADATA = {\n    "name": "demo",\n    "platforms": ["Darwin", "Ubuntu"],\n    "params": [\n        {"name": "count", "type": "int", "required": True, "min": 1, "max": 5},\n        {"name": "mode", "type": "select", "options": ("a", "b"), "default": "a"},\n        {"name": "paths", "type": "remote_files"},\n    ],\n}\n'''
        metadata = read_script_metadata_from_source(source)
        self.assertEqual(['mac', 'linux'], metadata['platforms'])
        self.assertEqual(['a', 'b'], metadata['params'][1]['options'])
        self.assertEqual(
            {'count': 3, 'mode': 'b', 'paths': ['/a', '/b']},
            resolve_script_params(metadata, {'count': '3', 'mode': 'b', 'paths': '["/a", "/b"]'}),
        )

    def test_job_execution_mode_aliases_remain_job_specific(self):
        self.assertEqual('inproc', normalize_job_execution_mode('threaded'))
        self.assertEqual('subprocess', normalize_job_execution_mode('process'))
        self.assertEqual(['subprocess', 'inproc'], normalize_job_execution_allowed(['process', 'thread', 'subprocess']))
        with self.assertRaisesRegex(ValueError, 'Unsupported background job execution mode'):
            normalize_job_execution_mode('unknown')

    def test_job_metadata_source_class_and_execution_policy_stay_job_specific(self):
        source = '''\nclass DemoJob:\n    JOB_METADATA = {\n        "name": "demo-job",\n        "platforms": ["macOS"],\n        "execution": {"default": "subprocess", "allowed": ["inproc", "subprocess"]},\n        "params": [\n            {"name": "count", "type": "int", "required": True, "min": 1, "max": 5},\n            {"name": "paths", "type": "remote_files"},\n        ],\n    }\n'''
        metadata = read_job_metadata_from_source(source)
        self.assertEqual('subprocess', metadata['execution_mode'])
        self.assertEqual(['inproc', 'subprocess'], metadata['allowed'])
        self.assertEqual(['mac'], metadata['platforms'])
        self.assertEqual(
            {'count': 3, 'paths': ['/a', '/b']},
            resolve_job_params(metadata, {'count': '3', 'paths': '/a,/b'}),
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
