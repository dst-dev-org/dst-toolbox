"""Independent external-path and precedence checks, without installed Skills."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
import dst_paths

class PathTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.knowledge=self.root/'different location'/'wiki assets'
        (self.knowledge/'wiki').mkdir(parents=True)
        (self.knowledge/'wiki/index.md').write_text('# navigation\n',encoding='utf-8')
        self.config=self.root/'personal.json'

    def test_configuration_points_outside_toolbox_and_missing_source_is_visible(self):
        self.config.write_text(json.dumps({'knowledge_root':str(self.knowledge)}),encoding='utf-8')
        resolved=dst_paths.knowledge_root(config=self.config)
        self.assertEqual(resolved,self.knowledge.resolve())
        self.assertFalse((resolved/'raw/current/scripts').exists())

    def test_explicit_knowledge_does_not_read_malformed_configuration(self):
        self.config.write_text('broken',encoding='utf-8')
        self.assertEqual(dst_paths.knowledge_root(self.knowledge,self.config),self.knowledge.resolve())

    def test_no_root_never_falls_back_to_toolbox_parent(self):
        with self.assertRaisesRegex(ValueError,'specify --knowledge-root'):
            dst_paths.knowledge_root(config=self.config)
        with self.assertRaisesRegex(ValueError,'absolute'):
            dst_paths.knowledge_root('relative/wiki')
        with self.assertRaisesRegex(ValueError,'wiki/index.md'):
            dst_paths.knowledge_root(self.root)

    def test_explicit_source_supports_historical_snapshot_without_global_configuration(self):
        historical=self.root/'old snapshot'/'scripts'
        self.assertEqual(dst_paths.source_root(historical),historical.resolve())

    def test_fixture_root_hint_is_provenance_not_external_checkout_assumption(self):
        fixture={'revision':{'scheme':'fixture'},'root_hint':'scripts/tests/fixtures/extraction'}
        self.assertEqual(dst_paths.catalog_root(fixture),dst_paths.TOOLBOX/'scripts/tests/fixtures/extraction')
        self.assertEqual(dst_paths.catalog_root(fixture,self.root),self.root.resolve())

if __name__=='__main__': unittest.main()
