"""Check Wiki metadata, local links and physical size; not DST semantics/runtime."""
import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
import os
from urllib.parse import unquote, urlsplit
import yaml

REPO = Path(__file__).resolve().parents[3]
FORMAT = None


def resolve_format(value=None):
    value = value or FORMAT or os.environ.get('DST_WIKI_FORMAT')
    if not value or not Path(value).is_file():
        raise ValueError('specify --format pointing to dst-wiki-skill/references/maintain/write-format.md')
    return Path(value).resolve()
TYPE_DIRECTORIES = {
    "component": ("reference", "components"),
    "prefab": ("reference", "prefabs"),
    "stategraph": ("reference", "stategraphs"),
    "api": ("reference", "api"),
    "mechanism": ("reference", "mechanisms"),
    "cookbook": ("cookbook",),
}


def load_limits(format_path=FORMAT):
    """Read the authoritative table, rather than maintaining a second policy."""
    rows = re.findall(r"^\|\s*([^|\n]+?)\s*\|\s*(\d+)\s*\|\s*(\d+) KiB\s*\|",
                      resolve_format(format_path).read_text(encoding="utf-8"), re.M)
    limits = {}
    for label, lines, kib in rows:
        key = ("root" if "根导航" in label else "index" if "索引" in label
               else "cookbook" if "cookbook" in label else "page")
        if key in limits:
            raise ValueError(f"duplicate size policy: {key}")
        limits[key] = (int(lines), int(kib) * 1024)
    if set(limits) != {"root", "index", "page", "cookbook"}:
        raise ValueError("missing/unknown size policy; inspect write-format.md")
    return limits


def load_size_classes(format_path=FORMAT, limits=None):
    """Optional reference-page budgets; older policies retain the standard limit."""
    limits = limits if limits is not None else load_limits(format_path)
    text = resolve_format(format_path).read_text(encoding="utf-8")
    _, separator, body = text.partition("### 源码知识页分档\n")
    if not separator:
        return {"standard": limits["page"]}
    body = re.split(r"^#{1,3} ", body, maxsplit=1, flags=re.M)[0]
    rows = re.findall(r"^\|\s*`([a-z-]+)`\s*\|[^|\n]*\|\s*(\d+)\s*\|\s*(\d+) KiB\s*\|",
                      body, re.M)
    classes = {}
    for name, lines, kib in rows:
        if name in classes:
            raise ValueError(f"duplicate size class: {name}")
        classes[name] = (int(lines), int(kib) * 1024)
    if set(classes) != {"simple", "standard", "complex"}:
        raise ValueError("missing/unknown size class; inspect write-format.md")
    if classes["standard"] != limits["page"]:
        raise ValueError("standard size class differs from the default page budget")
    for dimension in (0, 1):
        if not 0 < classes["simple"][dimension] <= classes["standard"][dimension] <= classes["complex"][dimension]:
            raise ValueError("size class budgets must be positive and ordered")
    return classes


def prose(text):
    result, fence = [], None
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match:
            if fence is None:
                fence = (match[1][0], len(match[1]))
            elif (fence[0] == match[1][0] and len(match[1]) >= fence[1]
                  and not match[2].strip()):
                fence = None
            result.append("")
        else:
            result.append(line if fence is None else "")
    return "\n".join(result)


def headings(text):
    return {s["anchor"] for s in sections(text)}


