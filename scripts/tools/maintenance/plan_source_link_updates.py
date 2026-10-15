"""Read-only Lua citation relocation plan; no semantic or version approval."""
import argparse
from collections import Counter
import difflib
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verify"))
from validate_source_links import LINK, LINE_ANCHOR, STRUCTURAL, prose_lines, source_links


def absolute_directory(value, label):
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f"{label} must be an accessible absolute directory")
    return path.resolve()


def exact_case(root, relative):
    """Do not silently accept a different filename on Windows."""
    path = root
    for part in relative.parts:
        if not path.is_dir() or part not in {child.name for child in path.iterdir()}:
            return False
        path = path / part
    return True


def occurrences(lines, fragment):
    """Stop at the second match: only uniqueness matters."""
    count = 0
    for i in range(len(lines) - len(fragment) + 1):
        if lines[i:i + len(fragment)] == fragment:
            count += 1
            if count == 2:
                break
    return count


def context_code_flags(lines):
    """Identify real code outside Lua comments/strings without parsing an AST."""
    flags = []
    long_close = None
    quote = None
    for line in lines:
        code = []
        pos = 0
        while pos < len(line):
            if long_close is not None:
                end = line.find(long_close, pos)
                if end < 0:
                    break
                pos = end + len(long_close)
                long_close = None
            elif quote is not None:
                if line[pos] == "\\":
                    pos += 2
                elif line[pos] == quote:
                    quote = None
                    pos += 1
                else:
                    pos += 1
            elif line.startswith("--", pos):
                opening = re.match(r"\[(=*)\[", line[pos + 2:])
                if opening is None:
                    break
                long_close = "]" + opening[1] + "]"
                pos += 2 + len(opening[0])
                code.append(" ")
            elif line[pos] in ("'", '"'):
                quote = line[pos]
                pos += 1
                code.append(" ")
            else:
                opening = re.match(r"\[(=*)\[", line[pos:]) if line[pos] == "[" else None
                if opening:
                    long_close = "]" + opening[1] + "]"
                    pos += len(opening[0])
                    code.append(" ")
                else:
                    code.append(line[pos])
                    pos += 1
        visible = "".join(code).strip()
        flags.append(bool(visible) and STRUCTURAL.fullmatch(visible) is None)
    return flags


def locate(old, new, blocks, start, end, *, code_flags=None):
    if not 1 <= start <= end <= len(old):
        return None, "old-range-invalid"
    if old == new:
        return (start, end), "same-lines"
    first = old[start - 1].strip()
    if not first or STRUCTURAL.fullmatch(first.split("--", 1)[0].strip()):
        return None, "weak-old-anchor"
    block = next((b for b in blocks if b.a <= start - 1 and end <= b.a + b.size), None)
    if block is None:
        return None, "changed-or-cross-hunk"
    if block.a == start - 1 or block.a + block.size == end:
        return None, "insufficient-context"
    # A matching end/return in a repeated block is not a reliable relocation.
    # Expand context only within the equal block; never ignore changed lines.
    if code_flags is None:
        code_flags = context_code_flags(old)
    for radius in (2, 4, 8, 16):
        left = max(block.a, start - 1 - radius)
        right = min(block.a + block.size, end + radius)
        meaningful = any(code_flags[left:start - 1]) or any(code_flags[end:right])
        if not meaningful:
            continue
        context = old[left:right]
        if occurrences(old, context) == occurrences(new, context) == 1:
            offset = block.b - block.a
            return (start + offset, end + offset), "unique-equal-block"
    return None, "ambiguous-or-insufficient-context"


