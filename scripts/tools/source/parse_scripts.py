"""Extract selected Lua structural facts; preserve unsupported inputs in a separate coverage report."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dst_paths import knowledge_root, source_root, catalog_root
import tomllib

SCRIPTS = Path(__file__).resolve().parents[2]
REPO = SCRIPTS.parent
TOOL = SCRIPTS / "fullmoon-dst"
VERSION = tomllib.loads((TOOL / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]


def relative_path(value: str) -> str:
    parts = value.split("/")
    if not value.endswith(".lua") or any(p in ("", ".", "..") for p in parts) or any(c in value for c in "\\:"):
        raise ValueError(f"expected source-relative .lua path: {value}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_extraction(root: Path, paths: list[str], output: Path, snapshot: str,
                   revision: dict, source_kind: str, binary: Path, *, full_scan: bool = False) -> dict:
    root, output = root.resolve(), output.resolve()
    if not root.is_dir() or not binary.is_file():
        raise ValueError("source root or extractor missing; build fullmoon-dst first")
    # Generation must never write through source/fork paths or overwrite an old selection.
    forbidden = [root, REPO / "scripts/vendor"]
    if root.name == "scripts" and root.parent.parent.name == "raw":
        forbidden.extend([root.parent.parent, root.parent.parent.parent / "wiki"])
    if any(output.is_relative_to(p.resolve()) or p.resolve().is_relative_to(output) for p in forbidden):
        raise ValueError("output overlaps source or maintained inputs")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory is nonempty; choose a new directory to retain earlier selections")
    normalized = sorted({relative_path(path) for path in paths})
    if not normalized:
        raise ValueError("no Lua inputs selected")
    results, files = [], []
    for path in normalized:
        source_path = (root / path).resolve()
        if not source_path.is_relative_to(root):
            raise ValueError(f"source symlink escapes source root: {path}")
        item = {"path": path, "sha256": None, "bytes": None, "input_kind": "unreadable"}
        try:
            data = source_path.read_bytes()
        except OSError as error:
            facts = {"format_version": "1.0.0", "kind": "facts", "snapshot_id": snapshot,
                     "primary_file": path, "coverage": {"status": "failed", "selection": {
                         "symbols": [], "record_kinds": [], "description": "Unreadable selected input."},
                         "truncated": False, "diagnostics": [{"code": "input-access", "severity": "error",
                             "message": str(error), "anchor_id": None}]}, "anchors": [], "symbols": [], "records": []}
        else:
            item.update(sha256=sha256(data).hexdigest(), bytes=len(data), input_kind="utf8-source")
            if data.startswith(b"\x1bLua"):
                item["input_kind"] = "lua-bytecode"
            else:
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    item["input_kind"] = "non-utf8-source"
            if item["input_kind"] == "utf8-source":
                files.append({"path": path, "sha256": item["sha256"], "encoding": "utf-8"})
            run = subprocess.run([str(binary.resolve()), snapshot, path, str(source_path)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=120)
            if run.returncode not in (0, 1):
                raise RuntimeError(f"extractor process failed for {path}: {run.stderr}")
            facts = json.loads(run.stdout)
            if (facts["primary_file"] != path or facts["snapshot_id"] != snapshot
                    or (facts["coverage"]["status"] == "failed") != (run.returncode == 1)):
                raise RuntimeError(f"extractor output/exit status mismatch: {path}")
            if source_path.read_bytes() != data:
                raise RuntimeError(f"input changed during extraction: {path}")
        item.update(status=facts["coverage"]["status"], truncated=facts["coverage"]["truncated"],
                    symbols=len(facts["symbols"]), records=len(facts["records"]),
                    diagnostics=facts["coverage"]["diagnostics"])
        write_json(output / "facts" / (path + ".json"), facts)
        results.append(item)
    manifest = {"format_version": "1.0.0", "kind": "manifest", "snapshot": {"id": snapshot, "version": revision},
                "producer": {"name": "fullmoon-dst", "version": VERSION, "mode": "extracted", "dialect": "lua51",
                             "parser": {"name": "full_moon", "version": "3.0.0"}},
                "sources": [{"id": "dst", "kind": source_kind, "root_hint": None, "revision": revision, "files": files}]}
    report = {"report_version": 1, "kind": "extraction-coverage-report", "snapshot_id": snapshot,
              "manifest": "manifest.json", "binary_sha256": sha256(binary.read_bytes()).hexdigest(),
              "input_scope": {"selected_paths": normalized, "include": ["*.lua"], "excluded_by_design": ["*.po"], "selection_mode": "full-scan" if full_scan else "explicit"},
              "stage": "explicit-syntax-and-finite-resolution", "runtime_tested": False,
              "selected_files": len(results), "manifest_utf8_files": len(files),
              "failed_files": sum(r["status"] == "failed" for r in results), "results": results}
    write_json(output / "manifest.json", manifest)
    write_json(output / "coverage-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="source-relative .lua paths; no implicit full scan")
    parser.add_argument("--catalog", type=Path, help="select W02 cases without changing their manual provenance")
    parser.add_argument("--all", action="store_true", help="explicit full .lua selection, .po excluded")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--knowledge-root", type=Path)
    parser.add_argument("--snapshot-id")
    parser.add_argument("--version")
    parser.add_argument("--version-scheme", choices=["steam-buildid", "fixture"], default="steam-buildid")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--binary", type=Path, default=TOOL / "target/debug" / ("fullmoon-dst.exe" if sys.platform == "win32" else "fullmoon-dst"))
    args = parser.parse_args()
    if args.catalog:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        if catalog.get("baseline_version") != 1 or catalog.get("contract_version") != "1.0.0":
            parser.error("unsupported baseline or contract version")
        if args.paths or args.version or args.snapshot_id or args.all:
            parser.error("catalog supplies selection/revision; do not combine with paths/version/snapshot-id")
        root = catalog_root(catalog, args.source_root, args.knowledge_root)
        revision = catalog["revision"]
        paths = [c["path"] for c in catalog["cases"]]
    else:
        root = source_root(args.source_root, args.knowledge_root)
        version = args.version
        if version is None:
            if args.source_root or args.version_scheme != "steam-buildid":
                parser.error("custom source root requires an explicit --version")
            version = (root.parent / "BUILD.txt").read_text(encoding="utf-8").strip()
        revision = {"scheme": args.version_scheme, "value": version}
        if args.all and args.paths:
            parser.error("--all cannot be combined with paths")
        paths = sorted(p.relative_to(root).as_posix() for p in root.rglob('*.lua')) if args.all else args.paths
    snapshot = args.snapshot_id or ("dst-steam-" + revision["value"] if revision["scheme"] == "steam-buildid" else revision["value"])
    if not snapshot or any(c in snapshot for c in '/\\:<>"|?*') or snapshot in (".", ".."):
        parser.error("snapshot-id must be a nonempty directory-safe name")
    output = args.output or knowledge_root(args.knowledge_root) / "output" / snapshot
    report = run_extraction(root, paths, output, snapshot, revision,
                            "fixture" if revision["scheme"] == "fixture" else "game-source", args.binary, full_scan=args.all)
    statuses = {status: sum(r['status'] == status for r in report['results']) for status in ('complete','partial','failed')}
    print(f"Selected {report['selected_files']} Lua files; statuses={statuses}. Output: {output}")
    print("Excluded by design: .po. Coverage report includes unsupported/unreadable inputs; manifest lists UTF-8 source only.")
    return 1 if report["failed_files"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
