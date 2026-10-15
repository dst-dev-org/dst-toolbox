"""Read-only DST Wiki coverage checks with graded output.

A. Alias ownership: with --registrations, a confirmed registration claimed by
   more than one maintained Prefab page is an error. Without a list, shared
   aliases are only suspected: identifier-like names warn, other annotations
   stay info. candidate/unresolved entries never decide ownership.
B. Back-links: the 返回 [[...]] line is compared with the index table that
   registers the page. Only Prefab pages are reported by default; within
   --scope all, a page with no 返回 line is still limited to Prefab pages unless
   --missing-scope all is given. An unparsed 返回 line and an ambiguous
   registration leaf stay separate info states, never a pass.
C. Index budgets: --rows-warn/--bytes-warn are reminders on table data rows and
   UTF-8 bytes; the hard limits stay physical lines/bytes read from the
   selected write-format.md through load_limits. Index checks run only with
   --scope all.
D. Coverage gaps: confirmed registrations with no page stem or alias warn;
   --strict promotes them to errors. candidate/unresolved entries are ignored.

Scope: the default --scope prefab reports only Prefab-page findings; index
budget reminders, non-Prefab back-links/page errors and shared phrase aliases
are skipped. --scope all restores the full inventory (and still keeps
--missing-scope). Alias phrases stay info either way; aliases are search aids,
not required or unique.

Grading: only findings at or above --fail-on (default error) fail the run.
passed/exit 0 therefore means "no blocking finding", not "all content
verified"; checks, counts, groups and unresolved state what was actually
covered. Findings carry per-occurrence detail for error/warning by default;
info occurrences are aggregated into groups and can be expanded with
--severity info --limit N. --code/--page/--changed narrow that detail without
changing counts.

Registrations JSON (optional): a list of names, or an object with an optional
"snapshot" plus a list under entries/registrations/prefabs/items. Each entry is
a name string or an object with name/id/prefab/registration and status
confirmed|candidate|unresolved (missing status means unresolved). Without it,
alias ownership is suspected-only and D is skipped.

Scope follows validate_page.wiki_files: root/reference indexes, typed knowledge
pages and cookbook; updates/, the maintenance log and legacy categories are not
scanned. Only reads pages and BUILD.txt next to the Wiki root; writes nothing.
Exit 0 = no blocking finding, 1 = blocking finding, 2 = unusable input.
"""
import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve()
TOOLS = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "wiki"))

import validate_page as page
from wiki_text import physical_lines
from wiki_data import brief

SEVERITY = {"error": 0, "warning": 1, "info": 2}
SEVERITY_NAMES = ("error", "warning", "info")
STATUSES = ("confirmed", "candidate", "unresolved")
LIST_KEYS = ("entries", "registrations", "prefabs", "items")
NAME_KEYS = ("name", "id", "prefab", "registration")
ALIAS_CODES = ("alias-conflict", "alias-suspected-conflict", "alias-shared-phrase",
               "alias-case-variant")
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{2,}\Z")
BACKLINK = re.compile(r"^\s*(?:[-*+>]\s*)?返回\s*[：:]?\s*")
WIKILINK = re.compile(r"\[\[([^\]\n]+)\]\]")
SEPARATOR_CHARS = set("|-: ")


def finding(code, severity, *, page=None, name=None, line=None, message="", pages=None):
    return {"code": code, "severity": severity, "page": page, "name": name,
            "line": line, "message": message,
            "pages": list(pages) if pages is not None else ([page] if page else [])}


def page_key(value):
    return value[:-3] if value.endswith(".md") else value


def bounded(values, limit=5, width=160):
    """One bounded sentence fragment; silent list tails stay visible."""
    values = sorted(str(value) for value in values)
    text = ", ".join(brief(values, limit, width))
    return text + (f" (+{len(values) - limit} more)" if len(values) > limit else "")


