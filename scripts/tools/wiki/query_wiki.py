"""Optional bounded Wiki lookup and actual chapter reading (no full-cache output)."""
import argparse
from pathlib import Path
import re
import sys
from wiki_data import REPO, bounded, brief, digest, load, page, safe_page


def words(text):
    text = text.lower()
    latin = re.findall(r"[a-z_][a-z_0-9]*(?:[.:][a-z_][a-z_0-9]*)*", text)
    # Ignore task framing in fuzzy matching; it must not recall a different object.
    for phrase in ("帮我", "我想", "修改已有", "新增一个", "如何", "怎么"):
        text = text.replace(phrase, " ")
    chinese = re.findall(r"[\u3400-\u9fff]+", text)
    return set(latin + [word[i:i + 2] for word in chinese for i in range(len(word) - 1)])


def score(query, fields):
    """Transparent lexical ranking: names/aliases before overlapping demand terms."""
    query = query.lower().strip()
    terms = words(query)
    best = 0
    for field, weight in fields:
        field = str(field).lower()
        if query and query == field:
            best = max(best, weight + 30)
        elif len(query) > 1 and query in field and (re.search(r"[\u3400-\u9fff]", query) or "/" in query):
            best = max(best, weight + 10)
        elif terms:
            overlap = len(terms & words(field)) / len(terms)
            if overlap:
                best = max(best, weight * overlap)
    return round(best, 3)


def candidate(record, chapter, hits, points, build):
    meta = record["meta"]
    cond = chapter["conditions"] or record["conditions"]
    return {"path": record["path"], "chapter": chapter["anchor"], "heading": chapter["title"],
            "lines": [chapter["start"], chapter["end"]], "type": meta["type"], "title": meta["title"],
            "summary": meta["summary"][:200], "conditions": brief(cond, 3, 300) or ["unknown; read applicable chapter"],
            "summary_clipped": len(meta["summary"]) > 200,
            "conditions_omitted": max(0, len(cond) - 3), "status": meta["status"],
            "conditions_clipped": any(len(v) > 300 for v in cond[:3]),
            "reliability": meta["reliability"], "dst_build": meta["dst_build"], "validation": meta["validation"],
            "source_version": "unknown" if not build else "match" if build == meta["dst_build"] else "mismatch",
            "evidence": brief(meta["sources"], 3), "evidence_total": len(meta["sources"]),
            "evidence_scope": "page sources; inspect chapter citations before using conclusions",
            "matched_goals": hits, "score": points}


def search(data, goals, *, limit=5, path=None, kind=None, history=False, build=None):
    if not 1 <= limit <= 50 or not 1 <= len(goals) <= 10:
        raise ValueError("limit must be 1..50; goals must be 1..10")
    found = {}
    goal_scores = {}
    for record in data["pages"]:
        meta = record["meta"]
        if (path and not record["path"].startswith(path)) or (kind and meta["type"] != kind):
            continue
        if meta["status"] == "archived" and not history:
            continue
        for i, goal in enumerate(goals):
            pagefields = [(record["path"], 60), (Path(record["path"]).stem, 60), (meta["title"], 60),
                          (meta["summary"], 20)] + [(alias, 45) for alias in meta["aliases"]]
            ranked = []
            for chapter in record["sections"]:
                # Chapter text/code is not copied into search cache. Explicit identifiers are searchable.
                local = score(goal, [(chapter["title"], 50)] +
                              [(v, 55) for v in chapter["identifiers"]] + [(v, 15) for v in chapter["conditions"]])
                points = max(score(goal, pagefields), local)
                if points >= 12:
                    # On a page-level hit prefer a useful short entry; on a symbol hit prefer interfaces.
                    priority = 2 if chapter["title"] in ("快速判断", "适用条件") else 1
                    if score(goal, [(chapter["title"], 50)]) and chapter["title"] not in ("快速判断", "适用条件"):
                        priority = 3
                    if goal in chapter["identifiers"] and chapter["title"] == "关键接口":
                        priority = 4
                    ranked.append((points, priority, local, -chapter["level"], -chapter["start"], chapter))
            if ranked:
                ranked.sort(key=lambda r: r[:5], reverse=True)
                points, _, _, _, _, chapter = ranked[0]
                key = (record["path"], chapter["anchor"])
                if key not in found:
                    found[key] = candidate(record, chapter, [], points, build)
                found[key]["matched_goals"].append(i)
                found[key]["score"] = max(points, found[key]["score"])
                goal_scores[(key, i)] = points
    # Round-robin top goal hits first, so a broad first goal cannot consume the entire shared budget.
    ranked = sorted(found.values(), key=lambda r: (-r["score"], r["path"], r["chapter"]))
    chosen = []
    for i in range(len(goals)):
        matches = sorted((r for r in ranked if i in r["matched_goals"]), key=lambda r:
                         -goal_scores[((r["path"], r["chapter"]), i)])
        best = matches[0] if matches else None
        if best and best not in chosen and len(chosen) < limit:
            chosen.append(best)
    for item in ranked:
        if item not in chosen and len(chosen) < limit:
            chosen.append(item)
    ambiguity = []
    for i in range(len(goals)):
        points = sorted([goal_scores[((r["path"], r["chapter"]), i)]
                         for r in ranked if i in r["matched_goals"]], reverse=True)
        if len(points) > 1 and points[0] == points[1]:
            ambiguity.append(i)
    return {"results": chosen, "matches_total": len(ranked), "ambiguous_goals": ambiguity,
            "truncated": len(ranked) > len(chosen), "omitted": len(ranked) - len(chosen)}


