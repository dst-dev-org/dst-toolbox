"""Check W02 baseline evidence, and optionally compare W03 facts with it."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dst_paths import knowledge_root, source_root, catalog_root

from validate_examples import ContractError, position, require, safe_path, unique


SCRIPTS = Path(__file__).resolve().parents[2]
REPO = SCRIPTS.parent


def inside(root, relative):
    safe_path(relative)
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), "path escapes source root")
    return path


def matches(actual, expected):
    """Expected dictionaries select facets; expected lists specify exact order."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            matches(a, e) for a, e in zip(actual, expected))
    return type(actual) is type(expected) and actual == expected


def validate_anchor(anchor, data):
    start, end = anchor["start"]["byte"], anchor["end"]["byte"]
    require(0 <= start < end <= len(data), "invalid evidence byte range")
    require(position(data, start) == anchor["start"] and position(data, end) == anchor["end"],
            "evidence coordinates differ")
    require(sha256(data[start:end]).hexdigest() == anchor["sha256"], "evidence hash differs")


def validate_catalog(catalog, source_root):
    require(catalog["baseline_version"] == 1 and catalog["contract_version"] == "1.0.0",
            "unsupported baseline or contract version")
    require(catalog["mode"] == "manual-expectations" and catalog["parser_executed"] is False,
            "W02 expectations must not claim extraction")
    require(catalog["comparison"] == "required-subset-plus-forbidden", "unsupported comparison")
    cases = {case["path"]: case for case in catalog["cases"]}
    require(len(cases) == len(catalog["cases"]) and bool(cases), "duplicate or empty cases")
    if catalog["revision"]["scheme"] == "steam-buildid":
        require((source_root.parent / "BUILD.txt").read_text(encoding="utf-8").strip()
                == catalog["revision"]["value"], "baseline BUILD.txt differs")
    data_by_path = {}
    for path, case in cases.items():
        data = inside(source_root, path).read_bytes()
        data.decode("utf-8")
        require(sha256(data).hexdigest() == case["sha256"], f"baseline source changed: {path}")
        require(case["expected_status"] in ("complete", "partial-or-complete", "failed"),
                "unsupported coverage expectation")
        unique(case["checks"], "check")
        for check in case["checks"]:
            require(check["collection"] in ("symbols", "records") and bool(check["match"]),
                    "unsupported positive check")
        for check in case["forbidden"]:
            require(check["collection"] in ("symbols", "records") and bool(check["match"]),
                    "unsupported negative check")
        for review in case["semantic_reviews"]:
            require(review["state"] == "source-reviewed" and review["runtime_tested"] is False
                    and bool(review["claim"]) and bool(review["evidence"]) and bool(review["remaining"]),
                    "invalid manual semantic benchmark")
        data_by_path[path] = data
    anchors = unique(catalog["anchors"], "baseline anchor")
    for anchor in anchors.values():
        require(anchor["path"] in data_by_path, "anchor outside baseline files")
        validate_anchor(anchor, data_by_path[anchor["path"]])
    for case in cases.values():
        for check in case["checks"]:
            require(check["anchor_id"] in anchors, "missing check anchor")
            require(anchors[check["anchor_id"]]["path"] == case["path"], "check source differs")
        for aid in case.get("coordinate_probes", []):
            require(aid in anchors and anchors[aid]["path"] == case["path"], "missing coordinate probe")
        for review in case["semantic_reviews"]:
            for evidence in review["evidence"]:
                require(evidence["anchor_id"] in anchors and bool(evidence["role"]), "missing review evidence")
    return anchors


