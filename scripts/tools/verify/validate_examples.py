"""Validate W01 reference bundles; does not parse Lua or prove review semantics."""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dst_paths import knowledge_root, source_root, catalog_root

SCRIPTS = Path(__file__).resolve().parents[2]
REPO = SCRIPTS.parent


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return sha256(data).hexdigest()


def input_hashes(bundle):
    return {key: digest(canonical(bundle[key]))
            for key in ("manifest", "facts", "candidates", "reviews")}


def unique(items, label):
    result = {}
    for item in items:
        require(item["id"] not in result, f"duplicate {label}: {item['id']}")
        result[item["id"]] = item
    return result


def safe_path(path):
    require(bool(path) and "\\" not in path and ":" not in path
            and not path.startswith("/") and all(p not in ("", ".", "..")
                                                    for p in path.split("/")),
            f"unsafe relative path: {path}")
    return PurePosixPath(path)


def position(data, offset):
    require(0 <= offset <= len(data), f"byte offset out of range: {offset}")
    prefix = data[:offset]
    # A token boundary must not split a UTF-8 codepoint.
    prefix.decode("utf-8")
    return {"byte": offset, "line": prefix.count(b"\n") + 1,
            "column": offset - prefix.rfind(b"\n")}


def target_key(target):
    return target["symbol_id"], target["facet"]


def known_value(value):
    if value["kind"] == "type":
        return value["expression"] is not None
    if value["kind"] == "optional":
        return value["accepts_omitted"] is not None and value["accepts_nil"] is not None
    if value["kind"] == "returns":
        return all(s["type"] is not None for s in value["slots"]) and value["can_fall_through"] != "unknown"
    return True


def valid_review(review, bundle, anchors, sources):
    return (review["state"] == "verified"
            and review["reviewed_snapshot_id"] == bundle["manifest"]["snapshot"]["id"]
            and review["reviewed_at"] is not None
            and bool(review["evidence"])
            and all(e["anchor_id"] in anchors
                    and e["expected_sha256"] == anchors[e["anchor_id"]]["sha256"]
                    for e in review["evidence"])
            and any(e["anchor_id"] in anchors
                    and sources[anchors[e["anchor_id"]]["source_id"]]["kind"] == "game-source"
                    and e["role"] != "external-annotation" for e in review["evidence"])
            and (review["verdict"] == "reject" or known_value(review["value"])))


def resolve(bundle):
    """Small deterministic reference merge, scoped to one W01 example bundle."""
    anchors = {a["id"]: a for k in ("facts", "candidates", "reviews")
               for a in bundle[k]["anchors"]}
    sources = {s["id"]: s for s in bundle["manifest"]["sources"]}
    groups = defaultdict(lambda: {"claims": [], "reviews": []})
    for claim in bundle["candidates"]["claims"]:
        groups[target_key(claim["target"])]["claims"].append(claim)
    for review in bundle["reviews"]["entries"]:
        groups[target_key(review["target"])]["reviews"].append(review)
    records, conflicts = [], []
    for key, group in sorted(groups.items()):
        target = {"symbol_id": key[0], "facet": key[1]}
        active = [r for r in group["reviews"] if valid_review(r, bundle, anchors, sources)]
        accepted = [r for r in active if r["verdict"] == "accept"]
        rejected = sorted({c for r in active if r["verdict"] == "reject" for c in r["candidate_ids"]})
        contradictory = bool(set(rejected) & {c for r in accepted for c in r["candidate_ids"]})
        values = {canonical(r["value"]) for r in accepted}
        conflict_ids, selected, value = [], [], None
        if len(values) > 1 or contradictory:
            status, note = "conflict", "Conflicting current verified reviews; no value selected."
            conflict_id = "conflict:" + digest(canonical(target))[:16]
            conflict_ids.append(conflict_id)
            conflicts.append({"id": conflict_id, "target": target,
                              "review_ids": sorted(r["id"] for r in active),
                              "candidate_ids": sorted(c["id"] for c in group["claims"]),
                              "reason": "Different accepted values or a candidate both accepted and rejected."})
        elif accepted:
            status, note = "verified", "Current source-reviewed value; runtime validation is separate."
            selected = sorted(r["id"] for r in accepted)
            value = accepted[0]["value"]
        elif any(r["state"] == "stale" or (r["state"] == "verified" and r not in active)
                 for r in group["reviews"]):
            status, note = "review-needed", "Stale evidence requires a new review."
        else:
            status, note = "unknown", "No current verified acceptance."
        records.append({"target": target, "status": status, "value": value,
                        "selected_review_ids": selected,
                        "candidate_ids": sorted(c["id"] for c in group["claims"]),
                        "rejected_candidate_ids": rejected, "conflict_ids": conflict_ids,
                        "note": note})
    return {"format_version": "1.0.0", "kind": "resolved",
            "snapshot_id": bundle["manifest"]["snapshot"]["id"],
            "input_sha256": input_hashes(bundle), "coverage": bundle["facts"]["coverage"],
            "records": records, "conflicts": conflicts}


