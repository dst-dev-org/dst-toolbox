"""Run reviewed component LuaLS probes; no download or game execution."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[2]
EXPECTED = {
    "finiteuses": [(2, "param-type-mismatch"), (3, "param-type-mismatch"), (4, "undefined-field")],
    "equippable": [(2, "assign-type-mismatch"), (3, "assign-type-mismatch"),
                   (4, "param-type-mismatch"), (5, "param-type-mismatch"),
                   (6, "undefined-field"), (7, "need-check-nil")],
}


def assess(diagnostics, component):
    """Require every deliberate diagnostic and reject extra/positive/declaration errors."""
    positive, negative, declaration = [], [], []
    for uri, items in diagnostics.items():
        if uri.endswith(f"/{component}-positive.lua"):
            positive.extend(items)
        elif uri.endswith(f"/{component}-negative.lua"):
            negative.extend(items)
        elif uri.endswith(f"/{component}.lua"):
            declaration.extend(items)
        elif items:
            raise ValueError(f"unexpected diagnostic source: {uri}")
    expected = EXPECTED[component]
    actual = sorted((d["range"]["start"]["line"], d["code"]) for d in negative)
    return {"declaration_diagnostics": declaration, "positive_diagnostics": positive,
            "negative_expected": expected, "negative_actual": actual,
            "passed": not positive and not declaration and actual == expected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--luals", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True,
                        help="Maintained lsp-dst scripts root, containing the reviewed declaration")
    parser.add_argument("--component", choices=sorted(EXPECTED), default="finiteuses")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("output exists; use a new directory")
    library = args.library.resolve()
    component = args.component
    annotation = library / f"components/members/{component}.lua"
    if not annotation.is_file() or not args.luals.is_file():
        raise ValueError(f"LuaLS binary or {component} annotation is missing")
    fixtures = SCRIPTS / "tests/fixtures/luacats"
    fixture_paths = [fixtures / f"{component}-{suffix}.lua" for suffix in ("positive", "negative")]
    if not all(p.is_file() for p in fixture_paths):
        raise ValueError("positive/negative fixtures are missing")
    version = subprocess.check_output([str(args.luals), "--version"], timeout=30).decode().strip()
    output = args.output.resolve()
    output.mkdir(parents=True)
    workspace = output / "workspace"
    workspace.mkdir()
    for path in fixture_paths:
        (workspace / path.name).write_bytes(path.read_bytes())
    (workspace / f"{component}.lua").write_bytes(annotation.read_bytes())
    config = output / "config.json"
    config.write_text(json.dumps({"runtime.version": "Lua 5.1", "workspace.checkThirdParty": False,
                                  "type.weakNilCheck": False,
                                  "diagnostics.neededFileStatus": {"need-check-nil": "Any!"},
                                  "workspace.library": [p.as_posix() for p in sorted(library.iterdir())
                                                        if p.name != "components"],
                                  "diagnostics.libraryFiles": "Disable"}), encoding="utf-8")
    diagnostics_path = output / "diagnostics.json"
    command = [str(args.luals.resolve()), f"--check={workspace.as_posix()}",
               f"--configpath={config.as_posix()}", "--check_format=json",
               f"--check_out_path={diagnostics_path.as_posix()}", f"--logpath={(output / 'log').as_posix()}"]
    result = subprocess.run(command, capture_output=True, timeout=60)
    (output / "cli.txt").write_bytes(result.stdout + result.stderr)
    if result.returncode not in (0, 1) or not diagnostics_path.is_file():
        raise ValueError("LuaLS did not produce a valid check report; inspect cli.txt")
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assessment = assess(diagnostics, component)
    report = {"report_version": 1, "component": component, "luals_version": version,
              "luals_sha256": sha256(args.luals.read_bytes()).hexdigest(),
              "runtime_target": "Lua 5.1", "annotation_sha256": sha256(annotation.read_bytes()).hexdigest(),
              "weak_nil_check": False,
              **assessment, "cli_exit_code": result.returncode,
              "config_sha256": sha256(config.read_bytes()).hexdigest(),
              "fixture_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in fixture_paths},
              "scope": f"{component} declaration/positive and negative use cases; full library diagnostics excluded",
              "runtime_tested": False}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if assessment["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
