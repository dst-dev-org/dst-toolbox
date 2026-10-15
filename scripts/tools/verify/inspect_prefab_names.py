"""Locate Simplified Chinese display-name evidence for selected Wiki pages."""
import argparse
from ast import literal_eval
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_page import metadata
from wiki_text import physical_lines


PO_PATH = Path("languages/chinese_s.po")
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
STRING_KEY = re.compile(r"STRINGS(?:\.[A-Za-z0-9_]+)+")


def candidate_keys(path, meta):
    names = [path.stem, *meta["aliases"]]
    return {f"STRINGS.NAMES.{name.upper()}" for name in names
            if IDENTIFIER.fullmatch(name)}


def find_entries(text, keys):
    """Read selected singular PO entries, including multiline values."""
    lines = physical_lines(text)
    entries = {}
    prefix = 'msgctxt "'
    for index, line in enumerate(lines):
        if not line.startswith(prefix) or not line.endswith('"'):
            continue
        key = line[len(prefix):-1]
        if key not in keys:
            continue
        comment = index - 1
        fuzzy = False
        while comment >= 0 and lines[comment].startswith("#"):
            if lines[comment].startswith("#,") and "fuzzy" in lines[comment][2:].replace(",", " ").split():
                fuzzy = True
                break
            comment -= 1
        if fuzzy:
            continue
        values = {"msgid": "", "msgstr": ""}
        field = None
        end_line = index + 1
        for offset in range(index + 1, len(lines)):
            entry_line = lines[offset]
            label, _, value = entry_line.partition(" ")
            if label in values:
                field = label
                fragment = literal_eval(value)
                if not isinstance(fragment, str):
                    raise ValueError(f"expected a quoted PO value for {key} at line {offset + 1}")
                values[field] = fragment
            elif field and entry_line.startswith('"'):
                values[field] += literal_eval(entry_line)
            else:
                break
            end_line = offset + 1
        if values["msgstr"].strip():
            entries.setdefault(key, []).append({
                "key": key, "english": values["msgid"], "zh_cn": values["msgstr"],
                "start_line": index + 1, "end_line": end_line,
            })
    return entries


def compare_name(entry, meta, match):
    name = entry["zh_cn"]
    present_in = [field for field in ("title", "summary") if name in meta[field]]
    if name in meta["aliases"]:
        present_in.append("aliases")
    return {
        **entry, "match": match, "present_in": present_in,
        "review_visible_name": not any(field in present_in for field in ("title", "summary")),
    }


def read_name_catalog(path):
    entries = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["prefab", "zh_name"]:
            raise ValueError("name catalog requires prefab,zh_name columns")
        for row in reader:
            name, value = row["prefab"], row["zh_name"]
            if not name or value is None or None in row:
                raise ValueError(f"malformed name catalog row at line {reader.line_num}")
            key = f"STRINGS.NAMES.{name.upper()}"
            if key in entries:
                raise ValueError(f"duplicate name catalog registration: {name}")
            entries[key] = value
    return {key: value for key, value in entries.items() if value}


def catalog_candidates(keys, entries, catalog):
    for key in sorted(keys & catalog.keys()):
        name = catalog[key]
        if all(entry["zh_cn"] != name for entry in entries.get(key, ())):
            yield {"key": key, "zh_cn": name, "match": "runtime-name-catalog"}


def inspect_page(path, meta, guessed, explicit, entries, provided=(), catalog=None):
    candidates = [compare_name({"zh_cn": name}, meta, "provided-name") for name in provided]
    for key in sorted(guessed | explicit):
        for entry in entries.get(key, ()):
            match = "explicit-key" if key in explicit else "registration-shaped"
            candidates.append(compare_name(entry, meta, match))
    candidates.extend(compare_name(entry, meta, entry["match"])
                      for entry in catalog_candidates(guessed | explicit, entries, catalog or {}))
    return {"page": str(path), "title": meta["title"], "candidates": candidates}


def source_identity(source):
    stat = source.stat()
    build_file = source.parent.parent.parent / "BUILD.txt"
    return {
        "path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "build": build_file.read_text(encoding="utf-8-sig").strip() if build_file.is_file() else None,
    }


def read_previous_report(reuse):
    report = json.load(sys.stdin.buffer) if reuse == "-" else json.loads(Path(reuse).read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict) or report.get("report_version") != 1:
        raise ValueError("expected a batch name inspection report")
    requests = report.get("requests")
    if not isinstance(requests, dict) or not isinstance(requests.get("pages"), dict):
        raise ValueError("prior report is missing batch page requests")
    if requests.get("source_root") and not isinstance(report.get("po_evidence"), dict):
        raise ValueError("prior report is missing PO evidence")
    return report