def validate_bundle(bundle, roots=None, structure_only=False, record_root=None):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ContractError("Install scripts/requirements.txt in your Python environment.") from exc
    schema = json.loads((SCRIPTS / "schemas/contract.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(bundle), key=lambda e: str(e.path))
    require(not errors, "schema: " + (errors[0].message if errors else ""))
    require(bundle["kind"] == "example-bundle", "validator expects an example-bundle")
    def reject_floats(value):
        require(not isinstance(value, float), "v1 JSON numbers must be integers; Lua numeric expressions are strings")
        if isinstance(value, dict):
            for item in value.values():
                reject_floats(item)
        elif isinstance(value, list):
            for item in value:
                reject_floats(item)
    reject_floats(bundle)
    manifest, facts, candidates, reviews = (bundle[k] for k in ("manifest", "facts", "candidates", "reviews"))
    sources = unique(manifest["sources"], "source")
    anchors = unique([a for layer in (facts, candidates, reviews) for a in layer["anchors"]], "anchor")
    symbols = unique(facts["symbols"], "symbol")
    unique(facts["records"], "record")
    claims = unique(candidates["claims"], "claim")
    entries = unique(reviews["entries"], "review")
    require(facts["snapshot_id"] == manifest["snapshot"]["id"], "facts snapshot mismatch")
    require(facts["primary_file"] == candidates["target_file"] == reviews["target_file"], "target file mismatch")
    if candidates["source_id"] is None:
        require(not candidates["anchors"] and not candidates["claims"], "candidates without a source must be empty")
    else:
        require(candidates["source_id"] in sources, "candidate source missing")
        require(sources[candidates["source_id"]]["kind"] == "annotation-library", "candidate source is not annotation-library")
    if manifest["producer"]["mode"] == "extracted":
        require(manifest["producer"]["parser"] is not None, "extracted producer requires parser version")
    files, source_data, notices = {}, {}, []
    roots = roots or {}
    for source in sources.values():
        source_paths = set()
        for file in source["files"]:
            safe_path(file["path"])
            require(file["path"] not in source_paths, "duplicate source file")
            source_paths.add(file["path"])
            files[(source["id"], file["path"])] = file
        if structure_only:
            continue
        if source["kind"] == "game-source":
            require(source["revision"] == manifest["snapshot"]["version"], "game revision mismatch")
        root = roots.get(source["id"])
        if root is None:
            require(source["kind"] != "game-source", f"missing game source root: {source['id']}")
            notices.append(f"external source not checked locally: {source['id']}")
            continue
        root = Path(root).resolve()
        if source["kind"] == "game-source":
            if source["revision"]["scheme"] == "steam-buildid":
                build_file = root.parent / "BUILD.txt"
                require(build_file.is_file(), f"missing {build_file}")
                require(build_file.read_text(encoding="utf-8").strip() == source["revision"]["value"], "BUILD.txt mismatch")
        for file in source["files"]:
            path = (root / file["path"]).resolve()
            require(path.is_relative_to(root), f"source path escapes root: {path}")
            require(path.is_file(), f"missing source file: {path}")
            data = path.read_bytes()
            data.decode("utf-8")
            require(digest(data) == file["sha256"], f"source file hash mismatch: {path}")
            source_data[(source["id"], file["path"])] = data
    for anchor in anchors.values():
        safe_path(anchor["path"])
        key = anchor["source_id"], anchor["path"]
        require(key in files, f"anchor file absent from manifest: {anchor['id']}")
        require(anchor["start"]["byte"] < anchor["end"]["byte"], f"empty/reversed anchor: {anchor['id']}")
        if key in source_data:
            data = source_data[key]
            for bound in ("start", "end"):
                require(position(data, anchor[bound]["byte"]) == anchor[bound], f"anchor coordinates mismatch: {anchor['id']}")
            require(digest(data[anchor["start"]["byte"]:anchor["end"]["byte"]]) == anchor["sha256"], f"anchor hash mismatch: {anchor['id']}")
    for anchor in facts["anchors"]:
        require(sources[anchor["source_id"]]["kind"] == "game-source", "facts anchor must use game-source")
    for anchor in candidates["anchors"]:
        require(anchor["source_id"] == candidates["source_id"], "candidate anchor source mismatch")
    for symbol in symbols.values():
        require(symbol["anchor_id"] in anchors, f"missing symbol anchor: {symbol['id']}")
        require(symbol["anchor_id"] in {a["id"] for a in facts["anchors"]}, "symbol must use a facts anchor")
        require(symbol["owner_id"] is None or symbol["owner_id"] in symbols, "missing symbol owner")
        expected = f"{anchors[symbol['anchor_id']]['path']}#{symbol['scope']}/{symbol['kind']}:{symbol['name']}"
        require(symbol["id"] == expected or (symbol["id"].startswith(expected + "@") and symbol["id"][len(expected)+1:].isdigit()), "symbol ID mismatch")
        params = [p["name"] for p in symbol["parameters"]]
        require(len(params) == len(set(params)), "duplicate parameter")
    coverage = facts["coverage"]
    require(set(coverage["selection"]["symbols"]) <= symbols.keys(), "coverage references missing symbol")
    if coverage["status"] == "complete":
        require(not coverage["truncated"] and not any(d["severity"] == "error" for d in coverage["diagnostics"]), "complete coverage with truncation/error")
    for diagnostic in coverage["diagnostics"]:
        require(diagnostic["anchor_id"] is None or diagnostic["anchor_id"] in anchors, "missing diagnostic anchor")
    for record in facts["records"]:
        require(record["subject_symbol_id"] in symbols and record["anchor_id"] in anchors, "missing record reference")
        require(record["subject_symbol_id"] in coverage["selection"]["symbols"], "record outside selected symbols")
        require(record["anchor_id"] in {a["id"] for a in facts["anchors"]}, "record must use a facts anchor")
        require(record["kind"] in coverage["selection"]["record_kinds"], "record outside selected kinds")
        for guard in record["guards"]:
            require(guard["anchor_id"] in anchors, "missing guard anchor")
        data = record["data"]
        for key in ("field_symbol_id", "target_symbol_id"):
            if key in data:
                require(data[key] in symbols, f"missing {key}")
        if "resolution" in data:
            resolution = data["resolution"]
            require(set(resolution["candidates"]) <= symbols.keys(), "missing resolution candidate")
            if resolution["state"] == "resolved":
                require(resolution["symbol_id"] in symbols and not resolution["candidates"], "invalid resolved target")
            else:
                require(resolution["symbol_id"] is None and bool(resolution["reason"]), "invalid unresolved target")
                require((len(resolution["candidates"]) >= 2) if resolution["state"] == "ambiguous" else not resolution["candidates"], "invalid resolution candidates")
    for item in list(claims.values()) + list(entries.values()):
        target, value = item["target"], item["value"]
        require(target["symbol_id"] in symbols, "missing target symbol")
        symbol, facet = symbols[target["symbol_id"]], target["facet"]
        if facet.startswith("param:"):
            require(facet.split(":")[1] in [p["name"] for p in symbol["parameters"]], "missing target parameter")
        if facet == "field:type":
            require(symbol["kind"] == "field", "field type on non-field")
        kind = ("type" if facet.endswith(":type") else "optional" if facet.endswith(":optional")
                else "returns" if facet == "returns" else "aliases" if facet == "aliases" else "text")
        require(value["kind"] == kind, "facet/value kind mismatch")
    for claim in claims.values():
        require(claim["anchor_id"] in {a["id"] for a in candidates["anchors"]}, "missing candidate anchor")
    for review in entries.values():
        require(set(review["candidate_ids"]) <= claims.keys(), "missing reviewed candidate")
        for candidate_id in review["candidate_ids"]:
            require(claims[candidate_id]["target"] == review["target"] and claims[candidate_id]["value"] == review["value"], "review rewrites candidate instead of separate correction")
        for evidence in review["evidence"]:
            require(evidence["anchor_id"] in anchors, "missing evidence anchor")
            anchor = anchors[evidence["anchor_id"]]
            external = sources[anchor["source_id"]]["kind"] == "annotation-library"
            require((evidence["role"] == "external-annotation") == external, "evidence role/source mismatch")
        if review["verdict"] == "reject":
            require(bool(review["candidate_ids"]), "reject requires candidate")
        if review["state"] == "verified":
            require(valid_review(review, bundle, anchors, sources), f"invalid verified review: {review['id']}")
        for run in review["runtime"]:
            safe_path(run["record_path"])
            require(review["state"] == "verified" and run["build"] == manifest["snapshot"]["version"], "runtime build/state mismatch")
            if not structure_only:
                require(record_root is not None, "runtime records require explicit record_root")
                require((Path(record_root) / run["record_path"]).is_file(), "runtime record file missing")
    require(bundle["resolved"] == resolve(bundle), "resolved cache differs from deterministic merge or input hashes")
    checks = bundle["projection_checks"]
    require(set(checks["index_symbol_ids"]) <= symbols.keys(), "index projection missing symbol")
    selected = {r for row in bundle["resolved"]["records"] for r in row["selected_review_ids"]}
    for key in ("luacats_review_ids", "wiki_review_ids"):
        require(set(checks[key]) <= selected, f"unverified projection: {key}")
    for review_id in checks["luacats_review_ids"]:
        require(entries[review_id]["value"]["kind"] in ("type", "optional", "returns"), "LuaCATS projection is not a type facet")
    require(set(checks["excluded_candidate_ids"]) <= claims.keys(), "excluded candidate missing")
    adopted = {c for r in selected for c in entries[r]["candidate_ids"]}
    require(not set(checks["excluded_candidate_ids"]) & adopted, "excluded candidate was adopted")
    if structure_only:
        notices.append("structure only: source files and byte anchors not checked")
    return notices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--source-root", action="append", default=[], metavar="ID=PATH")
    parser.add_argument("--structure-only", action="store_true")
    parser.add_argument("--knowledge-root", type=Path)
    parser.add_argument("--record-root", type=Path)
    args = parser.parse_args()
    roots = {}
    for mapping in args.source_root:
        require("=" in mapping, "--source-root requires ID=PATH")
        key, path = mapping.split("=", 1)
        roots[key] = Path(path)
    if not args.structure_only and "dst" not in roots:
        roots["dst"] = source_root(knowledge=args.knowledge_root)
    paths = args.paths or sorted((SCRIPTS / "tests/fixtures/bundles").glob("*.json"))
    require(bool(paths), "no example bundles found")
    for path in paths:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        notices = validate_bundle(bundle, roots, args.structure_only, args.record_root)
        print(f"PASS {path.name}: {len(bundle['facts']['symbols'])} symbols, {len(bundle['reviews']['entries'])} reviews")
        for notice in notices:
            print(f"  {notice}")


if __name__ == "__main__":
    try:
        main()
    except (ContractError, OSError, UnicodeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
