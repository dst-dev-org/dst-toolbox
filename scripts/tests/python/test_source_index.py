"""End-to-end generated index tests, including bounded results and stale evidence."""
import importlib.util
import json
import unittest
from pathlib import Path
from test_extraction import ExtractorAssertions, wrapper, BINARY, REPO

spec=importlib.util.spec_from_file_location('source_index',REPO/'scripts/tools/source/source_index.py')
index=importlib.util.module_from_spec(spec);spec.loader.exec_module(index)


class SourceIndexTests(ExtractorAssertions,unittest.TestCase):
    def prepare(self, inputs=None, full_scan=False):
        self.source=self.root/'source';self.source.mkdir()
        inputs=inputs or {'a.lua':b'local function same(x) end\nsame(1);inst:AddComponent("health")',
                          'b.lua':b'local function same(y) end\nsame(2);inst:PushEvent("death",{})',
                          'bad.lua':b'local function broken('}
        for path,data in inputs.items():
            file=self.source/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
        self.snapshot=self.root/'output'
        wrapper.run_extraction(self.source,list(inputs),self.snapshot,'test-v1',{'scheme':'fixture','value':'test-v1'},'fixture',BINARY,full_scan=full_scan)
        return index.build(self.snapshot,self.source)

    def test_definitions_ambiguity_filter_and_limit(self):
        summary=self.prepare()
        self.assertEqual(summary['failed_paths'],['bad.lua'])
        result=index.query(self.snapshot,self.source,'definition','same',limit=1)
        self.assertEqual((result['total'],result['returned'],result['ambiguous'],result['truncated']),(2,1,True,True))
        result=index.query(self.snapshot,self.source,'definition','same',path='b.lua')
        self.assertEqual(result['total'],1)
        exact=index.query(self.snapshot,self.source,'definition',result['results'][0]['id'])
        self.assertEqual(exact['total'],1)

    def test_reverse_target_component_event_and_no_match(self):
        self.prepare()
        definition=index.query(self.snapshot,self.source,'definition','same',path='a.lua')['results'][0]
        target=index.query(self.snapshot,self.source,'target',definition['id'])
        self.assertEqual(target['results'][0]['data']['resolution']['state'],'resolved')
        self.assertEqual(index.query(self.snapshot,self.source,'component','health')['total'],1)
        self.assertEqual(index.query(self.snapshot,self.source,'event','death')['total'],1)
        missing=index.query(self.snapshot,self.source,'definition','missing')
        self.assertEqual(missing['status'],'no-match')
        self.assertEqual(missing['coverage']['failed_files'],1)

    def test_source_change_and_added_full_scan_file_are_stale(self):
        self.prepare(full_scan=True)
        (self.source/'new.lua').write_bytes(b'return 1')
        result=index.query(self.snapshot,self.source,'definition','same')
        self.assertEqual(result['status'],'stale');self.assertFalse(result['results'])
        (self.source/'a.lua').write_bytes(b'return 2')
        self.assertIn('a.lua',index.query(self.snapshot,self.source,'definition','same')['stale_paths'])

    def test_snapshot_or_shard_mutation_is_rejected(self):
        self.prepare()
        name=index.shard_name('definition','same')
        (self.snapshot/'source-index'/name).write_bytes(b'[]')
        with self.assertRaisesRegex(ValueError,'shard changed'):
            index.query(self.snapshot,self.source,'definition','same')
        (self.snapshot/'manifest.json').write_bytes(b'{}')
        self.assertEqual(index.query(self.snapshot,self.source,'definition','same')['status'],'stale')

    def test_build_rejects_stale_facts_and_input_overlap(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,'index exists'): index.build(self.snapshot,self.source)
        with self.assertRaisesRegex(ValueError,'overlaps'): index.build(self.source,self.source)
        (self.source/'a.lua').write_bytes(b'return 9')
        # Different output directory; input hashes continue to refer to original bytes.
        other=self.root/'other'
        import shutil
        shutil.copytree(self.snapshot,other,ignore=shutil.ignore_patterns('source-index'))
        with self.assertRaisesRegex(ValueError,'stale source'): index.build(other,self.source)

    def test_byte_budget_caps_long_arguments(self):
        self.prepare({'a.lua':b'local function f() end\n'+b'\n'.join(b'f("'+b'x'*2000+b'")' for _ in range(8))})
        result=index.query(self.snapshot,self.source,'call','f',limit=20,max_bytes=2000)
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode('utf-8')),2100)
        self.assertTrue(result['truncated'])
        if result['results']:
            self.assertTrue(result['results'][0]['data']['arguments'][0]['truncated'])

    def test_dynamic_reference_is_separate_from_literal_names(self):
        self.prepare({'a.lua':b'inst:AddComponent(name);Prefab(name,unknown);inst:PushEvent(event) '})
        for category in ('component','prefab','event'):
            self.assertEqual(index.query(self.snapshot,self.source,category,'<dynamic>')['total'],1)
            self.assertEqual(index.query(self.snapshot,self.source,category,'known')['status'],'no-match')

    def test_build_change_invalidates_even_identical_source_bytes(self):
        self.source=self.root/'source';self.source.mkdir()
        (self.root/'BUILD.txt').write_text('123',encoding='utf-8')
        (self.source/'a.lua').write_bytes(b'local function f() end')
        self.snapshot=self.root/'snapshot'
        wrapper.run_extraction(self.source,['a.lua'],self.snapshot,'dst-steam-123',{'scheme':'steam-buildid','value':'123'},'game-source',BINARY)
        index.build(self.snapshot,self.source)
        self.assertEqual(index.query(self.snapshot,self.source,'definition','f')['status'],'ok')
        (self.root/'BUILD.txt').write_text('124',encoding='utf-8')
        result=index.query(self.snapshot,self.source,'definition','f')
        self.assertEqual(result['status'],'stale')
        self.assertIn('BUILD.txt',result['stale_paths'])
        self.assertFalse(result['results'])


if __name__=='__main__': unittest.main()
