"""Validate authored layered navigation and build a separate Wiki search cache."""
import argparse
import os
from pathlib import Path
import sys
from wiki_data import REPO, build, encode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", type=Path, required=True)
    parser.add_argument("--format", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.output = args.output or args.wiki_root.resolve().parent / 'output/wiki/index.json'
    if args.output.resolve().is_relative_to(args.wiki_root.resolve()):
        raise ValueError("generated cache must stay outside authored Wiki")
    data = build(args.wiki_root, args.source_root, args.format)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(encode(data), encoding="utf-8", newline="\n")
    os.replace(temporary, args.output)
    print(encode({"passed": True, "output": str(args.output), "coverage": data["coverage"],
                  "navigation_checked": True, "authored_markdown_changed": False}), end="")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
