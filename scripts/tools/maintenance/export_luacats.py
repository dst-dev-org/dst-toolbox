"""Export one component's reviewed LuaCATS; reject stale or conflicting input."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

SCRIPTS = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "dst_contract", SCRIPTS / "tools/verify/validate_examples.py")
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle(facts_path, manifest_path, reviews_path, source_root, record_root=None):
    """Use the contract's existing semantic/byte checks, without saving a bundle."""
    facts, manifest, reviews = map(read_json, (facts_path, manifest_path, reviews_path))
    contract.require(facts["format_version"] == "1.0.0", "unsupported facts version")
    contract.require(facts["coverage"]["status"] != "failed"
                     and not facts["coverage"]["truncated"], "failed/truncated facts")
    bundle = {
        "format_version": "1.0.0", "kind": "example-bundle",
        "purpose": "In-memory projection validation; not a manual reference fixture.",
        "manifest": manifest, "facts": facts, "reviews": reviews,
        "candidates": {"format_version": "1.0.0", "kind": "candidates",
                       "source_id": None, "target_file": facts["primary_file"],
                       "anchors": [], "claims": []},
        "projection_checks": {"index_symbol_ids": [], "luacats_review_ids": [],
                              "wiki_review_ids": [], "excluded_candidate_ids": []},
    }
    bundle["resolved"] = contract.resolve(bundle)
    contract.validate_bundle(bundle, {"dst": source_root}, record_root=record_root)
    contract.require(not bundle["resolved"]["conflicts"], "conflicting reviews; no export")
    contract.require(all(r["status"] != "review-needed"
                         for r in bundle["resolved"]["records"]), "stale review; no export")
    return bundle


def render(bundle, class_name, authors=""):
    contract.require(re.fullmatch(r"[A-Za-z_]\w*", class_name), "invalid class name")
    facts = bundle["facts"]
    classes = [s for s in facts["symbols"] if s["kind"] == "class"]
    contract.require(len(classes) == 1, "export supports one explicit component class")
    owner = classes[0]
    # A source Class base needs its own model mapping; never silently discard it.
    contract.require(owner["base_expression"] in (None, "nil"),
                     "real source inheritance needs an explicit model; no export")
    rows = {(r["target"]["symbol_id"], r["target"]["facet"]): r
            for r in bundle["resolved"]["records"] if r["status"] == "verified"}
    used, missing = set(), []

    def value(symbol, facet):
        row = rows.get((symbol["id"], facet))
        if row is None:
            missing.append({"symbol_id": symbol["id"], "facet": facet})
            return None
        used.update(row["selected_review_ids"])
        return row["value"]

    credits = ", ".join(dict.fromkeys([name.strip() for name in authors.split(",") if name.strip()]
                                     + ["DST Wiki contributors"]))
    lines = ["---@meta", "", "--- Generated from source-reviewed input; no game runtime validation.",
             f"--- Snapshot: {bundle['manifest']['snapshot']['id']}",
             f"---author: {credits}", "",
             f"---@class {class_name}"]
    symbols = [s for s in facts["symbols"] if s["owner_id"] == owner["id"]]
    for symbol in symbols:
        if symbol["kind"] == "field":
            field = value(symbol, "field:type")
            if field:
                lines.append(f"---@field {symbol['name']} {field['expression']}")
    lines.extend(["local component = {}", ""])
    for symbol in symbols:
        if symbol["kind"] != "method":
            continue
        prior_used = set(used)
        contract.require(symbol["calling"] == "colon", "only colon component methods supported")
        params, annotations, complete = [], [], True
        for param in symbol["parameters"]:
            name = param["name"]
            typ = value(symbol, f"param:{name}:type")
            optional = value(symbol, f"param:{name}:optional")
            params.append(name)
            if typ is None or optional is None:
                complete = False
                continue
            expression = typ["expression"]
            # LuaCATS '?' admits nil too; required-but-nilable parameters stay explicit.
            mark = "?" if optional["accepts_omitted"] and optional["accepts_nil"] else ""
            contract.require(not optional["accepts_omitted"] or optional["accepts_nil"],
                             "omitted-only optionality cannot be represented by LuaCATS")
            if optional["accepts_nil"] and not mark and "nil" not in expression.split("|"):
                expression = f"({expression})|nil"
            annotations.append(f"---@param {name}{mark} {expression}")
        returns = value(symbol, "returns")
        if returns is None or not complete:
            used = prior_used
            continue  # Do not emit a permissive fake signature for unknown contracts.
        summary = rows.get((symbol["id"], "summary"))
        if summary:
            used.update(summary["selected_review_ids"])
            lines.append("--- " + summary["value"]["text"].replace("\n", " "))
        lines.extend(annotations)
        types = [slot["type"] for slot in returns["slots"]]
        # Fall-through means no values; only the first explicit slot gets nil here.
        contract.require(not returns["can_fall_through"] or len(types) <= 1,
                         "multi-return fall-through needs explicit modeling")
        if types and returns["can_fall_through"] and "nil" not in types[0].split("|"):
            types[0] = f"({types[0]})|nil"
        if returns["variadic"] is not None:
            raise contract.ContractError("variadic returns not supported by this exporter")
        if types:
            lines.append("---@return " + ", ".join(types))
        lines.extend([f"function component:{symbol['name']}({', '.join(params)}) end", ""])
    report = {
        "report_version": 1, "snapshot_id": facts["snapshot_id"],
        "target_file": facts["primary_file"], "class_name": class_name,
        "input_sha256": bundle["resolved"]["input_sha256"],
        "coverage": facts["coverage"], "selected_review_ids": sorted(used),
        "missing_facets": missing,
        "unresolved": [r for r in bundle["resolved"]["records"] if r["status"] != "verified"],
        "runtime_tested": False,
    }
    return "\n".join(lines), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Review source manifest, containing all evidence files")
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--record-root", type=Path, help="Explicit root for runtime evidence, if present")
    parser.add_argument("--class-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotation", type=Path, help="Existing annotation, to preserve author credits")
    args = parser.parse_args()
    # New output only; applying a reviewed export to the independent fork is explicit.
    contract.require(not args.output.exists(), "output already exists; choose a new directory")
    bundle = load_bundle(args.facts, args.manifest, args.reviews, args.source_root, args.record_root)
    authors = ""
    if args.annotation:
        authors = ", ".join(sorted({name.strip() for credit in re.findall(
            r"^---author:\s*(.+)$", args.annotation.read_text(encoding="utf-8"), re.M)
            for name in credit.split(",") if name.strip() and name.strip() != "DST Wiki contributors"}))
    text, report = render(bundle, args.class_name, authors)
    args.output.mkdir(parents=True)
    name = Path(bundle["facts"]["primary_file"]).stem
    (args.output / f"{name}.lua").write_text(text, encoding="utf-8", newline="\n")
    (args.output / "resolved.json").write_text(
        json.dumps(bundle["resolved"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "projection-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {name}: {len(report['selected_review_ids'])} reviews; "
          f"{len(report['missing_facets'])} missing facets; runtime not tested")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
