"""Check and record the per-page source hash baseline for the shared knowledge wiki."""
import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dst_paths import knowledge_root, source_root

FLOW_LIST = re.compile(r"^\[.*\]$")
TOP_KEY = re.compile(r"^([A-Za-z][\w-]*):(?:\s+(.*))?$")
BAD_PATH = re.compile(r'[:"\'{}]|^\s|\s$')
MANIFEST_NAME = "source-baseline.json"
CACHE_NAME = "source-baseline-cache.json"
LOCK_NAME = ".source-baseline.lock"
RULE_VERSION = 2  # bump on check-semantics changes; stale clean caches from other versions must not pass


def normalize(data):
    """Semantic Lua content: strip BOM and newline-style differences."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").rstrip(b"\n")


def file_hashes(path):
    data = path.read_bytes()
    return sha256(data).hexdigest(), sha256(normalize(data)).hexdigest()


def combined_hash(files):
    """One digest per page over its sorted per-file normalized hashes."""
    joined = "\n".join(f"{path} {norm}" for path, (_, norm) in sorted(files.items()))
    return "sha256:" + sha256(joined.encode("utf-8")).hexdigest()


def snapshot_fingerprint(sroot):
    """Bind the check cache to the actual inputs: path, size and mtime of every file."""
    parts = []
    for path in sorted(sroot.rglob("*")):
        if path.is_file():
            stat = path.stat()
            parts.append(f"{path.relative_to(sroot).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}")
    return sha256("\n".join(parts).encode("utf-8")).hexdigest()


def snapshot_case_index(sroot):
    """Case-exact relative paths; tolerant filesystems would otherwise resolve a
    wrong-case citation against a differently named file without any signal."""
    try:
        return {p.relative_to(sroot).as_posix() for p in sroot.rglob("*") if p.is_file()}
    except OSError:
        return None


def wiki_fingerprint(pages, wiki_root, manifest):
    """Invalidate cached results when page bytes, membership or the baseline changes."""
    parts = [(page.relative_to(wiki_root).as_posix(),
              sha256(page.read_bytes()).hexdigest()) for page in pages]
    payload = {"pages": parts, "manifest": manifest}
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_flow_list(value, where):
    """Split one YAML flow sequence on top-level commas, honouring quotes."""
    inner = value.strip()[1:-1].strip()
    if not inner:
        return []
    items, buf, quote = [], "", None
    for char in inner:
        if quote:
            if char == quote:
                quote = None
            buf += char
        elif char in "\"'":
            quote = char
            buf += char
        elif char == ",":
            items.append(buf)
            buf = ""
        else:
            buf += char
    if quote is not None:
        raise ValueError(f"unclosed quote in flow list at {where}")
    items.append(buf)
    return [unquote(item) for item in items]


def parse_block(lines):
    """Strict YAML subset: top-level scalars, flow lists, block lists and one-level maps."""
    data, i = {}, 0
    while i < len(lines):
        line = lines[i].rstrip("\r\n")
        if not line.strip():
            i += 1
            continue
        key = TOP_KEY.match(line)
        if key is None:
            raise ValueError(f"expected a top-level key, got: {line.strip()[:60]}")
        name, rest = key[1], (key[2] or "").strip()
        if rest:
            if FLOW_LIST.match(rest):
                data[name] = parse_flow_list(rest, name)
            else:
                data[name] = unquote(rest)
            i += 1
            continue
        i += 1
        items, mapping, mode = [], {}, None
        while i < len(lines) and lines[i][:1] in (" ", "\t") and lines[i].strip():
            item = lines[i].strip()
            if item.startswith("- "):
                if mode == "map":
                    raise ValueError(f"mixed list and map under {name}")
                mode = "list"
                items.append(unquote(item[2:]))
            else:
                if mode == "list":
                    raise ValueError(f"mixed list and map under {name}")
                mode = "map"
                entry = re.match(r"^([^:]+):\s+(.*)$", item)
                if entry is None:
                    raise ValueError(f"expected 'key: value' under {name}, got: {item[:60]}")
                mapping[entry[1].strip()] = entry[2].strip()
            i += 1
        data[name] = mapping if mode == "map" else (items if items else None)
    return data


def load_page(path):
    """Return (data, text, bom, error); error is None for readable pages, else the reason."""
    try:
        original = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        return None, None, False, str(exc)
    bom = original.startswith(b"\xef\xbb\xbf")
    try:
        text = original[3:].decode("utf-8") if bom else original.decode("utf-8")
    except UnicodeError as exc:
        return None, None, bom, f"page is not valid UTF-8: {exc}"
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, bom, "no frontmatter"
    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if closing is None:
        return None, text, bom, "unterminated frontmatter"
    try:
        data = parse_block(lines[1:closing])
    except ValueError as exc:
        return None, text, bom, str(exc)
    if "sources" in data and not isinstance(data["sources"], list):
        return None, text, bom, "sources is not a list"
    return data, text, bom, None


def source_paths(values):
    """Normalise and bound sources to the snapshot layout; raise on paths we refuse to hash."""
    paths = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"non-path sources entry: {value!r}"[:80])
        path = value.strip().replace("\\", "/")
        if BAD_PATH.search(path) or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"source path outside snapshot layout: {value!r}"[:80])
        paths.append(path)
    return paths


def select_pages(wiki_root):
    """Knowledge and navigation only: no logs, archives or output."""
    pages = [wiki_root / "index.md"] if (wiki_root / "index.md").is_file() else []
    for category in ("cookbook", "reference"):
        pages.extend((wiki_root / category).rglob("*.md"))
    return sorted({page.resolve() for page in pages})


def resolve_selection(wiki_root, selected):
    pages = []
    for item in selected:
        path = Path(item)
        path = path.resolve() if path.is_absolute() else (wiki_root / path).resolve()
        if not path.is_relative_to(wiki_root) or path.suffix.lower() != ".md":
            raise ValueError(f"select Markdown pages inside the wiki root: {item}")
        if not path.is_file():
            raise ValueError(f"selected page does not exist: {item}")
        pages.append(path)
    if not pages:
        raise ValueError("selected page list is empty")
    return sorted(set(pages))


def acquire_lock(path, timeout=10.0, stale_seconds=300.0):
    """Serialize record writes: atomic replace alone cannot stop a stale read from
    clobbering another task's committed baseline."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(str(path)) > stale_seconds:
                    os.remove(str(path))
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)
        except OSError as exc:
            raise ValueError("could not create the baseline lock {}: {}".format(path, exc))