def sections(text):
    """Fence-aware ATX chapters, inclusive 1-based physical line ranges."""
    result, used = [], set()
    for number, line in enumerate(prose(text).splitlines(), 1):
        match = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*(?:\s+#+\s*)?$", line)
        if not match:
            continue
        title = match[2].strip()
        plain = re.sub(r"[`*_]", "", title).lower()
        base = "".join(c for c in plain if c.isalnum() or c in " -_").replace(" ", "-")
        slug, suffix = base, 0
        while slug in used:
            suffix += 1
            slug = f"{base}-{suffix}"
        used.add(slug)
        result.append({"title": title, "anchor": slug, "level": len(match[1]), "start": number})
    end = len(text.splitlines())
    for i, section in enumerate(result):
        section["end"] = next((s["start"] - 1 for s in result[i + 1:]
                               if s["level"] <= section["level"]), end)
    return result


def load_tags(format_path=FORMAT):
    body = resolve_format(format_path).read_text(encoding="utf-8").split("## 标签\n", 1)[1]
    return set(re.findall(r"[a-z]+(?:-[a-z]+)*", "\n".join(
        line.split("：", 1)[1] for line in body.splitlines() if line.startswith("- ") and "：" in line)))


def wiki_category(name):
    """Return the semantic category, rather than the shared reference container."""
    parts = Path(name).parts
    return next((prefix for prefix in TYPE_DIRECTORIES.values()
                 if parts[:len(prefix)] == prefix), None)


def wiki_files(wiki_root):
    """Task/reference categories and their navigation; exclude unrelated material."""
    excluded = {"sessions", "decisions", "templates", "patterns", "pitfalls"}
    return sorted(p for p in wiki_root.rglob("*.md") if p in
                  (wiki_root / "index.md", wiki_root / "reference/index.md") or
                  (wiki_category(p.relative_to(wiki_root)) and p.name != "log.md"
                   and not excluded.intersection(p.relative_to(wiki_root).parts[:-1])))


def wiki_links(text, path, wiki_root):
    """Local Wiki/Markdown links with navigation-table and Top30 context."""
    top = False
    for number, line in enumerate(prose(text).splitlines(), 1):
        if re.match(r"^##\s", line):
            top = bool(re.match(r"^##\s+Top 30\b", line, re.I))
        targets = [(m, True) for m in re.findall(r"\[\[([^\]\n]+)\]\]", line)]
        targets += [(m, False) for m in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)", line)]
        for target, wiki in targets:
            name, _, anchor = target.split("|", 1)[0].partition("#")
            if not wiki and urlsplit(name).scheme:
                continue
            dest = ((wiki_root / (name + ".md") if name else path) if wiki else
                    path.parent / unquote(name) if name else path).resolve()
            if dest.is_relative_to(wiki_root.resolve()):
                yield {"path": dest.relative_to(wiki_root.resolve()).as_posix(), "anchor": unquote(anchor),
                       "line": number, "table": line.lstrip().startswith("|"), "top30": top}


def check_indexes(wiki_root):
    """Check authored navigation; cross-links outside tables are not registration."""
    wiki_root = wiki_root.resolve()
    pages, issues = {}, []
    for path in wiki_files(wiki_root):
        name = path.relative_to(wiki_root).as_posix()
        try:
            meta, _ = metadata(path.read_text(encoding="utf-8"))
            pages[name] = (meta, list(wiki_links(path.read_text(encoding="utf-8"), path, wiki_root)))
        except (ValueError, yaml.YAMLError) as exc:
            issues.append({"code": "navigation-metadata", "path": name, "message": str(exc)})
    indexes = {name for name, (meta, _) in pages.items() if meta.get("type") == "index"}
    graph = {name: set() for name in indexes}
    registrations = {name: [] for name, (meta, _) in pages.items() if meta.get("type") != "index"}
    shortcuts = []
    for name in sorted(indexes):
        for link in pages[name][1]:
            dest = link["path"]
            if link["table"] and not link["top30"]:
                if dest in indexes and dest != name:
                    graph[name].add(dest)
                elif dest in registrations and wiki_category(name) == wiki_category(dest) and wiki_category(name):
                    registrations[dest].append(name)
                elif dest in registrations and name == "index.md":
                    issues.append({"code": "root-leaf", "line": link["line"],
                                   "message": "root tables route to categories; page shortcuts belong in Top30"})
                elif dest in registrations:
                    issues.append({"code": "registration-category", "path": name, "line": link["line"],
                                   "message": f"register {dest} in its own category leaf; cross-links belong outside tables"})
            if name == "index.md" and link["top30"]:
                shortcuts.append(link)
    if "index.md" not in indexes:
        issues.append({"code": "root-index", "message": "missing root index"})
    reached, visiting = set(), set()

    def visit(name):
        if name in visiting:
            issues.append({"code": "index-cycle", "path": name, "message": "cycle in navigation tables"})
            return
        if name in reached:
            return
        visiting.add(name)
        for child in sorted(graph[name]):
            visit(child)
        visiting.remove(name)
        reached.add(name)

    if "index.md" in indexes:
        visit("index.md")
    for name in sorted(indexes - reached):
        issues.append({"code": "index-unreachable", "path": name, "message": "no parent route from root"})
    for name, parents in sorted(registrations.items()):
        if not parents and pages[name][0].get("status") == "archived":
            continue  # Historical pages may be removed from normal navigation.
        if len(parents) != 1:
            issues.append({"code": "registration", "path": name, "message": f"expected one leaf table registration, got {len(parents)}"})
        elif graph[parents[0]] and Path(name).parent != Path(parents[0]).parent:
            issues.append({"code": "registration-nonleaf", "path": name,
                           "message": f"{parents[0]} routes to subindexes; register nested pages in their own leaf"})
    seen = set()
    for link in shortcuts:
        key = (link["path"], link["anchor"])
        meta = pages.get(link["path"], ({}, []))[0]
        if key in seen or meta.get("type") == "index" or meta.get("status") != "active":
            issues.append({"code": "top30-target", "line": link["line"], "message": f"duplicate, missing or inactive shortcut: {key}"})
        seen.add(key)
    if len(shortcuts) > 30:
        issues.append({"code": "top30-count", "message": f"{len(shortcuts)} shortcuts; maximum 30"})
    return {"passed": not issues, "issues": issues, "indexes": len(indexes),
            "knowledge_pages": len(registrations), "top30": len(shortcuts),
            "registrations": registrations}


def metadata(text):
    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        keys = [loader.construct_object(key, deep=deep) for key, _ in node.value]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate frontmatter keys")
        return dict(loader.construct_pairs(node, deep=deep))

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        raise ValueError("missing YAML frontmatter")
    data = yaml.load(match[1], Loader=UniqueLoader)
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    return data, text[match.end():]


def check_page(path, wiki_root, limits=None, source_root=None, format_path=None, size_classes=None):
    limits = limits or load_limits(format_path)
    path, wiki_root = path.resolve(), wiki_root.resolve()
    if not path.is_relative_to(wiki_root) or path.name == "log.md":
        raise ValueError("check only Wiki knowledge/index pages; maintenance log is excluded")
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    issues = []
    meta, body = {}, text
    try:
        meta, body = metadata(text)
    except (ValueError, yaml.YAMLError) as exc:
        issues.append({"code": "frontmatter", "message": str(exc)})
    kind = meta.get("type")
    index = kind == "index"
    required = {"title", "created", "updated", "type", "tags"}
    if not index:
        required |= {"summary", "aliases", "dst_build", "sources", "reliability", "validation", "status"}
    for key in sorted(required - meta.keys()):
        issues.append({"code": "metadata", "message": f"missing {key}"})
    allowed = {"index", *TYPE_DIRECTORIES}
    if not isinstance(kind, str) or kind not in allowed:
        issues.append({"code": "metadata", "message": "unsupported page type"})
    for key in ("title", "summary", "dst_build"):
        if key in meta and (not isinstance(meta[key], str) or not meta[key].strip()):
            issues.append({"code": "metadata", "message": f"{key} must be a nonempty string"})
    for key in ("aliases", "sources", "tags"):
        if key in meta and (not isinstance(meta[key], list) or
                            any(not isinstance(v, str) or not v.strip() for v in meta[key])):
            issues.append({"code": "metadata", "message": f"{key} must be a string list"})
    if isinstance(meta.get("tags"), list):
        for tag in meta["tags"]:
            if isinstance(tag, str) and tag not in load_tags(format_path):
                issues.append({"code": "tag", "message": f"unknown tag {tag}; update authoritative taxonomy first"})
    dates = {}
    for key in ("created", "updated"):
        try:
            dates[key] = date.fromisoformat(str(meta[key]))
        except (KeyError, ValueError, TypeError):
            issues.append({"code": "metadata", "message": f"invalid {key} date"})
    if len(dates) == 2 and dates["created"] > dates["updated"]:
        issues.append({"code": "metadata", "message": "updated precedes created"})
    if not index:
        for key, values in {"reliability": {"verified"},
                            "validation": {"source-reviewed", "runtime-tested"},
                            "status": {"active", "review-needed", "archived"}}.items():
            if not isinstance(meta.get(key), str) or meta[key] not in values:
                issues.append({"code": "metadata", "message": f"invalid {key}"})
        expected = TYPE_DIRECTORIES.get(kind) if isinstance(kind, str) else None
        if expected and path.relative_to(wiki_root).parts[:len(expected)] != expected:
            issues.append({"code": "metadata", "message": "type differs from category directory"})
    if isinstance(meta.get("sources"), list):
        for source in meta["sources"]:
            if not isinstance(source, str):
                continue
            if not source or source.startswith("/") or ":" in source or "\\" in source or any(
                    p in ("", ".", "..") for p in source.split("/")):
                issues.append({"code": "source-path", "message": f"unsafe source {source}"})
            elif source_root:
                dest = (source_root / source).resolve()
                if not dest.is_relative_to(source_root.resolve()) or not dest.is_file():
                    issues.append({"code": "source-path", "message": f"missing source {source}"})
    category = "root" if path == wiki_root / "index.md" else "index" if index else "cookbook" if kind == "cookbook" else "page"
    line_limit, byte_limit = limits[category]
    selected_class = "standard"
    if "size_class" in meta:
        value = meta["size_class"]
        if category != "page":
            issues.append({"code": "metadata", "message": "size_class applies only to reference knowledge pages"})
        elif not isinstance(value, str) or value not in {"simple", "standard", "complex"}:
            issues.append({"code": "metadata", "message": "invalid size_class"})
        else:
            classes = size_classes if size_classes is not None else load_size_classes(format_path)
            if value not in classes:
                issues.append({"code": "metadata", "message": f"size_class {value} is not defined by the selected format"})
            else:
                selected_class = value
                line_limit, byte_limit = classes[value]
    line_count = raw.count(b"\n") + int(bool(raw) and not raw.endswith(b"\n"))
    size = {"lines": line_count, "utf8_bytes": len(raw), "max_lines": line_limit,
            "max_bytes": byte_limit, "category": category}
    if category == "page":
        size["size_class"] = selected_class
    if line_count > line_limit:
        issues.append({"code": "size-lines", "line": line_limit + 1,
                       "message": "line budget exceeded; split by object/interface or distinct task"})
    if len(raw) > byte_limit:
        line = raw[:byte_limit].count(b"\n") + 1
        issues.append({"code": "size-bytes", "line": line, "byte": byte_limit,
                       "message": "UTF-8 byte budget exceeded; preserve necessary code/cleanup/evidence when splitting"})

    def link(dest, fragment, display, line, boundary):
        dest = dest.resolve()
        if not dest.is_relative_to(boundary.resolve()) or not dest.is_file():
            issues.append({"code": "link", "line": line, "message": f"missing/unsafe {display}"})
        elif fragment and dest.suffix == ".md" and unquote(fragment) not in headings(dest.read_text(encoding="utf-8")):
            issues.append({"code": "link-anchor", "line": line, "message": f"missing anchor {display}"})

    for number, line in enumerate(prose(text).splitlines(), 1):
        for target in re.findall(r"\[\[([^\]\n]+)\]\]", line):
            name, _, fragment = target.split("|", 1)[0].partition("#")
            dest = wiki_root / (name + ".md") if name else path
            link(dest, fragment, target, number, wiki_root)
        for target in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)", line):
            if urlsplit(target).scheme:
                continue  # Remote availability is not claimed by this checker.
            name, _, fragment = target.partition("#")
            dest = path.parent / unquote(name) if name else path
            link(dest, fragment, target, number, wiki_root.parent)
    return {"path": path.relative_to(wiki_root).as_posix(), "type": kind, "size": size,
            "passed": not issues, "issues": issues,
            "validation": "structure-only; no DST semantics, source anchors or runtime checked"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="*", type=Path)
    parser.add_argument("--wiki-root", type=Path, required=True)
    parser.add_argument("--format", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--check-indexes", action="store_true", help="also check navigation when checking selected drafts")
    args = parser.parse_args()
    pages = args.pages or wiki_files(args.wiki_root)
    limits = load_limits(args.format)
    size_classes = load_size_classes(args.format, limits)
    reports = [check_page(p, args.wiki_root, limits, args.source_root, args.format, size_classes) for p in pages]
    navigation = check_indexes(args.wiki_root) if not args.pages or args.check_indexes else None
    passed = all(r["passed"] for r in reports) and (navigation is None or navigation["passed"])
    print(json.dumps({"report_version": 2, "pages": reports, "navigation": navigation, "passed": passed,
                      "not_checked": ["DST semantics", "source line/hash anchors", "runtime"] +
                      ([] if navigation else ["navigation (selected draft mode)"])},
                     ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
