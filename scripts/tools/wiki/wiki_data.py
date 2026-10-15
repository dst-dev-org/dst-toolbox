"""Shared, rebuildable Wiki data. No source/AST/type-cache input."""
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verify"))
import validate_page as page

REPO = Path(__file__).resolve().parents[3]
VERSION = 1


def digest(raw):
    return sha256(raw).hexdigest()


def encode(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"


def safe_page(wiki_root, name):
    path = (wiki_root / name).resolve()
    if not path.is_relative_to(wiki_root.resolve()) or path.suffix != ".md":
        raise ValueError(f"unsafe Wiki path: {name}")
    if path not in page.wiki_files(wiki_root.resolve()):
        raise ValueError(f"not a knowledge/navigation page: {name}")
    return path


def identifiers(text):
    # Explicit inline identifiers and call spellings only, never inferred types/conditions.
    inline = re.findall(r"(?<!`)`([^`\n]+)`(?!`)", text)
    calls = re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)(?=\s*\()", text)
    return sorted({word for value in inline + calls for word in
                   re.findall(r"[A-Za-z_][A-Za-z_0-9]*(?:[.:][A-Za-z_][A-Za-z_0-9]*)*", value)})


def conditions(text):
    result, applicable = [], False
    for line in page.prose(text).splitlines():
        if re.match(r"^#{1,6}\s", line):
            applicable = bool(re.match(r"^##\s+适用条件\s*$", line))
        elif line.strip() and (applicable or re.match(
                r"\s*(?:[-*]\s*)?(?:\*\*)?(?:前提(?:与选择)?|适用条件|职责与适用|修改边界|生效与撤销)[：:]", line)):
            result.append(line.strip())
    return result


def inventory(wiki_root):
    return {p.relative_to(wiki_root).as_posix(): digest(p.read_bytes()) for p in page.wiki_files(wiki_root)}


def build(wiki_root, source_root=None, format_path=None):
    wiki_root = wiki_root.resolve()
    files = page.wiki_files(wiki_root)
    limits = page.load_limits(format_path)
    size_classes = page.load_size_classes(format_path, limits)
    reports = [page.check_page(p, wiki_root, limits, source_root, format_path, size_classes) for p in files]
    navigation = page.check_indexes(wiki_root)
    if not all(r["passed"] for r in reports) or not navigation["passed"]:
        raise ValueError(encode({"pages": [r for r in reports if not r["passed"]], "navigation": navigation}))
    records = []
    for path in files:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        meta, _ = page.metadata(text)
        if meta["type"] == "index":
            continue
        lines = text.splitlines(keepends=True)
        chapters = []
        for chapter in page.sections(text):
            if chapter["level"] < 2:
                continue
            content = "".join(lines[chapter["start"] - 1:chapter["end"]])
            chapters.append({**chapter, "identifiers": identifiers(content), "conditions": conditions(content)})
        records.append({"path": path.relative_to(wiki_root).as_posix(), "sha256": digest(raw),
                        "meta": meta, "identifiers": identifiers(text), "conditions": conditions(text),
                        "sections": chapters})
    data = {"index_version": VERSION, "inventory": inventory(wiki_root), "pages": records,
            "navigation": navigation,
            "coverage": {"knowledge_pages": len(records), "navigation_pages": navigation["indexes"],
                         "scope": "authored Wiki categories; not full DST source coverage"}}
    data["payload_sha256"] = digest(encode(data).encode("utf-8"))
    return data


def load(index, wiki_root):
    data = json.loads(index.read_text(encoding="utf-8"))
    if data.get("index_version") != VERSION:
        raise ValueError("unsupported Wiki index version; rebuild")
    expected = data.pop("payload_sha256", None)
    if expected != digest(encode(data).encode("utf-8")):
        raise ValueError("Wiki index integrity mismatch; rebuild")
    before, now = data["inventory"], inventory(wiki_root.resolve())
    changes = {"added": sorted(now.keys() - before.keys()), "removed": sorted(before.keys() - now.keys()),
               "changed": sorted(name for name in now.keys() & before.keys() if now[name] != before[name])}
    return data, changes


def bounded(report, max_bytes):
    """Limit the *entire* emitted JSON, never slice code or silently lose status."""
    if max_bytes < 2048:
        raise ValueError("max-bytes must be at least 2048 (status envelope)")
    report["output_bytes"] = 0
    while True:
        if report.get("mode") == "search":
            matched = {i for result in report["results"] for i in result["matched_goals"]}
            report["uncovered_goals"] = [i for i in range(len(report["goals"])) if i not in matched]
        encoded = encode(report)
        size = len(encoded.encode("utf-8"))
        if size <= max_bytes:
            if report["output_bytes"] == size:
                return encoded
            report["output_bytes"] = size
            continue
        report["truncated"] = True
        if report.get("results"):
            report["results"].pop()
            report["omitted"] = report.get("omitted", 0) + 1
        else:
            raise ValueError("status envelope exceeds max-bytes; narrow request or increase budget")


def brief(values, limit=10, width=160):
    return [str(value)[:width] for value in values[:limit]]