def read_chapter(wiki_root, target, build=None):
    name, _, anchor = target.partition("#")
    if not name.endswith(".md"):
        name += ".md"
    if not anchor:
        raise ValueError("read requires path#anchor; use full file reading for maintenance")
    path = safe_page(wiki_root.resolve(), name)
    raw = path.read_bytes()
    text = raw.decode("utf-8")  # Decode bytes directly: preserve CRLF when emitting actual ranges.
    meta, _ = page.metadata(text)
    chapters = page.sections(text)
    selected = next((s for s in chapters if s["anchor"] == anchor), None)
    if not selected:
        raise ValueError(f"missing chapter: {target}")
    if meta["type"] == "index":
        mandatory = []
    else:
        mandatory = [s for s in chapters if s["title"] in
                     ("快速判断", "适用条件", "验证记录", "边界与验证") and s["level"] == 2]
        if not any(s["title"] in ("验证记录", "边界与验证") for s in mandatory):
            raise ValueError(f"missing validation boundary: {name}; read full page and review")
    ranges = [(s["start"], s["end"]) for s in mandatory + [selected]]
    # Keep introductory prerequisites in ancestor sections, without emitting sibling cases.
    for ancestor in chapters:
        if 2 <= ancestor["level"] < selected["level"] and ancestor["start"] < selected["start"] <= ancestor["end"]:
            first_child = next(s for s in chapters if s["start"] > ancestor["start"] and s["level"] > ancestor["level"])
            ranges.append((ancestor["start"], first_child["start"] - 1))
    ranges.sort()
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    lines = text.splitlines(keepends=True)
    parts = [{"lines": [start, end], "text": "".join(lines[start - 1:end])} for start, end in merged]
    return {"path": name, "chapter": anchor, "metadata": meta, "sha256": digest(raw),
            "source_version": "unknown" if not build or meta["type"] == "index" else
                              "match" if build == meta["dst_build"] else "mismatch",
            "ranges": parts, "page_utf8_bytes": len(raw), "read_characters": sum(len(p["text"]) for p in parts),
            "complete_selected_ranges": True, "validation": "authored records; tool does not verify DST semantics"}


def read_targets(wiki_root, targets, build=None):
    """Same-page subgoals share metadata/mandatory boundaries and overlapping ranges."""
    grouped = {}
    for target in targets:
        item = read_chapter(wiki_root, target, build)
        if item["path"] not in grouped:
            item["chapters"] = [item.pop("chapter")]
            grouped[item["path"]] = item
            continue
        prior = grouped[item["path"]]
        if prior["sha256"] != item["sha256"]:
            raise ValueError("page changed during read; retry")
        if item["chapter"] not in prior["chapters"]:
            prior["chapters"].append(item["chapter"])
        spans = sorted([part["lines"] for part in prior["ranges"] + item["ranges"]])
        merged = []
        for start, end in spans:
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        raw = safe_page(wiki_root.resolve(), item["path"]).read_bytes()
        if digest(raw) != item["sha256"]:
            raise ValueError("page changed during read; retry")
        lines = raw.decode("utf-8").splitlines(keepends=True)
        prior["ranges"] = [{"lines": [start, end], "text": "".join(lines[start - 1:end])} for start, end in merged]
        prior["read_characters"] = sum(len(part["text"]) for part in prior["ranges"])
    return list(grouped.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=16000)
    parser.add_argument("--build", help="explicit version, e.g. steam-buildid:25643519; unknown if absent")
    modes = parser.add_subparsers(dest="mode", required=True)
    find = modes.add_parser("search")
    find.add_argument("goals", nargs="+")
    find.add_argument("--index", type=Path)
    find.add_argument("--limit", type=int, default=5)
    find.add_argument("--path")
    find.add_argument("--type", dest="kind", choices=list(page.TYPE_DIRECTORIES))
    find.add_argument("--history", action="store_true")
    read = modes.add_parser("read")
    read.add_argument("targets", nargs="+")
    args = parser.parse_args()
    if args.mode == 'search':
        args.index = args.index or args.wiki_root.resolve().parent / 'output/wiki/index.json'
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    report = {"report_version": 1, "mode": args.mode, "truncated": False, "omitted": 0}
    if args.mode == "search":
        if not 1 <= len(args.goals) <= 10 or not 1 <= args.limit <= 50:
            raise ValueError("limit must be 1..50; goals must be 1..10")
        data, changes = load(args.index, args.wiki_root)
        stale = any(changes.values())
        report.update({"index_state": "stale" if stale else "current", "coverage": data["coverage"],
                       "changes": {key: {"count": len(values), "sample": brief(values)} for key, values in changes.items()},
                       "results": [], "goals": brief(args.goals, 10, 300),
                       "goals_clipped": any(len(goal) > 300 for goal in args.goals),
                       "matching": "lexical (minimum score 12); candidate matches do not establish applicability"})
        if not stale:
            report.update(search(data, args.goals, limit=args.limit, path=args.path, kind=args.kind,
                                 history=args.history, build=args.build))
        report["next"] = "rebuild or search Markdown directly" if stale else "read selected chapters; gaps require targeted Wiki/source search"
    else:
        if not 1 <= len(args.targets) <= 5:
            raise ValueError("read accepts 1..5 chapters sharing one output budget")
        report.update({"results": read_targets(args.wiki_root, args.targets, args.build),
                       "index_state": "not-used; current Markdown read", "next": "inspect emitted ranges and citations; unreturned chapters remain unread"})
    rendered = bounded(report, args.max_bytes)
    print(rendered, end="")
    return 1 if report.get("index_state") == "stale" else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, page.yaml.YAMLError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
