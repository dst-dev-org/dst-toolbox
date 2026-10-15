"""Compare a selected extraction stage against an explicit projection of unchanged W02 baselines."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dst_paths import knowledge_root, source_root, catalog_root

from check_baselines import check_facts, validate_catalog
from validate_examples import ContractError, require

SCRIPTS = Path(__file__).resolve().parents[2]
REPO = SCRIPTS.parent


def stage1_case(original: dict) -> dict:
    case = deepcopy(original)
    aliases = {c["match"]["data"]["target_symbol_id"] for c in case["checks"]
               if c["match"].get("kind") == "method_alias"}
    case["checks"] = [c for c in case["checks"] if
                      (c["collection"] == "symbols" and c["match"]["kind"] != "field"
                       and c["match"]["id"] not in aliases) or c["match"].get("kind") == "comment"]
    if case["expected_status"] != "failed":
        case["expected_status"] = "partial-or-complete"
    return case


def stage2_case(original: dict) -> dict:
    case = deepcopy(original)
    case["checks"] = [c for c in case["checks"] if c["collection"] == "symbols"
                      or c["match"].get("kind") in {"assignment", "property_callback", "method_alias", "return", "comment"}]
    if case["expected_status"] != "failed":
        case["expected_status"] = "partial-or-complete"
    return case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--facts-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--stage", choices=["1", "2"], default="2")
    parser.add_argument("--knowledge-root", type=Path)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    root = catalog_root(catalog, args.source_root, args.knowledge_root)
    anchors = validate_catalog(catalog, root)
    schema = json.loads((SCRIPTS / "schemas/contract.schema.json").read_text(encoding="utf-8"))
    count = 0
    for original in catalog["cases"]:
        case = (stage1_case if args.stage == "1" else stage2_case)(original)
        facts = json.loads((args.facts_root / (case["path"] + ".json")).read_text(encoding="utf-8"))
        snapshot = ("dst-steam-" + catalog["revision"]["value"] if catalog["revision"]["scheme"] == "steam-buildid"
                    else catalog["revision"]["value"])
        require(facts["snapshot_id"] == snapshot, "snapshot mismatch")
        check_facts(case, facts, anchors, root, schema)
        count += len(case["checks"])
    print(f"PASS stage {args.stage}: {len(catalog['cases'])} files, {count}/{sum(len(c['checks']) for c in catalog['cases'])} selected baseline facts; all forbidden checks retained.")
    print("Calls/events/component/Prefab references are deferred; full W02 comparison and semantic/runtime validation have not passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ContractError, OSError, ValueError, KeyError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
