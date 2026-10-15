"""Read-only checks for local inline Markdown links to Lua/PO source lines.

Encoding contract: pages must be UTF-8 (BOM tolerated); sources are read as
bytes and decoded UTF-8 first with a latin-1 fallback so stock files with
legacy bytes (e.g. copyright marks) still yield anchor line numbers. Both
sides split on physical CR/LF only, so Unicode separators never shift lines.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_text import physical_lines


# Inline destinations: angle brackets, escaped characters, or bare paths with
# one level of balanced parentheses. Reference-style links are outside scope.
LINK = re.compile(
    r'''(?<!!)\[(?:\\.|[^\]\\\n])*\]\(\s*'''
    r'''(<[^>\n]+>|(?:\\.|[^\\()\s]|\((?:\\.|[^\\()\s])*\))+)'''
    r'''(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^\n)]*\)))?\s*\)''')
LINE_ANCHOR = re.compile(r"L([0-9]+)(?:-L([0-9]+))?\Z")
STRUCTURAL = re.compile(r"(?:end\s*[),;]*|else|[{}][,;]?)\Z")
SOURCE_SUFFIXES = (".lua", ".po")


def prose_lines(text):
    """Mask comments/code without removing physical lines or moving links."""
    fence = None
    comment = False
    for number, line in enumerate(physical_lines(text), 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker and not comment:
            if fence is None:
                fence = (marker[1][0], len(marker[1]))
            elif (fence[0] == marker[1][0] and len(marker[1]) >= fence[1]
                  and not marker[2].strip()):
                fence = None
            continue
        if fence is None:
            masked = list(line)
            position = 0
            while position < len(line):
                if comment:
                    close = line.find("-->", position)
                    end = len(line) if close < 0 else close + 3
                    comment = close < 0
                else:
                    token = re.search(r"<!--|`+", line[position:])
                    if token is None:
                        break
                    position += token.start()
                    if token[0] == "<!--":
                        comment = True
                        continue
                    code_end = re.search(r"(?<!`)" + re.escape(token[0]) + r"(?!`)",
                                         line[position + len(token[0]):])
                    if code_end is None:
                        position += len(token[0])
                        continue
                    end = position + len(token[0]) + code_end.end()
                masked[position:end] = " " * (end - position)
                position = end
            yield number, "".join(masked)


def local_links(text):
    for number, line in prose_lines(text):
        for match in LINK.finditer(line):
            target = match[1]
            if target.startswith("<"):
                target = target[1:-1]
            target = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\1", target)
            parsed = urlsplit(target)
            if not parsed.scheme and not parsed.netloc and parsed.path:
                yield number, target, unquote(parsed.path), unquote(parsed.fragment)


def source_links(text, suffixes=SOURCE_SUFFIXES):
    """Select supported text links; callers may keep a narrower source scope."""
    for item in local_links(text):
        if Path(item[2]).suffix.lower() in suffixes:
            yield item


def binary_source(data):
    """Conservative byte signals, not a claim about all malformed text."""
    sample = data[:8192]
    return (sample.startswith((b"\x1bLua", b"\x89PNG\r\n\x1a\n", b"PK\x03\x04", b"\x7fELF"))
            or sample.count(b"\0") >= max(4, len(sample) // 100))


def context_lines(lines, start, end, radius):
    """Bound even very large cited ranges to the two endpoint neighborhoods."""
    numbers = set()
    for anchor in (start, end):
        numbers.update(range(max(1, anchor - radius), min(len(lines), anchor + radius) + 1))
    return [{"line": n, "text": lines[n - 1][:240], "clipped": len(lines[n - 1]) > 240}
            for n in sorted(numbers)]


def current_snapshot_version(knowledge_root):
    """Record current BUILD.txt as context, including when links use archives."""
    name = "raw/current/BUILD.txt"
    result = {"path": name, "value": None}
    try:
        result["value"] = (knowledge_root / name).read_text(encoding="utf-8-sig").strip()
        result["state"] = "recorded" if result["value"] else "empty"
    except FileNotFoundError:
        result["state"] = "missing"
    except (OSError, UnicodeError) as exc:
        result.update(state="unreadable", message=str(exc))
    return result


def scan(wiki_root, pages=None, *, context=2, max_issues=50, strict=False):
    wiki_root = Path(wiki_root).resolve()
    if not wiki_root.is_dir():
        raise ValueError("--wiki-root must be an existing directory")
    if not 0 <= context <= 5 or not 1 <= max_issues <= 1000:
        raise ValueError("context must be 0..5; max-issues must be 1..1000")
    if pages is None:
        # Knowledge and navigation only: no logs, archives, reports or output.
        pages = [wiki_root / "index.md"] if (wiki_root / "index.md").is_file() else []
        for category in ("cookbook", "reference"):
            pages.extend((wiki_root / category).rglob("*.md"))
    else:
        pages = [Path(p) if Path(p).is_absolute() else wiki_root / p for p in pages]
    pages = sorted({p.resolve() for p in pages})
    if not pages:
        raise ValueError("no Wiki Markdown pages selected")
    for path in pages:
        if not path.is_relative_to(wiki_root) or path.suffix.lower() != ".md":
            raise ValueError(f"select Markdown pages inside --wiki-root: {path}")

    counts = Counter(pages=len(pages), references=0, line_references=0, file_only=0,
                     errors=0, warnings=0, skipped_unsupported=0)
    codes, issues, targets, source_cache = Counter(), [], set(), {}
    source_encodings = {}
    by_page = {p.relative_to(wiki_root).as_posix(): Counter(references=0, errors=0, warnings=0)
               for p in pages}

    def issue(base, severity, code, message, lines=None, start=None, end=None):
        category = "errors" if severity == "error" else "warnings"
        counts[category] += 1
        by_page[base["page"]][category] += 1
        codes[code] += 1
        if len(issues) < max_issues:
            item = dict(base, severity=severity, code=code, message=message)
            if lines is not None:
                item["source_lines"] = len(lines)
                item["context"] = context_lines(lines, start, end, context)
            issues.append(item)

    for page in pages:
        name = page.relative_to(wiki_root).as_posix()
        try:
            text = page.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            issue({"page": name}, "error", "page-read", str(exc))
            continue
        for number, target, source_name, fragment in local_links(text):
            if Path(source_name).suffix.lower() not in SOURCE_SUFFIXES:
                counts["skipped_unsupported"] += 1
                continue
            counts["references"] += 1
            by_page[name]["references"] += 1
            counts["line_references" if fragment else "file_only"] += 1
            source = (page.parent / source_name).resolve()
            targets.add((source, fragment))
            base = {"page": name, "wiki_line": number, "target": target}
            if not source.is_relative_to(wiki_root.parent):
                issue(base, "error", "source-outside-root", "link leaves the knowledge root")
                continue
            base["source"] = source.relative_to(wiki_root.parent).as_posix()
            if not source.is_relative_to(wiki_root.parent / "raw"):
                issue(base, "warning", "source-outside-raw", "text source link is inside the knowledge root but outside raw/")
            if source not in source_cache:
                try:
                    data = source.read_bytes()
                except OSError as exc:
                    source_cache[source] = str(exc)
                else:
                    try:
                        source_text = data.decode("utf-8-sig")
                        encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"
                    except UnicodeDecodeError:
                        # Stock sources may embed non-UTF-8 bytes (latin-1 copyright marks);
                        # line structure stays intact, which is all anchor checks need.
                        source_text = data.decode("latin-1")
                        encoding = "latin-1"
                    source_encodings[source] = {"source": base["source"], "encoding": encoding,
                                                "fallback": encoding == "latin-1", "references": 0}
                    if binary_source(data):
                        issue(base, "warning", "source-binary", "source has a binary signature or many NUL bytes")
                    source_cache[source] = physical_lines(source_text)
            lines = source_cache[source]
            if isinstance(lines, str):
                issue(base, "error", "source-read", lines)
                continue
            source_encodings[source]["references"] += 1
            if not fragment:
                continue
            anchor = LINE_ANCHOR.fullmatch(fragment)
            if anchor is None:
                issue(base, "error", "source-fragment", "expected #L12 or #L12-L20")
                continue
            start, end = int(anchor[1]), int(anchor[2] or anchor[1])
            base["lines"] = [start, end]
            if start > end:
                issue(base, "error", "source-range", "reversed source range")
            elif not 1 <= start <= end <= len(lines):
                issue(base, "error", "source-line", f"range outside 1..{len(lines)}")
            else:
                if not lines[start - 1].strip():
                    issue(dict(base, anchor="start"), "warning", "source-blank",
                          "citation starts on a blank line; review its evidence", lines, start, end)
                elif source.suffix.lower() == ".lua" and STRUCTURAL.fullmatch(lines[start - 1].split("--", 1)[0].strip()):
                    issue(dict(base, anchor="start"), "warning", "source-structural",
                          "citation starts on a structural line; may be intentional", lines, start, end)
                if end != start and not lines[end - 1].strip():
                    issue(dict(base, anchor="end"), "warning", "source-end-blank",
                          "citation ends on a blank line; review its range", lines, start, end)

    total = counts["errors"] + counts["warnings"]
    problem_pages = sorted((dict(page=name, **values) for name, values in by_page.items()
                            if values["errors"] or values["warnings"]),
                           key=lambda item: (-item["errors"], -item["warnings"], item["page"]))
    return {"report_version": 1, "wiki_root": str(wiki_root),
            "current_snapshot_version": current_snapshot_version(wiki_root.parent),
            "counts": dict(counts, unique_targets=len(targets), source_files=len(source_cache)),
            "source_encodings": sorted(source_encodings.values(), key=lambda item: item["source"]),
            "by_code": dict(sorted(codes.items())), "issues": issues,
            "by_page": problem_pages[:max_issues], "problem_pages": len(problem_pages),
            "by_page_omitted": max(0, len(problem_pages) - max_issues),
            "truncated": total > len(issues), "omitted": total - len(issues),
            "strict": strict, "passed": counts["errors"] == 0 and (not strict or counts["warnings"] == 0),
            "not_checked": ["claim support / DST semantics", "source version/hash matches", "runtime",
                            "remote and reference-style links", "HTML links/autolinks",
                            "multiline/nested Markdown links and Windows drive-letter absolute destinations",
                            "bare file:line text", "frontmatter sources"],
            "parser_limits": ["indented code is not distinguished from prose; links may be checked",
                              "line-based Markdown subset; no complete syntax coverage",
                              "current_snapshot_version is context only, not the version of every linked source"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="*", type=Path, help="optional paths relative to --wiki-root, or absolute")
    parser.add_argument("--wiki-root", type=Path, required=True)
    parser.add_argument("--context", type=int, default=2, help="lines around each citation endpoint, 0..5")
    parser.add_argument("--max-issues", type=int, default=50, help="maximum issue details and problem-page rows, 1..1000; counts remain complete")
    parser.add_argument("--strict", action="store_true", help="also exit 1 for review warnings")
    args = parser.parse_args(argv)
    report = scan(args.wiki_root, args.pages or None, context=args.context,
                  max_issues=args.max_issues, strict=args.strict)
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