def check_facts(case, facts, expected_anchors, source_root, schema):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ContractError("facts comparison requires scripts/requirements.txt") from exc
    fact_schema = {"$ref": "#/$defs/facts", "$defs": schema["$defs"]}
    errors = list(Draft202012Validator(fact_schema).iter_errors(facts))
    require(not errors, "facts schema: " + (errors[0].message if errors else ""))
    require(facts["primary_file"] == case["path"], "facts source differs")
    allowed = ("partial", "complete") if case["expected_status"] == "partial-or-complete" else (case["expected_status"],)
    require(facts["coverage"]["status"] in allowed and facts["coverage"]["truncated"] is False,
            "coverage status differs or facts are truncated")
    if case.get("require_error_diagnostic"):
        require(any(d["severity"] == "error" for d in facts["coverage"]["diagnostics"]),
                "failed parse must report an error diagnostic")
    if case.get("empty_facts"):
        require(not facts["symbols"] and not facts["records"] and not facts["anchors"],
                "failed parse must not provide valid facts or evidence")
    anchors = unique(facts["anchors"], "output anchor")
    symbols = unique(facts["symbols"], "output symbol")
    unique(facts["records"], "output record")
    data = inside(source_root, case["path"]).read_bytes()
    for anchor in anchors.values():
        require(anchor["source_id"] == "dst" and anchor["path"] == case["path"],
                "output anchor source differs")
        validate_anchor(anchor, data)
    require(set(facts["coverage"]["selection"]["symbols"]) <= symbols.keys(), "coverage symbol missing")
    for collection in (facts["symbols"], facts["records"]):
        for item in collection:
            require(item["anchor_id"] in anchors, "output evidence missing")
    for symbol in symbols.values():
        require(symbol["owner_id"] is None or symbol["owner_id"] in symbols, "output owner missing")
        expected_id = f"{case['path']}#{symbol['scope']}/{symbol['kind']}:{symbol['name']}"
        require(symbol["id"] == expected_id or (symbol["id"].startswith(expected_id + "@")
                and symbol["id"][len(expected_id) + 1:].isdigit()), "output symbol ID differs")
    if facts["coverage"]["status"] == "complete":
        require(not any(d["severity"] == "error" for d in facts["coverage"]["diagnostics"]),
                "complete coverage cannot include an error")
    for diagnostic in facts["coverage"]["diagnostics"]:
        require(diagnostic["anchor_id"] is None or diagnostic["anchor_id"] in anchors,
                "output diagnostic evidence missing")
    for record in facts["records"]:
        require(record["subject_symbol_id"] in symbols, "output subject missing")
        require(record["subject_symbol_id"] in facts["coverage"]["selection"]["symbols"]
                and record["kind"] in facts["coverage"]["selection"]["record_kinds"],
                "record outside declared selection")
        for guard in record["guards"]:
            require(guard["anchor_id"] in anchors, "output guard evidence missing")
        resolution = record["data"].get("resolution")
        for key in ("field_symbol_id", "target_symbol_id"):
            require(key not in record["data"] or record["data"][key] in symbols,
                    "output property or alias symbol missing")
        if resolution:
            require(set(resolution["candidates"]) <= symbols.keys(), "resolution candidate missing")
            if resolution["state"] == "resolved":
                require(resolution["symbol_id"] in symbols and not resolution["candidates"],
                        "invalid resolved target")
            elif resolution["state"] == "unresolved":
                require(resolution["symbol_id"] is None and not resolution["candidates"]
                        and bool(resolution["reason"]), "unresolved target needs a reason")
            else:
                require(resolution["symbol_id"] is None and len(resolution["candidates"]) >= 2
                        and bool(resolution["reason"]), "ambiguous target needs candidates and a reason")
    for check in case["checks"]:
        expected = expected_anchors[check["anchor_id"]]
        hits = [item for item in facts[check["collection"]] if matches(item, check["match"])]
        require(any(anchors[item["anchor_id"]]["start"]["byte"] <= expected["start"]["byte"]
                    and anchors[item["anchor_id"]]["end"]["byte"] >= expected["end"]["byte"] for item in hits),
                f"missing expected fact or evidence: {case['path']}:{check['id']}")
    for check in case["forbidden"]:
        require(not any(matches(item, check["match"]) for item in facts[check["collection"]]),
                f"forbidden fact: {case['path']}:{check['match']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogs", nargs="*", type=Path)
    parser.add_argument("--source-root", type=Path, help="Source root for a single catalog")
    parser.add_argument("--facts-root", type=Path, help="W03 facts directory containing <source-path>.json")
    parser.add_argument("--knowledge-root", type=Path)
    args = parser.parse_args()
    paths = args.catalogs or sorted((SCRIPTS / "tests/fixtures/baselines").glob("*.json"))
    require(bool(paths), "no baseline catalogs")
    require(args.source_root is None or len(paths) == 1, "source override requires one catalog")
    schema = json.loads((SCRIPTS / "schemas/contract.schema.json").read_text(encoding="utf-8"))
    for path in paths:
        catalog = json.loads(path.read_text(encoding="utf-8"))
        source_root = catalog_root(catalog, args.source_root, args.knowledge_root)
        anchors = validate_catalog(catalog, source_root)
        for case in catalog["cases"]:
            if args.facts_root:
                facts = json.loads(inside(args.facts_root, case["path"] + ".json").read_text(encoding="utf-8"))
                require(facts["snapshot_id"] == (
                    "dst-steam-" + catalog["revision"]["value"] if catalog["revision"]["scheme"] == "steam-buildid"
                    else catalog["revision"]["value"]), "facts snapshot differs")
                check_facts(case, facts, anchors, source_root, schema)
        count = sum(len(case["checks"]) for case in catalog["cases"])
        print(f"PASS {path.name}: {len(catalog['cases'])} sources, {count} required facts; evidence bytes checked")
    print("Facts comparison: " + ("passed" if args.facts_root else "not performed; W03 extractor not executed"))
    print("Semantic text and game runtime are not verified by this checker.")


if __name__ == "__main__":
    try:
        main()
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