def load_registrations(path):
    """Optional external registration inventory; unknown status is an input error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"registrations file is unreadable: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"registrations JSON is invalid: {exc}") from exc
    snapshot_value = None
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        if "snapshot" in data and not isinstance(data["snapshot"], str):
            raise ValueError("registrations snapshot must be a string")
        snapshot_value = (data.get("snapshot") or "").strip() or None
        rows = next((data[key] for key in LIST_KEYS if isinstance(data.get(key), list)), None)
        if rows is None:
            raise ValueError("registrations JSON needs a list under entries/registrations/prefabs/items")
    else:
        raise ValueError("registrations JSON must be an object or a list")
    entries, seen = [], set()
    for index, row in enumerate(rows, 1):
        if isinstance(row, str):
            name, status = row, "unresolved"
        elif isinstance(row, dict):
            name = next((row[key] for key in NAME_KEYS if isinstance(row.get(key), str)), "")
            status = row.get("status", "unresolved")
        else:
            raise ValueError(f"registration {index}: expected a name string or an object")
        name = name.strip()
        if not name:
            raise ValueError(f"registration {index}: missing name")
        if status not in STATUSES:
            raise ValueError(f"registration {index}: unsupported status {status!r}; "
                             "use confirmed/candidate/unresolved")
        if name.casefold() in seen:
            raise ValueError(f"registration {index}: duplicate name {name}")
        seen.add(name.casefold())
        entries.append({"name": name, "status": status})
    return {"snapshot": snapshot_value, "entries": entries}


def load_changed(path, wiki_root):
    """Optional change scope: one page path per line, for graded detail."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"changed list is unreadable: {exc}") from exc
    changed = set()
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        candidate = Path(raw)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve().relative_to(wiki_root.resolve())
            except ValueError as exc:
                raise ValueError(f"changed page outside the Wiki root: {raw}") from exc
        rel = page_key(candidate.as_posix())
        if rel.startswith("../") or "/../" in rel or rel.startswith("/"):
            raise ValueError(f"unsafe changed page: {raw}")
        changed.add(rel)
    if not changed:
        raise ValueError("changed list has no page paths")
    return changed