def snapshot_version(sroot, kroot):
    def read_build(path, name):
        result = {"path": name, "value": None}
        try:
            result["value"] = path.read_text(encoding="utf-8-sig").strip()
            result["state"] = "recorded" if result["value"] else "empty"
        except FileNotFoundError:
            result["state"] = "missing"
        except (OSError, UnicodeError) as exc:
            result.update(state="unreadable", message=str(exc))
        return result

    selected = read_build(sroot.parent / "BUILD.txt", "BUILD.txt beside the selected source root")
    try:
        selected["path"] = str((sroot.parent / "BUILD.txt").relative_to(kroot))
    except ValueError:
        pass
    selected["installed_current"] = read_build(kroot / "raw" / "current" / "BUILD.txt", "raw/current/BUILD.txt")
    return selected


def load_json(path, fallback):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return fallback, "missing"
    except (OSError, UnicodeError, ValueError) as exc:
        return fallback, f"unreadable: {exc}"
    if not isinstance(data, dict):
        return fallback, "malformed: expected a JSON object"
    return data, "ok"


def validate_manifest(manifest):
    """Check structures before their values reach the comparison and record paths."""
    if manifest.get("format_version") != 1 or not isinstance(manifest.get("pages"), dict):
        raise ValueError("expected format_version 1 and a pages object")
    for name, entry in manifest["pages"].items():
        if not isinstance(entry, dict):
            raise ValueError(f"page entry must be an object: {name}")
        sources, files = entry.get("sources"), entry.get("files")
        if not isinstance(sources, list) or any(not isinstance(p, str) for p in sources):
            raise ValueError(f"sources must be a string list: {name}")
        if not isinstance(files, dict) or set(files) != set(sources):
            raise ValueError(f"files must match sources: {name}")
        for path, hashes in files.items():
            if not isinstance(hashes, dict) or any(
                    not isinstance(hashes.get(key), str)
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", hashes[key])
                    for key in ("raw", "normalized")):
                raise ValueError(f"invalid source hash record: {name}: {path}")
        if not isinstance(entry.get("combined"), str) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", entry["combined"]):
            raise ValueError(f"invalid combined hash: {name}")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hash_block_span(lines, closing):
    start = next((i for i in range(1, closing)
                  if lines[i].rstrip("\r\n") == "source_hashes:"), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, closing)
                if lines[i][:1] not in (" ", "\t") and lines[i].strip()), closing)
    return start, end


