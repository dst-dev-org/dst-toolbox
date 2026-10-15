"""Exercise the real Rust extractor; build it first. Independent sources/evidence assertions."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / "scripts/fullmoon-dst"
BINARY = TOOL / "target/debug" / ("fullmoon-dst.exe" if sys.platform == "win32" else "fullmoon-dst")
SCHEMA = json.loads((REPO / "scripts/schemas/contract.schema.json").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("parse_scripts", REPO / "scripts/tools/source/parse_scripts.py")
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


class ExtractorAssertions:
    @classmethod
    def setUpClass(cls):
        if not BINARY.is_file():
            raise RuntimeError("build fullmoon-dst before executing extractor tests")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dst-extraction-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def extract(self, data: bytes, path="test.lua"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        result = subprocess.run([str(BINARY), "test-v1", path, str(target)], capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        facts = json.loads(result.stdout)
        Draft202012Validator({"$ref": "#/$defs/facts", "$defs": SCHEMA["$defs"]}).validate(facts)
        self.assertEqual(result.returncode == 1, facts["coverage"]["status"] == "failed")
        anchors = {a["id"]: a for a in facts["anchors"]}
        for anchor in anchors.values():
            start, end = anchor["start"]["byte"], anchor["end"]["byte"]
            self.assertTrue(0 <= start <= end <= len(data))
            self.assertEqual(anchor["sha256"], sha256(data[start:end]).hexdigest())
            for key in ("start", "end"):
                byte = anchor[key]["byte"]
                prefix = data[:byte]
                self.assertEqual(anchor[key]["line"], prefix.count(b"\n") + 1)
                self.assertEqual(anchor[key]["column"], byte - prefix.rfind(b"\n"))
        ids = {s["id"] for s in facts["symbols"]}
        self.assertEqual(len(ids), len(facts["symbols"]))
        for symbol in facts["symbols"]:
            self.assertTrue(symbol["owner_id"] is None or symbol["owner_id"] in ids)
        for record in facts["records"]:
            self.assertIn(record["subject_symbol_id"], ids)
            self.assertIn(record["anchor_id"], anchors)
            for guard in record['guards']:
                self.assertIn(guard['anchor_id'], anchors)
            for key in ('field_symbol_id', 'target_symbol_id'):
                if key in record['data']:
                    self.assertIn(record['data'][key], ids)
            if 'resolution' in record['data']:
                resolution = record['data']['resolution']
                self.assertTrue(set(resolution['candidates']) <= ids)
                if resolution['state'] == 'resolved':
                    self.assertIn(resolution['symbol_id'], ids)
                    self.assertFalse(resolution['candidates'])
                else:
                    self.assertIsNone(resolution['symbol_id'])
                    self.assertTrue(resolution['reason'])
        for diagnostic in facts["coverage"]["diagnostics"]:
            self.assertTrue(diagnostic["anchor_id"] is None or diagnostic["anchor_id"] in anchors)
        return facts, anchors

class ExtractionTests(ExtractorAssertions, unittest.TestCase):
    def test_lf_and_crlf_unicode_half_open_ranges(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                source = newline.join(['-- 中文', 'local function echo(value, ...)',
                                       '    local label = "耐久" -- WARNING: 示例', '    return value', 'end', ''])
                data = source.encode("utf-8")
                facts, anchors = self.extract(data)
                echo = next(s for s in facts["symbols"] if s["name"] == "echo")
                anchor = anchors[echo["anchor_id"]]
                self.assertEqual(data[anchor["start"]["byte"]:anchor["end"]["byte"]],
                                 source[source.index("local function"):source.rfind("end") + 3].encode("utf-8"))
                self.assertEqual(echo["parameters"], [{"name": "value", "kind": "named"}, {"name": "...", "kind": "vararg"}])
                warning = next(r for r in facts["records"] if r['kind']=='comment' and "WARNING" in r["data"]["text"])
                # Full Moon includes CR in a single-line comment token under CRLF;
                # retain that original byte rather than trim the evidence.
                self.assertEqual(warning["data"]["text"], "-- WARNING: 示例" + ("\r" if newline == "\r\n" else ""))
                self.assertEqual(warning["data"]["style"], "line")
                self.assertEqual(warning["subject_symbol_id"], echo["id"])
                # Byte column differs from Unicode character count on this line.
                self.assertEqual(anchors[warning["anchor_id"]]["start"]["column"], 28)

    def test_trivia_comments_and_code_shaped_strings_are_not_definitions(self):
        data = b'-- WARNING: file\nlocal text = "function Fake() end -- WARNING"\nlocal function real()\n --[[ WARNING: self.fake=1 ]]\nend\n-- EOF warning'
        facts, _ = self.extract(data)
        self.assertEqual({s["name"] for s in facts["symbols"]}, {"<chunk>", "real"})
        comments=[r for r in facts['records'] if r['kind']=='comment']
        self.assertEqual([r["data"]["style"] for r in comments], ["line", "block", "line"])
        self.assertEqual(len(comments), 3)

    def test_shadowing_repeated_class_and_block_scopes(self):
        data = b'''local C=Class(function(self) end)
function C:C(x) end
do local C={}; function C:Use() end end
local C=Class(function(self,inst) end)
function C:Use(y) end
do local function f() end end
do local function f() end end
'''
        facts, _ = self.extract(data)
        symbols = facts["symbols"]
        self.assertEqual(next(s for s in symbols if s["id"] == 'test.lua#C/method:C')["owner_id"], 'test.lua#module/class:C')
        shadowed = next(s for s in symbols if s["scope"] == "module/block:1/C")
        self.assertIsNone(shadowed["owner_id"])
        self.assertEqual(next(s for s in symbols if s["scope"] == "C@2" and s["kind"] == "method")["owner_id"], 'test.lua#module/class:C@2')
        self.assertEqual({s["scope"] for s in symbols if s["name"] == "f"}, {"module/block:2", "module/block:3"})
        self.assertTrue(any(d["code"] == "repeated-definition" for d in facts["coverage"]["diagnostics"]))

    def test_assignment_anonymous_scopes_and_shadowed_class_function(self):
        data = b'''local Class=function(fn) return fn end
local C=Class(function() end)
local fn=function() return function() return function(x) end end end
fn=function(y) end
'''
        facts, _ = self.extract(data)
        self.assertFalse(any(s["kind"] == "class" for s in facts["symbols"]))
        self.assertTrue(any(s["id"] == "test.lua#module/fn/anon:1/function:anon:1" for s in facts["symbols"]))
        self.assertTrue(any(s["id"] == "test.lua#module/function:fn@2" for s in facts["symbols"]))

    def test_uncalled_closure_and_branch_writes_do_not_choose_runtime_class(self):
        for tail in [b'local function reset() C=Class(function() end) end', b'if flag then C=Class(function() end) end']:
            facts, _ = self.extract(b'local C=Class(function() end)\n' + tail + b'\nfunction C:Use() end')
            self.assertIsNone(next(s for s in facts["symbols"] if s["name"] == "Use")["owner_id"])

    def test_loop_index_shadowing_survives_function_in_loop_header(self):
        data = b'local C=Class(function() end)\nfor C in make(function() end) do function C:Use() end end'
        facts, _ = self.extract(data)
        self.assertIsNone(next(s for s in facts["symbols"] if s["name"] == "Use")["owner_id"])

    def test_guarded_warning_preserves_exact_source_and_condition(self):
        data = b'if flag then\n -- WARNING: conditional\n local value=1\nend\n'
        facts, anchors = self.extract(data)
        comment=next(r for r in facts['records'] if r['kind']=='comment')
        self.assertEqual([(g['expression'],g['branch']) for g in comment['guards']], [('flag','then')])
        anchor = anchors[comment["anchor_id"]]
        self.assertEqual(data[anchor["start"]["byte"]:anchor["end"]["byte"]], b'-- WARNING: conditional')
        self.assertEqual(facts["coverage"]["status"], "complete")
        self.assertFalse(facts["coverage"]["truncated"])

    def test_instance_callback_assignment_keeps_lexical_owner(self):
        facts, _ = self.extract(b'local C=Class(function(self) end)\nfunction C:Setup() self.callback=function(src) end end')
        callback = next(s for s in facts["symbols"] if s["name"] == 'self.callback')
        self.assertEqual(callback["kind"], 'function')
        self.assertEqual(callback["scope"], 'C/Setup')
        self.assertEqual(callback["owner_id"], 'test.lua#C/method:Setup')
        self.assertFalse(any(s['id'] == 'test.lua#C/method:callback' for s in facts['symbols']))

    def test_failure_diagnostics_without_repaired_evidence(self):
        for data, code in [(b'local function broken(value\nreturn value\n', 'syntax-error'),
                           (b'-- copyright \xa9\nreturn 1', 'non-utf8-source'),
                           (b'\x1bLua\x51\x00', 'lua-bytecode')]:
            with self.subTest(code=code):
                facts, _ = self.extract(data)
                self.assertFalse(facts["symbols"] or facts["records"] or facts["anchors"])
                diagnostic = facts["coverage"]["diagnostics"][0]
                self.assertEqual(diagnostic["code"], code)
                if code == 'syntax-error':
                    self.assertIn('test.lua:2:1', diagnostic["message"])
                    self.assertIn('context: return value', diagnostic["message"])

    def test_manifest_preserves_input_gaps_and_excludes_po(self):
        root = self.root / 'input'
        root.mkdir()
        inputs = {'ok.lua': b'local function ok() end', 'bad.lua': b'local function broken(',
                  'encoding.lua': b'-- \xa9', 'binary.lua': b'\x1bLua\x51'}
        for path, data in inputs.items():
            (root / path).write_bytes(data)
        (root / 'translation.po').write_bytes(b'not Lua')
        output = self.root / 'output'
        report = wrapper.run_extraction(root, list(inputs), output, 'test-v1',
                                        {'scheme': 'fixture', 'value': 'test-v1'}, 'fixture', BINARY)
        manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
        Draft202012Validator({'$ref': '#/$defs/manifest', '$defs': SCHEMA['$defs']}).validate(manifest)
        self.assertEqual({f['path'] for f in manifest['sources'][0]['files']}, {'ok.lua', 'bad.lua'})
        self.assertEqual(report['failed_files'], 3)
        self.assertEqual(report['input_scope']['excluded_by_design'], ['*.po'])
        for path, data in inputs.items():
            self.assertEqual((root / path).read_bytes(), data)
        with self.assertRaises(ValueError):
            wrapper.run_extraction(root, list(inputs), output, 'test-v1', {}, 'fixture', BINARY)
        with self.assertRaises(ValueError):
            wrapper.relative_path('../outside.lua')
        with self.assertRaises(ValueError):
            wrapper.relative_path('translation.po')


if __name__ == '__main__':
    unittest.main()