def snapshot(wiki_root, registrations):
    """Return (value, source); registrations win, then raw/current/BUILD.txt."""
    if registrations and registrations["snapshot"]:
        return registrations["snapshot"], "registrations"
    try:
        value = (wiki_root.parent / "raw" / "current" / "BUILD.txt").read_text(
            encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        return "unknown", "none"
    return (value, "build-file") if value else ("unknown", "none")


def read_pages(wiki_root):
    """One read per page; unparsable pages stay visible instead of disappearing."""
    records = []
    for path in page.wiki_files(wiki_root):
        name = path.relative_to(wiki_root).as_posix()
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            meta, _body = page.metadata(text)
        except (ValueError, page.yaml.YAMLError, OSError) as exc:
            records.append({"path": name, "error": str(exc)})
            continue
        records.append({"path": name, "meta": meta, "text": text, "bytes": len(raw)})
    if not records:
        raise ValueError("no Wiki pages found; check --wiki-root")
    return records


def check_aliases(records, registrations, include_phrases=True):
    """Prefab alias ownership; exact names own a registration, case variants stay hints."""
    claims, folded, shared = {}, {}, {}
    for record in records:
        if "error" in record:
            continue
        meta = record["meta"]
        if meta.get("type") != "prefab" or meta.get("status") == "archived":
            continue
        aliases = meta.get("aliases")
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                continue
            alias = alias.strip()
            claims.setdefault(alias, set()).add(record["path"])
            folded.setdefault(alias.casefold(), {}).setdefault(alias, set()).add(record["path"])
            shared.setdefault(alias, set()).add(record["path"])
    findings = []
    if registrations is not None:
        for entry in registrations["entries"]:
            if entry["status"] != "confirmed":
                continue
            name = entry["name"]
            owners = sorted(claims.get(name, set()))
            variants = {alias: pages for alias, pages in folded.get(name.casefold(), {}).items()
                        if alias != name}
            if len(owners) > 1:
                findings.append(finding(
                    "alias-conflict", "error", page=owners[0], name=name, pages=owners,
                    message=f"confirmed registration is claimed by {len(owners)} maintained Prefab "
                            f"pages: {bounded(owners)}; keep one owner and cross-reference from the others"))
            if variants:
                variant_names = sorted(variants)
                variant_pages = sorted({page for pages in variants.values() for page in pages})
                pages = sorted(set(owners) | set(variant_pages))
                findings.append(finding(
                    "alias-case-variant", "info", page=(owners[0] if owners else variant_pages[0]),
                    name=name, pages=pages,
                    message=f"confirmed registration has case-variant alias(es) {bounded(variant_names)}; "
                            "only the exact name counts as ownership, variants are not merged"))
        return findings
    for alias in sorted(shared):
        names = sorted(shared[alias])
        if len(names) < 2:
            continue
        if IDENTIFIER.match(alias):
            findings.append(finding(
                "alias-suspected-conflict", "warning", page=names[0], name=alias, pages=names,
                message=f"identifier-like alias is also used by {bounded(names[1:], 4)}; "
                        "no registrations list, confirm which page owns the name"))
        elif include_phrases:
            findings.append(finding(
                "alias-shared-phrase", "info", page=names[0], name=alias, pages=names,
                message=f"alias is shared by {len(names)} Prefab pages ({bounded(names[1:], 4)}); "
                        "descriptive phrase, not treated as an ownership conflict"))
    return findings


def mask_html_comments(lines):
    """Mask HTML comments without moving physical lines or truncating later text."""
    masked, in_comment = [], False
    for line in lines:
        out, position = [], 0
        while position < len(line):
            if in_comment:
                end = line.find("-->", position)
                if end < 0:
                    out.append(" " * (len(line) - position))
                    position = len(line)
                else:
                    out.append(" " * (end + 3 - position))
                    position = end + 3
                    in_comment = False
            else:
                start = line.find("<!--", position)
                if start < 0:
                    out.append(line[position:])
                    position = len(line)
                else:
                    out.append(line[position:start])
                    out.append(" " * 4)
                    position = start + 4
                    in_comment = True
        masked.append("".join(out))
    return masked


def backlink_segments(text):
    """Only lines starting with the 返回 navigation convention; prose/comments are ignored."""
    segments = []
    for number, line in enumerate(mask_html_comments(physical_lines(page.prose(text))), 1):
        match = BACKLINK.match(line)
        if match:
            segments.append((number, line[match.end():]))
    return segments


def parse_targets(segments):
    targets = []
    for number, segment in segments:
        for raw in WIKILINK.findall(segment):
            name = raw.split("|", 1)[0].partition("#")[0].strip()
            if name:
                targets.append((name, number))
    return targets


def check_backlinks(records, registrations, missing_scope="prefab", scope="prefab"):
    findings, states = [], {"ambiguous": 0, "missing": 0, "unrecognized": 0}
    for record in records:
        if "error" in record:
            continue
        meta = record["meta"]
        if meta.get("type") == "index":
            continue
        if scope == "prefab" and meta.get("type") != "prefab":
            continue
        parents = registrations.get(record["path"]) or []
        segments = backlink_segments(record["text"])
        targets = parse_targets(segments)
        directory = Path(record["path"]).parent.as_posix()
        if len(parents) != 1:
            states["ambiguous"] += 1
            findings.append(finding(
                "backlink-unresolved", "info", page=record["path"], name=directory,
                message=f"registration leaf index not identifiable ({len(parents)} table "
                        "registrations); back-link not compared"))
            continue
        leaf = parents[0]
        stem = page_key(leaf)
        if not segments:
            if missing_scope == "prefab" and meta.get("type") != "prefab":
                continue
            states["missing"] += 1
            findings.append(finding(
                "backlink-missing", "info", page=record["path"], name=directory,
                message=f"no 返回 [[...]] line; leaf {stem} stays unverified. Required for "
                        "new/split pages, not a defect for untouched historical pages"))
        elif not targets:
            states["unrecognized"] += 1
            findings.append(finding(
                "backlink-unrecognized", "info", page=record["path"], name=directory,
                line=segments[0][0],
                message=f"a 返回 line exists but no [[...]] target was parsed; leaf {stem} "
                        "not compared, not counted as a pass"))
        elif not any(name == stem for name, _ in targets):
            findings.append(finding(
                "backlink-mismatch", "warning", page=record["path"], name=stem,
                line=targets[0][1],
                message=f"back-link targets {bounded({name for name, _ in targets})} but the page is "
                        f"registered in {stem}; point 返回 at the registering leaf "
                        "(a category hub link may remain as an extra)"))
    return findings, states


def separator(line):
    text = line.strip()
    return bool(text) and "-" in text and set(text) <= SEPARATOR_CHARS


def index_rows(text):
    """Markdown table data rows: headers/separators are not entries."""
    rows = 0
    lines = physical_lines(page.prose(text))
    for number, line in enumerate(lines):
        if not line.lstrip().startswith("|") or separator(line):
            continue
        following = lines[number + 1] if number + 1 < len(lines) else ""
        if separator(following):
            continue
        rows += 1
    return rows


def check_index_budgets(records, limits, rows_warn, bytes_warn, scope="prefab"):
    if scope != "all":
        return []
    findings = []
    for record in records:
        if "error" in record or record["meta"].get("type") != "index":
            continue
        lines = physical_lines(record["text"])
        rows = index_rows(record["text"])
        size = record["bytes"]
        hard_lines, hard_bytes = limits["root" if record["path"] == "index.md" else "index"]
        if len(lines) > hard_lines or size > hard_bytes:
            if len(lines) > hard_lines:
                line = hard_lines + 1
            else:
                prefix = record["text"].encode("utf-8")[:hard_bytes]
                line = len(re.findall(r"\r\n|\r|\n", prefix.decode("utf-8", "ignore"))) + 1
            findings.append(finding(
                "index-budget", "error", page=record["path"], line=line,
                message=f"{rows} table data rows, {len(lines)} physical lines / {size} bytes "
                        f"exceeds the format hard limit {hard_lines} physical lines / "
                        f"{hard_bytes} bytes; split by a stable topic"))
        elif rows > rows_warn or size > bytes_warn:
            findings.append(finding(
                "index-budget-reminder", "warning", page=record["path"],
                message=f"{rows} table data rows (not physical lines), {len(lines)} physical "
                        f"lines / {size} bytes; reminder {rows_warn} rows / {bytes_warn} bytes, "
                        f"hard limit {hard_lines} physical lines / {hard_bytes} bytes"))
    return findings


def check_coverage(records, registrations, strict):
    """A confirmed registration needs a maintained Prefab page stem or alias."""
    if registrations is None:
        return []
    covered, folded = set(), {}
    for record in records:
        if "error" in record:
            continue
        meta = record["meta"]
        if meta.get("type") != "prefab" or meta.get("status") == "archived":
            continue
        stem = Path(record["path"]).stem
        covered.add(stem)
        folded.setdefault(stem.casefold(), set()).add(stem)
        aliases = meta.get("aliases")
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias.strip():
                    alias = alias.strip()
                    covered.add(alias)
                    folded.setdefault(alias.casefold(), set()).add(alias)
    findings = []
    for entry in registrations["entries"]:
        if entry["status"] != "confirmed":
            continue
        name = entry["name"]
        if name in covered:
            continue
        variants = sorted(folded.get(name.casefold(), set()) - {name})
        detail = (f"; case-variant claim(s) {bounded(variants)} do not count as coverage"
                  if variants else "")
        findings.append(finding(
            "coverage-gap", "error" if strict else "warning", name=name,
            message="confirmed registration has no maintained Prefab page stem or alias"
                    + detail + (" (promoted by --strict)" if strict else "")))
    return findings


def group_key(item):
    if item["code"].startswith("backlink") or item["code"] in ALIAS_CODES or \
            item["code"] == "coverage-gap":
        return item["name"] or "unknown"
    return item["page"] or item["name"] or "unknown"


def group_findings(findings):
    """Full-scan summary; pages stay complete for warnings, sampled for info."""
    groups = {}
    for item in findings:
        key = group_key(item)
        entry = groups.setdefault((SEVERITY[item["severity"]], item["code"], key), {
            "code": item["code"], "severity": item["severity"], "key": key,
            "count": 0, "pages": []})
        entry["count"] += 1
        for item_page in item["pages"]:
            if item_page not in entry["pages"]:
                entry["pages"].append(item_page)
    result = []
    for key in sorted(groups, key=lambda value: (value[0], value[1], value[2])):
        entry = groups[key]
        entry["pages_total"] = len(entry["pages"])
        entry["pages"] = entry["pages"][:20 if entry["severity"] == "info" else 100]
        result.append(entry)
    return result


def matches_page(item, prefixes):
    texts = item["pages"] or [item["page"] or ""]
    name = item["name"] or ""
    return any(text.startswith(prefix) or name.startswith(prefix)
               for text in texts for prefix in prefixes)


def select_detail(findings, args, changed):
    """Per-occurrence detail: errors/warnings by default, info on request."""
    if args.severity:
        selected = set(args.severity)
    elif args.code:
        selected = set(SEVERITY_NAMES)
    else:
        selected = {"error", "warning"}
    detail = [item for item in findings if item["severity"] in selected]
    if args.code:
        detail = [item for item in detail if item["code"] in args.code]
    if args.page:
        detail = [item for item in detail if matches_page(item, args.page)]
    if changed is not None:
        detail = [item for item in detail
                  if not item["pages"]
                  or any(page_key(candidate) in changed for candidate in item["pages"])]
    return detail


def build(args):
    wiki_root = args.wiki_root.resolve()
    if not wiki_root.is_dir():
        raise ValueError(f"wiki root is not a directory: {wiki_root}")
    limits = page.load_limits(args.format)
    registrations = load_registrations(args.registrations) if args.registrations else None
    changed = load_changed(args.changed, wiki_root) if args.changed else None
    records = read_pages(wiki_root)
    navigation = page.check_indexes(wiki_root)

    findings = []
    findings += check_aliases(records, registrations, include_phrases=args.scope == "all")
    backlink_findings, backlink_states = check_backlinks(
        records, navigation.get("registrations", {}), args.missing_scope, args.scope)
    findings += backlink_findings
    findings += check_index_budgets(records, limits, args.rows_warn, args.bytes_warn, args.scope)
    findings += check_coverage(records, registrations, args.strict)
    for record in records:
        if "error" in record and (args.scope == "all" or
                                  record["path"].startswith("reference/prefabs/")):
            findings.append(finding(
                "page-unparsed", "info", page=record["path"],
                message=f"frontmatter/metadata not parsed; page excluded from A-D: {record['error']}"))
    findings.sort(key=lambda item: (SEVERITY[item["severity"]], item["code"],
                                    item["page"] or "", item["name"] or "", item["line"] or 0))

    counts = {"total": len(findings), "error": 0, "warning": 0, "info": 0, "by_code": {}}
    for item in findings:
        counts[item["severity"]] += 1
        counts["by_code"][item["code"]] = counts["by_code"].get(item["code"], 0) + 1
    counts["by_code"] = dict(sorted(counts["by_code"].items()))

    page_errors = sum(1 for record in records if "error" in record and
                      (args.scope == "all" or record["path"].startswith("reference/prefabs/")))
    registration_unresolved = sum(1 for entry in (registrations or {"entries": []})["entries"]
                                  if entry["status"] == "unresolved")
    unresolved = {
        "total": registration_unresolved + page_errors + backlink_states["ambiguous"]
                 + backlink_states["unrecognized"],
        "registrations": registration_unresolved,
        "pages": page_errors,
        "backlinks": backlink_states["ambiguous"] + backlink_states["unrecognized"],
        "backlink_ambiguous": backlink_states["ambiguous"],
        "backlink_unrecognized": backlink_states["unrecognized"],
        "backlink_missing": backlink_states["missing"],
    }

    detail = select_detail(findings, args, changed)
    detail.sort(key=lambda item: (SEVERITY[item["severity"]], item["code"],
                                  item["page"] or "", item["name"] or "", item["line"] or 0))
    shown = detail[:args.limit]
    blocking = [item for item in findings
                if SEVERITY[item["severity"]] <= SEVERITY[args.fail_on]]
    if not findings:
        exit_reason = "clean"
    elif blocking:
        exit_reason = next(name for name in SEVERITY_NAMES
                           if any(item["severity"] == name for item in blocking))
    else:
        exit_reason = "non-blocking"

    value, source = snapshot(wiki_root, registrations)
    checks = {
        "page_scope": args.scope,
        "alias_ownership": "confirmed" if registrations else "suspected-only",
        "coverage_gaps": "checked" if registrations else "skipped",
        "backlinks": "partial" if page_errors or backlink_states["ambiguous"] or
                     backlink_states["unrecognized"] else "checked",
        "indexes": "checked" if args.scope == "all" else "skipped",
        "snapshot_source": source,
    }
    scope = {
        "wiki_root": str(wiki_root),
        "page_scope": args.scope,
        "pages": len(records),
        "prefabs": sum(1 for record in records
                       if record.get("meta", {}).get("type") == "prefab"),
        "indexes": sum(1 for record in records
                       if record.get("meta", {}).get("type") == "index"),
        "registrations": len(registrations["entries"]) if registrations else 0,
        "changed": len(changed) if changed is not None else None,
    }
    report = {
        "snapshot": value,
        "scope": scope,
        "checks": checks,
        "counts": counts,
        "unresolved": unresolved,
        "hits_total": len(findings),
        "shown": len(shown),
        "truncated": len(detail) > len(shown),
        "omitted": len(findings) - len(shown),
        "findings": shown,
        "groups": group_findings(findings),
        "passed": not blocking,
        "exit_reason": exit_reason,
    }
    return report


def render(report):
    scope, checks, counts = report["scope"], report["checks"], report["counts"]
    unresolved = report["unresolved"]
    lines = [
        f"snapshot: {report['snapshot']}",
        f"scope: {scope['pages']} pages ({scope['prefabs']} prefab, {scope['indexes']} index) "
        f"under {scope['wiki_root']}; registrations {scope['registrations']}; "
        f"changed {scope['changed'] if scope['changed'] is not None else 'not supplied'}",
        f"checks: page-scope={checks['page_scope']} "
        f"alias-ownership={checks['alias_ownership']} "
        f"coverage-gaps={checks['coverage_gaps']} backlinks={checks['backlinks']} "
        f"indexes={checks['indexes']} snapshot={checks['snapshot_source']}",
        f"counts: {counts['total']} total (error {counts['error']}, "
        f"warning {counts['warning']}, info {counts['info']})",
        f"unresolved: {unresolved['total']} (registrations {unresolved['registrations']}, "
        f"pages {unresolved['pages']}, backlinks {unresolved['backlinks']}; "
        f"missing back-link {unresolved['backlink_missing']})",
        f"detail: shown {report['shown']}, omitted {report['omitted']}, "
        f"truncated {'yes' if report['truncated'] else 'no'}",
        f"passed: {'yes' if report['passed'] else 'no'}; exit_reason: {report['exit_reason']}",
    ]
    for group in report["groups"]:
        sample = ", ".join(group["pages"][:3])
        more = f" (+{group['pages_total'] - 3} more)" if group["pages_total"] > 3 else ""
        lines.append(f"[group] {group['severity']} {group['code']} {group['key']}: "
                     f"{group['count']} finding(s), {group['pages_total']} page(s)"
                     + (f" [{sample}{more}]" if sample else ""))
    for item in report["findings"]:
        where = item["page"] or f"(name {item['name']})"
        if item["line"] is not None:
            where += f":{item['line']}"
        lines.append(f"[{item['severity']}] {item['code']} {where}: {item['message']}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", type=Path, required=True,
                        help="Wiki directory (the parent holds raw/current/BUILD.txt)")
    parser.add_argument("--format", type=Path, required=True,
                        help="authoritative write-format.md with the size table")
    parser.add_argument("--registrations", type=Path,
                        help="optional registration inventory JSON (confirmed/candidate/unresolved)")
    parser.add_argument("--rows-warn", type=int, default=60,
                        help="index table-data-row reminder (default 60)")
    parser.add_argument("--bytes-warn", type=int, default=12288,
                        help="index UTF-8 byte reminder (default 12288)")
    parser.add_argument("--strict", action="store_true",
                        help="promote confirmed-registration coverage gaps to errors")
    parser.add_argument("--scope", choices=("prefab", "all"), default="prefab",
                        help="report only Prefab pages (default) or every knowledge page; "
                             "index budgets and alias phrases need --scope all")
    parser.add_argument("--missing-scope", choices=("prefab", "all"), default="prefab",
                        help="with --scope all, report pages without 返回 lines for Prefab "
                             "pages only (default) or for every knowledge page")
    parser.add_argument("--fail-on", choices=SEVERITY_NAMES, default="error",
                        help="lowest severity that fails the run (default error)")
    parser.add_argument("--severity", action="append", choices=SEVERITY_NAMES,
                        help="include per-occurrence detail for this severity (repeatable)")
    parser.add_argument("--code", action="append",
                        help="only detail for this code (repeatable; implies all severities)")
    parser.add_argument("--page", action="append",
                        help="only detail whose page/name starts with this prefix (repeatable)")
    parser.add_argument("--changed", type=Path,
                        help="file of page paths changed in this round; filters detail")
    parser.add_argument("--json", action="store_true", help="emit the machine report only")
    parser.add_argument("--limit", type=int, default=500,
                        help="maximum detail findings echoed (1..5000, default 500)")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 5000:
        raise ValueError("--limit must be 1..5000")
    if args.rows_warn < 0 or args.bytes_warn < 0:
        raise ValueError("warn thresholds must be nonnegative")
    for values in (args.code, args.page):
        for value in values or []:
            if not value.strip():
                raise ValueError("--code/--page filters must be nonempty")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    report = build(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report), end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, ImportError, page.yaml.YAMLError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
