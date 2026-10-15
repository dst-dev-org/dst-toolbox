"""Prepare a runtime Prefab catalog for name lookup and Wiki coverage triage."""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import re

from inspect_prefab_names import find_entries
from verify_page_coverage import check_aliases, check_coverage, read_pages


def load_catalog(path, steam_build):
    text = path.read_text(encoding="utf-8-sig")
    catalog = json.loads(text.removeprefix("KLEI     1 "))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("entries"), list) or not catalog["entries"]:
        raise ValueError("expected a Prefab export with a nonempty entries list")
    snapshot = catalog.get("snapshot")
    if steam_build and snapshot and steam_build != snapshot:
        raise ValueError(f"Steam build {steam_build} conflicts with export snapshot {snapshot}")
    snapshot = steam_build or snapshot
    if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9]+", snapshot):
        raise ValueError("supply the verified Steam build with --steam-build")

    enabled_mods = catalog.get("enabled_mods", [])
    if not isinstance(enabled_mods, list) or not all(isinstance(name, str) for name in enabled_mods):
        raise ValueError("enabled_mods must be a list of strings")
    names = set()
    entries = []
    for row in catalog["entries"]:
        if not isinstance(row, dict) or row.get("status") != "confirmed":
            raise ValueError("expected confirmed registration objects")
        name = row.get("name")
        if not isinstance(name, str) or not name or name != name.strip() or name.casefold() in names:
            raise ValueError(f"invalid or duplicate registration name: {name!r}")
        names.add(name.casefold())
        for field in ("strings_name", "source_file", "mod_root", "kind"):
            if row.get(field) is not None and not isinstance(row[field], str):
                raise ValueError(f"{name}: {field} must be a string or null")
        if name == "MOD_dst-prefab-export" and "dst-prefab-export" in enabled_mods:
            continue
        entries.append(row)
    if not entries:
        raise ValueError("no registrations remain after removing the exporter marker")
    return {**catalog, "snapshot": snapshot, "entries": sorted(entries, key=lambda row: row["name"])}


def csv_text(header, rows):
    with StringIO(newline="") as output:
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)
        return output.getvalue()


def compare_names(entries, po_text):
    keys = {row["name"]: f'STRINGS.NAMES.{row["name"].upper()}' for row in entries}
    po = find_entries(po_text, set(keys.values()))
    counts = Counter()
    differences = []
    for row in entries:
        name = row["name"]
        runtime = row.get("strings_name") or ""
        candidates = po.get(keys[name], [])
        values = sorted({entry["zh_cn"] for entry in candidates})
        if len(values) > 1:
            state = "ambiguous_po"
        elif values and runtime:
            state = "match" if runtime == values[0] else "different"
        elif values or runtime:
            state = "po_only" if values else "runtime_only"
        else:
            state = "neither"
        counts[state] += 1
        if state not in ("match", "neither"):
            lines = "; ".join(f'{entry["start_line"]}-{entry["end_line"]}' for entry in candidates)
            differences.append((name, state, runtime, " | ".join(values), lines))
    return counts, differences


def compare_coverage(catalog, knowledge_root):
    records = read_pages(knowledge_root / "wiki")
    errors = [record["path"] for record in records if "error" in record]
    if errors:
        raise ValueError("cannot compare coverage with unreadable Wiki pages: " + ", ".join(errors[:5]))
    missing = {finding["name"] for finding in check_coverage(records, catalog, strict=False)}
    aliases = check_aliases(records, catalog)
    groups = defaultdict(list)
    for row in catalog["entries"]:
        groups[row.get("source_file") or "", row.get("mod_root") or ""].append(row)
    rows = []
    states = Counter()
    for (source, mod), entries in sorted(groups.items()):
        gaps = [row["name"] for row in entries if row["name"] in missing]
        matched = len(entries) - len(gaps)
        if source:
            states["partial" if matched and gaps else "matched" if matched else "unmatched"] += 1
        rows.append((source, mod, len(entries), matched, len(gaps), " ".join(gaps)))
    build_path = knowledge_root / "raw" / "current" / "BUILD.txt"
    wiki_build = build_path.read_text(encoding="utf-8-sig").strip() if build_path.is_file() else None
    summary = {
        "wiki_source_snapshot": wiki_build,
        "source_snapshot_match": catalog["snapshot"] == wiki_build if wiki_build else None,
        "wiki_pages_scanned": len(records),
        "unmatched_registrations": len(missing),
        "unmatched_by_kind": Counter(row.get("kind") or "unknown" for row in catalog["entries"]
                                     if row["name"] in missing),
        "file_groups": states,
        "alias_conflicts": [item for item in aliases if item["code"] == "alias-conflict"],
    }
    return summary, rows


