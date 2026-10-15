"""Verify pinned parser readiness; this does not extract or compare W01 facts."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dst_paths import knowledge_root, source_root, catalog_root
import time
import tomllib


SCRIPTS = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SCRIPTS.parent
PARSER_ROOT = SCRIPTS / "fullmoon-dst"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--syntax-scan", action="store_true", help="scan all .lua files for syntax only")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--knowledge-root", type=Path)
    parser.add_argument("--binary", type=Path, default=PARSER_ROOT / "target/debug/examples" /
                        ("parser_probe.exe" if sys.platform == "win32" else "parser_probe"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    args.source_root = source_root(args.source_root, args.knowledge_root)
    if not args.binary.is_file() or not args.source_root.is_dir() or args.workers < 1:
        parser.error("build parser_probe first; source root must exist and workers must be positive")

    toolchain = tomllib.loads((PARSER_ROOT / "rust-toolchain.toml").read_text(encoding="utf-8"))
    manifest = tomllib.loads((PARSER_ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    dependency = manifest["dependencies"]["full_moon"]
    jobs = []
    if args.syntax_scan:
        jobs = [("snapshot", p, p.relative_to(args.source_root).as_posix(), None)
                for p in sorted(args.source_root.rglob("*.lua"))]
    else:
        for group, root, baseline in [
            ("fixtures", PROJECT_ROOT / "scripts/tests/fixtures/extraction", "fixtures.json"),
            ("pilots", args.source_root, "pilots.json"),
        ]:
            cases = json.loads((SCRIPTS / "tests/fixtures/baselines" / baseline).read_text(encoding="utf-8"))["cases"]
            for case in cases:
                jobs.append((group, root / case["path"], case["path"],
                             1 if group == "fixtures" and case["path"] == "invalid.lua" else 0))

    def inspect(job):
        group, path, relative, expected = job
        data = path.read_bytes()
        input_kind = "utf8-source"
        if data.startswith(b"\x1bLua"):
            input_kind = "lua-bytecode"
        else:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                input_kind = "non-utf8-source"
        command = [str(args.binary)] + (["--syntax-only"] if args.syntax_scan else []) + [str(path)]
        run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120)
        return {
            "group": group, "path": relative, "input_kind": input_kind,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "expected_exit_code": expected, "exit_code": run.returncode,
            "stdout": None if args.syntax_scan and run.returncode == 0 else run.stdout.strip(),
            "diagnostic": run.stderr.strip() or None,
        }

    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(inspect, jobs):
            results.append(result)
            if args.syntax_scan:
                if len(results) % 500 == 0:
                    print(f"Parsed {len(results)}/{len(jobs)}", flush=True)
            else:
                print(result["stdout"] or result["diagnostic"], flush=True)
    issues = [result for result in results if result["exit_code"] != 0]
    mismatches = [result for result in results
                  if result["expected_exit_code"] is not None
                  and result["exit_code"] != result["expected_exit_code"]]
    build_file = args.source_root.parent / "BUILD.txt"
    report = {
        "kind": "lua-dialect-syntax-scan" if args.syntax_scan else "parser-preparation-report",
        "toolchain": toolchain["toolchain"]["channel"],
        "parser": {"name": "full_moon", "version": dependency["version"].removeprefix("="),
                   "dialect": "lua51", "default_features": dependency.get("default-features", True)},
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "source_build": {"system": "steam-buildid", "value": build_file.read_text().strip()} if build_file.is_file() else None,
        "scope": "syntax only" if args.syntax_scan else "parse, original bytes and token ranges",
        "facts_compared": False, "runtime_tested": False,
        "file_count": len(results), "passed": len(results) - len(issues), "failed": len(issues),
        "expectation_mismatches": len(mismatches),
        "elapsed_seconds": round(time.monotonic() - started, 2), "results": results,
    }
    output = args.output or knowledge_root(args.knowledge_root) / "output/preparation" / (
        "lua-dialect-scan.json" if args.syntax_scan else "parser-probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {output}; parsed={report['passed']}, rejected={len(issues)}, expectation mismatches={len(mismatches)}")
    print("No fact-extraction, text semantics, LuaLS or game-runtime verification.")
    if args.syntax_scan:
        for result in issues:
            print(f"{result['path']}: {result['input_kind']}: {result['diagnostic']}")
        return 1 if issues else 0
    return 1 if mismatches else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
