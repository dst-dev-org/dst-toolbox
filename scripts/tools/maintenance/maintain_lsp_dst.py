"""Clone or check the pinned maintained LSP-dst fork."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dst_paths import knowledge_root, source_root, catalog_root

REPO = Path(__file__).resolve().parents[3]
METADATA = REPO / "scripts/vendor/lsp-dst.json"
SOURCE_ROOT = None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    error = result.stderr.decode("utf-8", errors="replace").strip()
    require(result.returncode == 0, error or f"command failed with exit code {result.returncode}: {command[0]}")
    return result.stdout.decode("utf-8").replace("\r\n", "\n").strip()


def git(checkout, *args):
    return run(["git", "-C", str(checkout), *args])


def relative_path(root, path):
    require(path and not path.startswith("/") and ":" not in path and chr(92) not in path
            and all(p not in ("", ".", "..") for p in path.split("/")), "unsafe relative path")
    resolved = (root / path).resolve()
    require(resolved.is_relative_to(root.resolve()), "metadata path escapes root")
    return resolved


def load_metadata():
    meta = json.loads(METADATA.read_text(encoding="utf-8"))
    require(meta["format_version"] == 2, "unsupported maintenance metadata version")
    for key in ("fork_commit", "upstream_commit"):
        require(re.fullmatch(r"[a-f0-9]{40}", meta[key]), "pin requires full commit SHA")
    relative_path(REPO, meta["checkout_path"])
    return meta


def validate_checkout(checkout, meta, require_pin=True):
    require((checkout / ".git").is_dir(), "expected independent Git clone")
    require(git(checkout, "branch", "--show-current") == meta["local_branch"], "maintenance branch differs")
    if require_pin:
        require(git(checkout, "rev-parse", "HEAD") == meta["fork_commit"], "HEAD differs from fork pin; review and pin explicitly")
    require(not git(checkout, "status", "--porcelain"), "checkout has uncommitted changes; preserve and review before pinning")
    require(git(checkout, "remote", "get-url", "origin") == meta["fork_url"], "origin differs from maintained fork")
    require(git(checkout, "remote", "get-url", "upstream") == meta["upstream_url"], "upstream fetch URL differs")
    require(git(checkout, "remote", "get-url", "--push", "upstream") == "DISABLED", "upstream push must remain disabled")
    git(checkout, "merge-base", "--is-ancestor", meta["upstream_commit"], "HEAD")
    coverage = json.loads(relative_path(checkout, meta["coverage_path"]).read_text(encoding="utf-8"))
    require(coverage["upstream_commit"] == meta["upstream_commit"] and coverage["upstream_url"] == meta["upstream_url"], "fork coverage upstream base differs")
    raw_root = SOURCE_ROOT or source_root()
    build = (raw_root.parent / "BUILD.txt").read_text(encoding="utf-8").strip()
    print(run([sys.executable, str(checkout / "tools/check_reviews.py"),
               "--source-root", str(raw_root), "--build", build]))
    return coverage


def setup(checkout, meta, clone_from=None):
    if checkout.exists():
        validate_checkout(checkout, meta)
        return
    checkout.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "-c", "core.autocrlf=false", "clone", "--no-checkout", "--origin", "origin",
         clone_from or meta["fork_url"], str(checkout)])
    git(checkout, "config", "core.autocrlf", "false")
    git(checkout, "remote", "set-url", "origin", meta["fork_url"])
    git(checkout, "remote", "add", "upstream", meta["upstream_url"])
    git(checkout, "remote", "set-url", "--push", "upstream", "DISABLED")
    branches = git(checkout, "branch", "--format=%(refname:short)").splitlines()
    if meta["local_branch"] in branches:
        require(git(checkout, "rev-parse", meta["local_branch"]) == meta["fork_commit"], "cloned local branch differs from pin")
        git(checkout, "switch", meta["local_branch"])
    else:
        git(checkout, "switch", "--no-track", "-c", meta["local_branch"], meta["fork_commit"])
    git(checkout, "branch", "--set-upstream-to", f"origin/{meta['fork_branch']}", meta["local_branch"])
    validate_checkout(checkout, meta)


def pin(checkout, meta):
    coverage = validate_checkout(checkout, meta, require_pin=False)
    # Only published commits can become the dependency pin.
    git(checkout, "fetch", "origin", meta["fork_branch"])
    git(checkout, "merge-base", "--is-ancestor", "HEAD", f"origin/{meta['fork_branch']}")
    meta["fork_commit"] = git(checkout, "rev-parse", "HEAD")
    meta["validation"] = coverage["validation"]
    meta["coverage"] = coverage["coverage"]
    METADATA.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8", newline=chr(10))
    print(f"Pinned published fork commit {meta['fork_commit']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["setup", "check", "pin"])
    parser.add_argument("--checkout", type=Path, help="Alternate checkout for reconstruction checks")
    parser.add_argument("--clone-from", help="Optional local clone for reconstruction checks")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--knowledge-root", type=Path)
    args = parser.parse_args()
    global SOURCE_ROOT
    SOURCE_ROOT = source_root(args.source_root, args.knowledge_root)
    meta = load_metadata()
    checkout = (args.checkout or relative_path(REPO, meta["checkout_path"])).resolve()
    if args.operation == "setup":
        setup(checkout, meta, args.clone_from)
    elif args.operation == "pin":
        require(args.checkout is None, "pin requires canonical maintenance checkout")
        pin(checkout, meta)
    else:
        validate_checkout(checkout, meta)
    print("PASS: maintained fork checkout and item-level evidence; full library review remains incomplete")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