def collect_evidence(source, keys, evidence=None):
    identity = source_identity(source)
    if evidence is not None:
        if not isinstance(evidence, dict) or evidence.get("source") != identity:
            raise ValueError("reused evidence must come from the same unchanged PO and snapshot")
        entries = evidence.get("entries")
        checked = evidence.get("checked_keys")
        if not isinstance(entries, dict) or not isinstance(checked, list) or not all(isinstance(key, str) for key in checked):
            raise ValueError("expected a prior report with PO entries and checked keys")
        missing = keys - set(checked)
        if missing:
            raise ValueError(f"reused evidence did not check {len(missing)} key(s): {', '.join(sorted(missing)[:5])}; run a fresh lookup")
        return evidence

    entries = find_entries(source.read_text(encoding="utf-8-sig"), keys)
    if source_identity(source) != identity:
        raise ValueError("PO or snapshot changed during lookup; rerun the batch")
    return {"source": identity, "checked_keys": sorted(keys), "entries": entries}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="*", type=Path, help="selected Prefab Markdown files")
    parser.add_argument("--source-root", type=Path, help="scripts root for PO lookup")
    parser.add_argument("--name-catalog", type=Path, help="Wiki prefab-names.csv for registration-name lookup")
    parser.add_argument("--key", action="append", default=[], help="exact STRINGS display key, repeatable")
    parser.add_argument("--display-name", action="append", default=[],
                        help="display name confirmed separately, compare against one page; repeatable")
    parser.add_argument("--page-key", nargs=2, action="append", default=[], metavar=("PAGE", "KEY"),
                        help="exact display key for one page in a batch; repeatable")
    parser.add_argument("--page-name", nargs=2, action="append", default=[], metavar=("PAGE", "NAME"),
                        help="separately confirmed display name for one page in a batch; repeatable")
    parser.add_argument("--reuse", help="reuse batch inputs and PO evidence from a previous report; use - for stdin")
    parser.add_argument("--output", type=Path, help="also save a new JSON report at this path")
    args = parser.parse_args(argv)
    previous = read_previous_report(args.reuse) if args.reuse is not None else {}
    saved = previous.get("requests", {})
    saved_pages = saved.get("pages", {})
    source_root = args.source_root or saved.get("source_root")
    catalog_path = args.name_catalog or saved.get("name_catalog")
    page_keys, page_names = defaultdict(set), defaultdict(list)
    for path, key in args.page_key:
        page_keys[Path(path).resolve()].add(key)
    for path, name in args.page_name:
        page_names[Path(path).resolve()].append(name.strip())
    paths = list(dict.fromkeys([*(path.resolve() for path in args.pages), *page_keys, *page_names]))
    if not paths and not args.key and not args.display_name:
        paths = list(map(Path, saved_pages))
        args.key = saved.get("lookup_keys", [])
    if not paths and not args.key:
        parser.error("specify at least one page or --key")
    if len(paths) > 1 and (args.key or args.display_name):
        parser.error("use --page-key and --page-name to associate inputs with pages in a batch")
    if args.display_name and not paths:
        parser.error("--display-name requires a page")
    if len(paths) == 1:
        page_keys[paths[0]].update(args.key)
        page_names[paths[0]].extend(name.strip() for name in args.display_name)
    for path in paths:
        page_request = saved_pages.get(str(path), {})
        page_keys[path].update(page_request.get("keys", ()))
        page_names[path] = list(dict.fromkeys([*page_request.get("display_names", ()), *page_names[path]]))
    explicit = set(args.key).union(*page_keys.values())
    if any(not STRING_KEY.fullmatch(key) for key in explicit):
        parser.error("display keys must be full STRINGS keys")
    if any("" in names for names in page_names.values()):
        parser.error("display names must be nonempty")
    if source_root is None and catalog_path is None and (explicit or not all(page_names[path] for path in paths)):
        parser.error("--source-root or --name-catalog is required for name lookup")

    pages = []
    keys = set(explicit)
    for path in paths:
        meta, _ = metadata(path.read_text(encoding="utf-8-sig"))
        if (meta.get("type") != "prefab" or not isinstance(meta.get("aliases"), list)
                or not all(isinstance(alias, str) for alias in meta["aliases"])
                or not all(isinstance(meta.get(field), str) for field in ("title", "summary"))):
            raise ValueError(f"expected Prefab metadata with title, summary and aliases: {path}")
        guessed = candidate_keys(path, meta)
        keys.update(guessed)
        pages.append((path, meta, guessed))

    source = Path(source_root).resolve() / PO_PATH if source_root is not None else None
    evidence = collect_evidence(source, keys, previous.get("po_evidence")) if source else None
    entries = evidence["entries"] if evidence else {}
    catalog_path = Path(catalog_path).resolve() if catalog_path else None
    catalog = read_name_catalog(catalog_path) if catalog_path else {}
    report = {
        "report_version": 1,
        "source": str(source) if source else None,
        "pages": [
            inspect_page(path, meta, guessed, page_keys[path], entries, page_names[path], catalog)
            for path, meta, guessed in pages
        ],
        "lookups": [] if pages else [
            *(entry for key in sorted(explicit) for entry in entries.get(key, ())),
            *catalog_candidates(explicit, entries, catalog),
        ],
        "missing_explicit_keys": sorted(explicit - entries.keys() - catalog.keys()),
        "ambiguous_keys": sorted(key for key in keys if len(entries.get(key, ())) > 1),
        "requests": {
            "source_root": str(source.parents[1]) if source else None,
            "lookup_keys": sorted(explicit) if not pages else [],
            "pages": {str(path): {"keys": sorted(page_keys[path]), "display_names": page_names[path]} for path in paths},
        },
        "po_evidence": evidence,
        "note": "PO matches are candidates. Provided names are caller-supplied. Review display evidence and prose/index context.",
    }
    if catalog_path:
        report["name_catalog"] = str(catalog_path)
        report["requests"]["name_catalog"] = str(catalog_path)
        report["note"] += " CSV matches are runtime name-table candidates without PO line evidence."
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        with args.output.open("x", encoding="utf-8", newline="\n") as file:
            file.write(output)
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(output, end="")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, SyntaxError, TypeError, yaml.YAMLError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