def strip_hashes(path, text, bom):
    """Remove a legacy frontmatter source_hashes block; every other byte is preserved."""
    newline = "\r\n" if "\r\n" in text[:4000] else "\n"
    lines = text.splitlines(keepends=True)
    closing = next(i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---")
    span = hash_block_span(lines, closing)
    if span is None:
        return False
    start, end = span
    del lines[start:end]
    data = "".join(lines).encode("utf-8")
    path.write_bytes(b"\xef\xbb\xbf" + data if bom else data)
    return True


def append(bag, item, max_items):
    if len(bag) < max_items:
        bag.append(item)


def page_entry(now, sources, files):
    return {"updated": now.date().isoformat(), "sources": sources,
            "files": {path: {"raw": f"sha256:{raw}", "normalized": f"sha256:{norm}"}
                      for path, (raw, norm) in files.items()},
            "combined": combined_hash(files)}


def scan(mode, knowledge, source, config, *, selected=None, write=False,
         max_items=50, fresh_hours=24.0):
    kroot = knowledge_root(knowledge, config)
    sroot = source_root(source, knowledge=kroot)
    if not sroot.is_dir():
        raise ValueError("source root is not an accessible directory: {}".format(sroot))
    all_pages = select_pages(kroot / "wiki")
    if not all_pages:
        raise ValueError("no Wiki Markdown pages selected")
    scoped = bool(selected)
    pages = resolve_selection(kroot / "wiki", selected) if scoped else all_pages
    manifest_path = kroot / "wiki" / MANIFEST_NAME
    manifest, manifest_state = load_json(manifest_path, {"format_version": 1, "pages": {}})
    if manifest_state == "ok":
        try:
            validate_manifest(manifest)
        except ValueError as exc:
            manifest, manifest_state = {"format_version": 1, "pages": {}}, f"malformed: {exc}"
    cache_path = kroot / "output" / CACHE_NAME
    build = snapshot_version(sroot, kroot)
    now = datetime.now().astimezone()
    report = {"report_version": 3, "mode": mode, "write": bool(write and mode == "record"),
              "scoped": scoped, "knowledge_root": str(kroot), "source_root": str(sroot),
              "manifest": f"wiki/{MANIFEST_NAME}", "manifest_state": manifest_state,
              "cache": f"output/{CACHE_NAME}", "snapshot_version": build,
              "counts": {}, "notes": [], "passed": False}
    counts = {key: 0 for key in ("pages", "pages_with_sources", "pages_without_sources",
                                 "archived_pages", "removed_archived", "comparisons", "unchanged", "changed",
                                 "line_ending_only", "case_mismatch", "sources_changed", "deleted",
                                 "unrecorded_pages", "stale_entries", "legacy_frontmatter", "stripped",
                                 "already_recorded", "recorded", "refreshed", "affected_pages",
                                 "pages_skipped_missing_files", "missing_files",
                                 "invalid_pages")}
    classes = {name: [] for name in ("changed", "deleted", "line_ending_only", "case_mismatch",
                                     "sources_changed", "unrecorded_pages", "stale_entries",
                                     "skipped_missing_files", "invalid")}

    def invalid(name, message):
        counts["invalid_pages"] += 1
        append(classes["invalid"], {"page": name, "message": message}, max_items)

    if (mode == "check" or scoped) and manifest_state not in ("ok", "missing"):
        invalid("(manifest)", f"baseline manifest is {manifest_state}; "
                              "repair it manually or explicitly rebuild all pages with record --write; "
                              "scoped record cannot repair a damaged manifest")

    wiki_digest = None
    if mode == "check" and not scoped:
        wiki_digest = wiki_fingerprint(all_pages, kroot / "wiki", manifest)
        cache, cache_state = load_json(cache_path, {})
        try:
            age = (now - datetime.fromisoformat(cache["time"])).total_seconds() / 3600.0
        except (KeyError, TypeError, ValueError):
            age = None
        if (manifest_state == "ok" and not counts["invalid_pages"]
                and cache_state == "ok" and cache.get("passed") is True and age is not None
                and 0 <= age < fresh_hours and cache.get("build") == build.get("value")
                and cache.get("rule_version") == RULE_VERSION
                and cache.get("source_root") == str(sroot)
                and cache.get("wiki_fingerprint") == wiki_digest
                and cache.get("fingerprint") == snapshot_fingerprint(sroot)):
            report.update(cached=True, cache_age_hours=round(age, 2),
                          counts=counts, passed=True)
            report["notes"].append(f"baseline checked {round(age, 1)}h ago against the same "
                                   "snapshot; skipped, use --fresh-hours 0 to force")
            report.update(classes)
            return report
        report["cached"] = False

    planned, strip_pages, seen, archived = {}, [], set(), set()
    skipped_missing = set()
    case_index = snapshot_case_index(sroot)
    affected = {}

    def note_affected(page, kind):
        kinds = affected.setdefault(page, {})
        kinds[kind] = kinds.get(kind, 0) + 1
    for page in pages:
        name = page.relative_to(kroot / "wiki").as_posix()
        seen.add(name)
        counts["pages"] += 1
        data, text, bom, error = load_page(page)
        if data is None:
            if error == "no frontmatter":
                counts["pages_without_sources"] += 1
            else:
                invalid(name, error)
            continue
        if data.get("status") == "archived":
            counts["archived_pages"] += 1
            archived.add(name)
            continue
        if "sources" not in data or data["sources"] is None:
            counts["pages_without_sources"] += 1
            continue
        counts["pages_with_sources"] += 1
        if data.get("source_hashes"):
            counts["legacy_frontmatter"] += 1
        try:
            sources = source_paths(data["sources"])
        except ValueError as exc:
            invalid(name, str(exc))
            continue

        if mode == "record":
            # a wrong-case citation must never reach the manifest: on tolerant
            # filesystems it would silently hash a differently named file
            missing = [item for item in sources
                       if not (sroot / item).is_file()
                       or (case_index is not None and item not in case_index)]
            if missing:
                counts["pages_skipped_missing_files"] += 1
                counts["missing_files"] += len(missing)
                skipped_missing.add(name)
                append(classes["skipped_missing_files"],
                       {"page": name, "missing": missing}, max_items)
                continue
            files = {item: file_hashes(sroot / item) for item in sources}
            entry_files = {path: {"raw": f"sha256:{raw}", "normalized": f"sha256:{norm}"}
                           for path, (raw, norm) in files.items()}
            old = manifest["pages"].get(name)
            if old and old.get("sources") == sources and old.get("files") == entry_files:
                counts["already_recorded"] += 1
            else:
                counts["refreshed" if old else "recorded"] += 1
            planned[name] = page_entry(now, sources, files)
            if data.get("source_hashes"):
                strip_pages.append((page, text, bom))
            continue

        entry = manifest["pages"].get(name)
        if entry is None:
            counts["unrecorded_pages"] += 1
            append(classes["unrecorded_pages"], {"page": name}, max_items)
            continue
        if entry.get("sources") != sources:
            counts["sources_changed"] += 1
            append(classes["sources_changed"], {"page": name}, max_items)
            note_affected(name, "sources_changed")
            continue
        for item in sources:
            if not (sroot / item).is_file():
                counts["deleted"] += 1
                append(classes["deleted"], {"page": name, "source": item}, max_items)
                note_affected(name, "deleted")
                continue
            if case_index is not None and item not in case_index:
                counts["case_mismatch"] += 1
                append(classes["case_mismatch"], {"page": name, "source": item}, max_items)
                note_affected(name, "case_mismatch")
                continue
            current = file_hashes(sroot / item)
            recorded = entry.get("files", {}).get(item) or {}
            have_raw = (recorded.get("raw") or "").removeprefix("sha256:")
            have_norm = (recorded.get("normalized") or "").removeprefix("sha256:")
            counts["comparisons"] += 1
            if have_raw == current[0]:
                counts["unchanged"] += 1
            elif have_norm == current[1]:
                counts["line_ending_only"] += 1
                append(classes["line_ending_only"], {"page": name, "source": item}, max_items)
                note_affected(name, "line_ending_only")
            else:
                counts["changed"] += 1
                append(classes["changed"], {"page": name, "source": item,
                                            "recorded": f"sha256:{have_raw}",
                                            "current": f"sha256:{current[0]}"}, max_items)
                note_affected(name, "changed")

    if not scoped:
        for name in sorted(set(manifest["pages"]) - seen):
            counts["stale_entries"] += 1
            append(classes["stale_entries"], {"page": name}, max_items)

    if mode == "check":
        counts["affected_pages"] = len(affected)
        # the per-page drift queue is the version-maintenance work list, so it
        # stays complete regardless of --max-items detail capping
        classes["affected_pages"] = [{"page": page, **kinds}
                                     for page, kinds in sorted(affected.items())]
        report["passed"] = not (counts["changed"] or counts["deleted"]
                                or counts["case_mismatch"] or counts["sources_changed"]
                                or counts["stale_entries"] or counts["invalid_pages"])
        if (not scoped and report["passed"] and not counts["unrecorded_pages"]
                and manifest_state in ("ok", "missing")):
            try:
                write_json(cache_path, {"time": now.isoformat(timespec="seconds"),
                                        "build": build.get("value"),
                                        "source_root": str(sroot), "passed": True,
                                        "rule_version": RULE_VERSION,
                                        "wiki_fingerprint": wiki_digest,
                                        "fingerprint": snapshot_fingerprint(sroot)})
                report["cache_updated"] = True
            except OSError as exc:
                report["notes"].append(f"could not record the check cache: {exc}")
    else:
        report["passed"] = not counts["invalid_pages"]
        if write and report["passed"]:
            lock_path = kroot / "output" / LOCK_NAME
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            if not acquire_lock(lock_path):
                raise ValueError("another record holds the baseline lock; run records serially or clear the stale lock")
            try:
                # the manifest read at scan start may be stale: another task could have
                # committed its own record between that read and this lock, so re-read
                # under the lock and merge into the newest state
                fresh, fresh_state = load_json(manifest_path, None)
                if fresh_state == "ok":
                    try:
                        validate_manifest(fresh)
                    except ValueError as exc:
                        fresh_state = "malformed: {}".format(exc)
                if fresh_state == "ok":
                    counts["removed_archived"] = len(archived & set(fresh["pages"]))
                    merge_target = fresh
                elif not scoped:
                    # an explicit full rebuild is the documented repair path for a
                    # manifest that is missing or structurally broken
                    merge_target = {"format_version": 1, "pages": {}}
                elif fresh_state == "missing" and manifest_state == "missing":
                    merge_target = {"format_version": 1, "pages": {}}
                else:
                    raise ValueError("baseline manifest changed while recording ({}); scoped record does not "
                                     "overwrite it — repair the manifest or run an explicit full rebuild".format(fresh_state))
                for page, text, bom in strip_pages:
                    strip_hashes(page, text, bom)
                counts["stripped"] = len(strip_pages)
                if scoped:
                    for name in archived:
                        merge_target["pages"].pop(name, None)
                    merge_target["pages"].update(planned)
                else:
                    # keep old baselines only for pages skipped for missing sources, so the
                    # drift signal survives until they are re-verified or archived
                    kept = {name: entry for name, entry in merge_target["pages"].items()
                            if name in skipped_missing}
                    kept.update(planned)
                    merge_target["pages"] = kept
                    merge_target.pop("last_check", None)
                    merge_target["format_version"] = 1
                    merge_target["generated"] = now.date().isoformat()
                write_json(manifest_path, merge_target)
                try:
                    cache_path.unlink()
                except FileNotFoundError:
                    pass
            finally:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
        else:
            counts["removed_archived"] = len(archived & set(manifest["pages"]))

    if mode == "check" and counts["comparisons"]:
        rate = (counts["changed"] + counts["line_ending_only"]) / counts["comparisons"]
        report["raw_mismatch_rate"] = round(rate, 4)
        if rate > 0.5:
            report["notes"].append("over half of the recorded comparisons mismatch on raw bytes; "
                                   "verify the snapshot extraction before per-page review")
    report["counts"] = counts
    report.update(classes)
    report["not_checked"] = ["claim support / DST semantics",
                             "sources completeness (pages may cite fewer files than they depend on)",
                             "symbol-level change classification (git diff --no-index --ignore-cr-at-eol)",
                             "wiki body links to sources (validate_source_links)", "runtime"]
    report["parser_limits"] = ["strict YAML subset; anything else is reported invalid, not guessed",
                               "normalization covers BOM, CRLF/CR endings and trailing newlines only",
                               "source paths must match the snapshot case-exactly; tolerant "
                               "filesystems report case_mismatch instead of resolving another file",
                               "page frontmatter carries no hashes; the baseline lives in the manifest",
                               "archived pages keep their place and are excluded from drift and manifest",
                               "record without page selection rebuilds the whole manifest",
                               "record skips whole pages when any source file is missing from the snapshot"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "record"))
    parser.add_argument("pages", nargs="*", type=Path,
                        help="limit the run to these pages, relative to the wiki root or absolute; "
                             "record keeps every other baseline entry untouched")
    parser.add_argument("--knowledge-root", type=Path, help="absolute knowledge root; default reads the user config")
    parser.add_argument("--source-root", type=Path, help="scripts root to compare against; default <K>/raw/current/scripts")
    parser.add_argument("--config", type=Path, help="alternative user config for path resolution")
    parser.add_argument("--max-items", type=int, default=50, help="maximum details per class, 1..1000; counts remain complete")
    parser.add_argument("--fresh-hours", type=float, default=24.0,
                        help="skip an unscoped check when the last clean run is younger than this, 0 disables the cache")
    parser.add_argument("--write", action="store_true",
                        help="record mode: write the planned manifest update and strip legacy frontmatter blocks")
    args = parser.parse_args(argv)
    report = scan(args.mode, args.knowledge_root, args.source_root, args.config,
                  selected=args.pages or None, write=args.write,
                  max_items=args.max_items, fresh_hours=args.fresh_hours)
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(2)
