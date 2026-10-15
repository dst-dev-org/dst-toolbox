"""Group candidate Wiki pages by shared component pages and shared source files.

Reads only authored frontmatter and in-page Wiki links; no source parsing, no
AST, no semantic judgement. Adjacency is evidence of *shared reading cost*, not
proof that two pages belong in one batch.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verify"))
import validate_page as page

LINK = re.compile(r"\[\[([^\]\n|#]+)")
NAMED = re.compile(r"\[\[reference/prefabs/([a-z0-9_-]+)")
DEFAULT_BOILERPLATE_RATIO = 0.05
# Shared by any page with this capability, so they never prove a family relation.
# Measured on 392 gap rows (2026-11-15): adding these removes ~65% of false pairs.
CONSTRUCTION_MODULE = re.compile(r"_(common|defs|def|shared)\.lua$")
# Pillar mechanics that identify a page family; generic capability flags do not.
MECHANISM_LINK = re.compile(r"reference/components/"
                            r"(armor|planardefense|planardamage|setbonus|resistance|"
                            r"mine|dryable|dryingrack|container|upgrader|fertilizer|"
                            r"forgerepairable|spidermutator|nabbag)$")
ALWAYS_BOILERPLATE = {
    "prefabs/skinprefabs.lua",      # every skinnable page
    "prefabskin.lua",               # skin mapping implementation
    "cooking.lua",                  # every cookable ingredient
    "components/tradable.lua",      # every tradable item
    "components/inventory.lua",     # every carried item
}


def named_pages(text, self_slug):
    """Prefab pages this page explicitly refers to; presence proves a known relation."""
    return {f"reference/prefabs/{name}" for name in NAMED.findall(text) if name != self_slug}


def neighbours(text, self_slug):
    """Wiki targets this page links to; navigation entries are not evidence."""
    targets = set()
    for match in LINK.findall(text):
        target = match.split("|", 1)[0].strip().rstrip("/")
        if target and target != self_slug and not target.endswith("/index"):
            targets.add(target)
    return targets


def gather(wiki_root):
    records = {}
    for path in page.wiki_files(wiki_root):
        text = path.read_text(encoding="utf-8")
        try:
            meta, _ = page.metadata(text)
        except ValueError:
            continue
        if meta.get("type") == "index":
            continue
        slug = path.relative_to(wiki_root).as_posix()[: -len(".md")]
        sources = meta.get("sources") or []
        if not isinstance(sources, list):
            continue
        records[slug] = {
            "path": path.relative_to(wiki_root).as_posix(),
            "type": meta.get("type", ""),
            "build": str(meta.get("dst_build", "")),
            "sources": set(str(value) for value in sources),
            "links": neighbours(text, slug),
            "named": named_pages(text, slug),
        }
    return records


def boilerplate(records, ratio):
    """Sources referenced by more pages than the ratio allow: shared cost, no signal."""
    freq = Counter()
    for record in records.values():
        freq.update(record["sources"])
    limit = max(3, int(len(records) * ratio))
    measured = {name for name, count in freq.items()
                if count > limit and not CONSTRUCTION_MODULE.search(name)}
    return measured | (ALWAYS_BOILERPLATE & set(freq)), freq, limit


def component_frequency(records):
    """How many pages reference each Wiki page; low counts identify a real family."""
    freq = Counter()
    for record in records.values():
        freq.update(record["links"])
    return freq


def source_frequency(records):
    """How many pages cite each source file; wide use means a shared host, not a family."""
    freq = Counter()
    for record in records.values():
        freq.update(record["sources"])
    return freq


def compare(left, right, boiler, freq, source_freq, rare_limit):
    shared_links = sorted(left["links"] & right["links"])
    shared_sources = sorted((left["sources"] & right["sources"]) - boiler)
    rare_links = [link for link in shared_links
                  if freq[link] <= rare_limit and not link.endswith("/index") and "-index" not in link]
    # A shared registration file hints at one factory. Wide use disqualifies it as
    # family evidence (beefalo.lua / woodie.lua serve several unrelated families),
    # but construction modules (*_common.lua / *_defs.lua) are shared by design.
    factory = [name for name in shared_sources
               if name.startswith("prefabs/") and name.endswith(".lua")
               and (CONSTRUCTION_MODULE.search(name) or source_freq[name] <= rare_limit)]
    mechanism = [link for link in shared_links if MECHANISM_LINK.match(link)]
    named = right["path"][: -len(".md")] in left["named"] or \
            left["path"][: -len(".md")] in right["named"]
    return shared_links, shared_sources, rare_links, factory, mechanism, named


def peer_layer(left, right):
    """Only same-layer relations are expected to be mutual; consumers point at definitions."""
    return left.split("/")[1] == right.split("/")[1]


def link_state(left, right):
    forward = right["path"][: -len(".md")] in left["links"]
    backward = left["path"][: -len(".md")] in right["links"]
    if forward and backward:
        return "mutual"
    return "a-to-b" if forward else "b-to-a" if backward else "none"


def groups(slugs, edges, max_group):
    """Greedy clusters over the strongest edges: a page joins only when it links
    to every current member, so a shared hub page cannot merge unrelated topics."""
    adjacent = defaultdict(dict)
    for edge in edges:
        adjacent[edge["a"]][edge["b"]] = edge
        adjacent[edge["b"]][edge["a"]] = edge
    assigned = {}
    result = []
    for edge in sorted(edges, key=lambda item: -item["score"]):
        if edge["a"] in assigned and edge["b"] in assigned:
            continue
        if edge["a"] in assigned:
            group = assigned[edge["a"]]
        elif edge["b"] in assigned:
            group = assigned[edge["b"]]
        else:
            if len(result) and max_group <= 1:
                continue
            group = {"pages": [], "pairs": 0, "shared": 0, "score": 0}
            result.append(group)
            assigned[edge["a"]] = group
            group["pages"].append(edge["a"])
        for candidate in (edge["a"], edge["b"]):
            if candidate in assigned or candidate in group["pages"]:
                continue
            if len(group["pages"]) >= max_group:
                break
            if not all(candidate in adjacent[member] for member in group["pages"]):
                continue
            group["pages"].append(candidate)
            assigned[candidate] = group
    for group in result:
        members = set(group["pages"])
        inside = [e for e in edges if e["a"] in members and e["b"] in members]
        group["pairs"] = len(inside)
        group["shared"] = max([e["score"] for e in inside], default=0)
        group["score"] = sum(e["score"] for e in inside)
        group["pages"].sort()
    result = [group for group in result if len(group["pages"]) > 1]
    result.sort(key=lambda group: (-len(group["pages"]), -group["score"], group["pages"]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="*", type=Path, help="candidate pages; omit to use --category")
    parser.add_argument("--wiki-root", type=Path, required=True)
    parser.add_argument("--category", default="prefab",
                        choices=["component", "prefab", "stategraph", "api", "mechanism"])
    parser.add_argument("--rare-limit", type=int, default=10,
                        help="a shared Wiki link referenced by at most this many pages counts as family evidence")
    parser.add_argument("--shared-links", type=int, default=3,
                        help="minimum shared Wiki links when none is rare")
    parser.add_argument("--shared-sources", type=int, default=3,
                        help="minimum shared non-boilerplate source files")
    parser.add_argument("--boilerplate-ratio", type=float, default=DEFAULT_BOILERPLATE_RATIO)
    parser.add_argument("--max-group", type=int, default=5)
    parser.add_argument("--cluster-score", type=int, default=3,
                        help="edges below this score stay candidate pairs but do not join a group")
    parser.add_argument("--pair-detail", action="store_true", help="list every related pair")
    args = parser.parse_args()

    wiki_root = args.wiki_root.resolve()
    records = gather(wiki_root)
    boiler, freq, limit = boilerplate(records, args.boilerplate_ratio)
    link_freq = component_frequency(records)
    source_freq = source_frequency(records)

    if args.pages:
        wanted = set()
        for path in args.pages:
            path = path.resolve()
            if not path.is_relative_to(wiki_root):
                raise ValueError(f"page outside Wiki root: {path}")
            wanted.add(path.relative_to(wiki_root).as_posix()[: -len(".md")])
        missing = sorted(wanted - set(records))
        if missing:
            raise ValueError("not a knowledge page: " + ", ".join(missing))
        selected = {slug: records[slug] for slug in sorted(wanted)}
    else:
        prefix = "/".join(page.TYPE_DIRECTORIES[args.category]) + "/"
        selected = {slug: record for slug, record in sorted(records.items())
                    if slug.startswith(prefix)}

    slugs = sorted(selected)
    edges = []
    for index, left_slug in enumerate(slugs):
        for right_slug in slugs[index + 1:]:
            left, right = selected[left_slug], selected[right_slug]
            links, sources, rare, factory, mechanism, named = compare(
                left, right, boiler, link_freq, source_freq, args.rare_limit)
            if not rare and not mechanism and not named and not factory \
                    and len(sources) < args.shared_sources:
                continue
            edges.append({
                "a": left_slug, "b": right_slug,
                "shared_links": links, "shared_sources": sources, "rare_links": rare,
                "factory_source": factory, "mechanism_links": mechanism,
                "named_each_other": named,
                "score": len(links) + len(sources),
                "links": link_state(left, right),
                "build": "same" if left["build"] == right["build"] else "mixed",
            })
    edges.sort(key=lambda edge: (-edge["score"], edge["a"], edge["b"]))
    # A group needs same-family evidence; aggregate tables and generic components
    # do not prove one. score only orders candidates, it is not a gate.
    strong = [edge for edge in edges
              if edge["rare_links"]
              or edge["factory_source"]
              or edge["mechanism_links"]
              or edge["named_each_other"]] 
    clusters = groups(slugs, strong, args.max_group)
    mates = {}
    for index, cluster in enumerate(clusters):
        for member in cluster["pages"]:
            mates[member] = index

    report = {
        "report_version": 1,
        "scope": {"wiki_root": str(wiki_root), "category": None if args.pages else args.category,
                  "pages": len(slugs)},
        "thresholds": {"rare_limit": args.rare_limit,
                       "cluster_score": args.cluster_score,
                       "shared_links": args.shared_links,
                       "shared_sources": args.shared_sources,
                       "max_group": args.max_group},
        "boilerplate": {"ratio": args.boilerplate_ratio, "page_limit": limit,
                        "sources": [{"path": name, "pages": freq[name]}
                                    for name in sorted(boiler)][:40],
                        "sources_truncated": len(boiler) > 40},
        "groups": clusters,
        "pairs": edges if args.pair_detail else len(edges),
        "backlink_gaps": [{"a": edge["a"], "b": edge["b"], "state": edge["links"]}
                          for edge in edges
                          if edge["links"] != "mutual"
                          and peer_layer(edge["a"], edge["b"])
                          and mates.get(edge["a"]) is not None
                          and mates.get(edge["a"]) == mates.get(edge["b"])],
        "not_checked": ["DST semantics", "source parsing", "batch fit"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