def select_entries(entries, source_files, prefabs):
    missing = ((source_files - {row.get("source_file") for row in entries})
               | (prefabs - {row["name"] for row in entries}))
    if missing:
        raise ValueError("unknown catalog filters: " + ", ".join(sorted(missing)))
    scoped = [row for row in entries
              if (not source_files or row.get("source_file") in source_files)
              and (not prefabs or row["name"] in prefabs)]
    if not scoped:
        raise ValueError("no registrations satisfy the combined filters")
    return scoped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="raw DST persistence file or unwrapped JSON")
    parser.add_argument("--steam-build", help="verified Steam build ID if absent from export")
    parser.add_argument("--output-dir", type=Path, required=True, help="new output directory")
    parser.add_argument("--chinese-po", type=Path, help="compare names against this Simplified Chinese PO")
    parser.add_argument("--knowledge-root", type=Path, help="compare registrations against this Wiki")
    parser.add_argument("--source-file", action="append", default=[], help="limit comparisons by exact loader path")
    parser.add_argument("--prefab", action="append", default=[], help="limit comparisons by exact registration name")
    args = parser.parse_args()

    try:
        catalog = load_catalog(args.export, args.steam_build)
        entries = catalog["entries"]
        scoped = select_entries(entries, set(args.source_file), set(args.prefab))
        outputs = {
            "registrations.json": json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            "prefab-names.csv": csv_text(("prefab", "zh_name"),
                                        ((row["name"], row.get("strings_name") or "") for row in entries)),
        }
        summary = {
            "snapshot": catalog["snapshot"],
            "game_version": catalog.get("game_version"),
            "enabled_mods": catalog.get("enabled_mods"),
            "registrations": len(entries),
            "named": sum(bool(row.get("strings_name")) for row in entries),
            "without_source_file": sum(not row.get("source_file") for row in entries),
            "comparison_scope": {
                "registrations": len(scoped),
                "source_files": args.source_file,
                "prefabs": args.prefab,
            },
        }
        if args.chinese_po:
            po_bytes = args.chinese_po.read_bytes()
            counts, differences = compare_names(scoped, po_bytes.decode("utf-8-sig"))
            summary["chinese_po"] = {
                "path": str(args.chinese_po.resolve()),
                "sha256": hashlib.sha256(po_bytes).hexdigest(),
            }
            summary["name_comparison"] = counts
            outputs["name-differences.csv"] = csv_text(
                ("prefab", "state", "runtime_name", "po_names", "po_lines"), differences)
        if args.knowledge_root:
            coverage, groups = compare_coverage({**catalog, "entries": scoped}, args.knowledge_root)
            summary["coverage"] = coverage
            outputs["coverage-by-file.csv"] = csv_text(
                ("source_file", "mod_root", "registered", "matched", "unmatched", "unmatched_prefabs"), groups)
        outputs["summary.json"] = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"

        args.output_dir.mkdir(parents=True)
        for name, content in outputs.items():
            (args.output_dir / name).write_text(content, encoding="utf-8", newline="")
    except (OSError, ValueError, SyntaxError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(f"Wrote {len(entries)} registrations to {args.output_dir}")


if __name__ == "__main__":
    main()