def scan(wiki_root, old_source_root, new_source_root, pages, *,
         max_items=50, include_patch=False):
    if not 1 <= max_items <= 1000:
        raise ValueError("max-items must be between 1 and 1000")
    wiki = absolute_directory(wiki_root, "wiki-root")
    old_root = absolute_directory(old_source_root, "old-source-root")
    new_root = absolute_directory(new_source_root, "new-source-root")
    if old_root == new_root:
        raise ValueError("old and new source roots must differ")
    raw = (wiki.parent / "raw").resolve()
    if not new_root.is_relative_to(raw):
        raise ValueError("new-source-root must be inside the knowledge root raw/")
    selected = []
    for value in pages:
        path = (wiki / value).resolve()
        if not path.is_relative_to(wiki) or path.suffix != ".md" or not path.is_file():
            raise ValueError(f"page must be an existing Markdown file inside wiki-root: {value}")
        if path not in selected:
            selected.append(path)
    if not selected:
        raise ValueError("select at least one page")

    counts = Counter(references=0, file_only=0, unchanged=0, proposed=0,
                     review=0, errors=0, skipped_other_snapshot=0)
    issues, proposals, by_page, patch = [], [], [], []
    pairs = {}
    fingerprint = sha256()

    def problem(base, code, severity="review"):
        counts[severity] += 1
        if len(issues) < max_items:
            issues.append(dict(base, code=code, severity=severity))

    def read_pair(relative):
        key = relative.as_posix()
        if key not in pairs:
            older, newer = (old_root / relative).resolve(), (new_root / relative).resolve()
            if not older.is_relative_to(old_root) or not newer.is_relative_to(new_root):
                pairs[key] = (None, "source-outside-snapshot")
            elif not exact_case(new_root, relative):
                pairs[key] = (None, "new-source-missing-or-case")
            elif not exact_case(old_root, relative):
                pairs[key] = (None, "old-source-missing-or-case")
            else:
                try:
                    a, b = older.read_bytes(), newer.read_bytes()
                    old = a.decode("utf-8-sig").splitlines()
                    new = b.decode("utf-8-sig").splitlines()
                    blocks = ([] if old == new else
                              difflib.SequenceMatcher(None, old, new, autojunk=False).get_matching_blocks())
                    pairs[key] = ((old, new, blocks, context_code_flags(old) if old != new else None), None)
                    fingerprint.update(json.dumps([key, sha256(a).hexdigest(),
                                                   sha256(b).hexdigest()]).encode())
                except (OSError, UnicodeError):
                    pairs[key] = (None, "source-read")
        return pairs[key]

    for page in selected:
        name = page.relative_to(wiki).as_posix()
        before_counts = counts.copy()
        try:
            raw_page = page.read_bytes()
            text = raw_page.decode("utf-8-sig")
        except (OSError, UnicodeError):
            problem({"page": name}, "page-read", "errors")
            by_page.append({"page": name, "errors": 1})
            continue
        fingerprint.update(json.dumps([name, sha256(raw_page).hexdigest()]).encode())
        lines = text.splitlines()
        changes = {}
        for number, prose in prose_lines(text):
            for match in LINK.finditer(prose):
                parsed = list(source_links(match[0]))
                if not parsed:
                    continue
                _, target, source_name, fragment = parsed[0]
                counts["references"] += 1
                base = {"page": name, "wiki_line": number, "target": target}
                # resolve() may canonicalize filename case on Windows. Keep
                # the lexical spelling for the separate exact-case check.
                lexical = Path(os.path.abspath(page.parent / source_name))
                source = lexical.resolve()
                if not source.is_relative_to(raw):
                    problem(base, "source-outside-raw", "errors")
                    continue
                if not source.is_relative_to(new_root):
                    counts["skipped_other_snapshot"] += 1
                    continue
                relative = (lexical.relative_to(new_root) if lexical.is_relative_to(new_root)
                            else source.relative_to(new_root))
                base["source"] = relative.as_posix()
                data, error = read_pair(relative)
                if error:
                    problem(base, error, "review" if error.startswith("old-") else "errors")
                    continue
                if not fragment:
                    counts["file_only"] += 1
                    continue
                anchor = LINE_ANCHOR.fullmatch(fragment)
                if anchor is None:
                    problem(base, "source-fragment", "errors")
                    continue
                start, end = int(anchor[1]), int(anchor[2] or anchor[1])
                base["old_lines"] = [start, end]
                mapped, reason = locate(*data[:3], start, end, code_flags=data[3])
                if mapped is None:
                    problem(base, reason)
                    continue
                if mapped == (start, end):
                    counts["unchanged"] += 1
                    continue
                first, last = mapped
                new_fragment = f"L{first}" + (f"-L{last}" if anchor[2] else "")
                destination = match[1]
                prefix, _, _ = destination.rpartition("#")
                replacement = prefix + "#" + new_fragment + (">" if destination.startswith("<") else "")
                counts["proposed"] += 1
                if len(proposals) < max_items:
                    proposals.append(dict(base, new_lines=[first, last],
                                          new_fragment=new_fragment, evidence=reason))
                changes.setdefault(number - 1, []).append((*match.span(1), replacement))
        new_lines = list(lines)
        for number, edits in changes.items():
            for start, end, replacement in reversed(edits):
                new_lines[number] = new_lines[number][:start] + replacement + new_lines[number][end:]
        if changes and include_patch:
            # apply_patch implementations may normalize line endings/BOM/EOF.
            # Keep useful line proposals, but do not promise byte preservation
            # for a page format the text patch transport cannot guarantee.
            if b"\r" in raw_page:
                problem({"page": name}, "patch-line-endings")
            elif raw_page.startswith(b"\xef\xbb\xbf") or not raw_page.endswith(b"\n"):
                problem({"page": name}, "patch-page-format")
            else:
                hunks = list(difflib.unified_diff(lines, new_lines, n=2, lineterm=""))[2:]
                patch.append("*** Update File: " + page.relative_to(wiki.parent).as_posix())
                patch.extend("@@" if h.startswith("@@") else h for h in hunks)
        by_page.append({"page": name, "sha256": sha256(raw_page).hexdigest(),
                        **{k: counts[k] - before_counts[k] for k in counts}})

    total_issues = counts["review"] + counts["errors"]
    report = {"report_version": 2, "wiki_root": str(wiki), "patch_root": str(wiki.parent),
              "old_source_root": str(old_root), "new_source_root": str(new_root),
              "input_fingerprint": fingerprint.hexdigest(),
              "counts": dict(counts, pages=len(selected), source_pairs=len(pairs)),
              "by_page": by_page, "proposals": proposals, "issues": issues,
              "proposals_omitted": counts["proposed"] - len(proposals),
              "issues_omitted": total_issues - len(issues),
              "mechanical_passed": total_issues == 0,
              "not_checked": ["claim support / DST semantics", "undeclared dependencies",
                              "enclosing function identity / code movement semantics",
                              "old snapshot matches the page's verified sources/build",
                              "non-inline/source_links parser-excluded citations", "runtime",
                              "historical/other-snapshot links (preserved, not relocated)"],
              "writes": "none; no source, page, baseline, metadata or cache is modified"}
    if include_patch:
        report["patch"] = ("*** Begin Patch\n" + "\n".join(patch) + "\n*** End Patch\n") if patch else ""
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", required=True, type=Path)
    parser.add_argument("--old-source-root", required=True, type=Path)
    parser.add_argument("--new-source-root", required=True, type=Path)
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--include-patch", action="store_true", help="include complete apply_patch preview for safe relocations")
    parser.add_argument("pages", nargs="+", type=Path, help="selected pages, absolute or relative to wiki-root")
    args = parser.parse_args(argv)
    report = scan(args.wiki_root, args.old_source_root, args.new_source_root, args.pages,
                  max_items=args.max_items, include_patch=args.include_patch)
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["mechanical_passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
