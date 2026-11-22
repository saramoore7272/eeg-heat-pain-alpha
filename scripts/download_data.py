"""Download the pinned OpenNeuro subset and verify each file before using it."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.client import IncompleteRead
import json
from pathlib import Path, PurePosixPath
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "data" / "raw" / "ds008349-2.0.1"
MANIFEST_ROOT = ROOT / "data" / "manifests"
TREE_SHA = "3252827891885aa1890e6b1531a2d3aeefeaa5fd"
PILOT = ("pilot-download-manifest.json", "expanded-heat-download-manifest.json")
CONFIRMATION = ("confirmation-heat-download-manifest.json",)
GROUPS = {"demo": PILOT[:1], "pilot": PILOT, "confirmation": CONFIRMATION, "all": PILOT + CONFIRMATION}


def selection(group):
    entries, receipts = {}, {}
    for name in GROUPS[group]:
        content = (MANIFEST_ROOT / name).read_bytes()
        manifest = json.loads(content)
        if (manifest["dataset"], manifest["version"], manifest["tree_sha"]) != ("ds008349", "2.0.1", TREE_SHA):
            raise ValueError(f"Snapshot mismatch in {name}.")
        if group != "demo":
            receipts[name] = content
        for entry in manifest["files"]:
            path = entry["path"]
            if group == "demo" and "/" in path and not path.startswith("sub-086/eeg/sub-086_task-thermalactive_"):
                continue
            if path in entries and entries[path] != entry:
                raise ValueError(f"Conflicting snapshot entries for {path}.")
            entries[path] = entry
    return entries, receipts


def new_digest(entry):
    if entry["sha256"] is not None:
        return hashlib.sha256(), entry["sha256"]
    digest = hashlib.sha1()
    digest.update(f"blob {entry['bytes']}\0".encode("ascii"))
    return digest, entry["snapshot_blob_sha"]


def copy_and_check(stream, entry, destination=None):
    digest, expected = new_digest(entry)
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > entry["bytes"]:
            return False
        digest.update(chunk)
        if destination is not None:
            destination.write(chunk)
    return size == entry["bytes"] and digest.hexdigest() == expected


def is_verified(path, entry):
    if not path.is_file() or path.stat().st_size != entry["bytes"]:
        return False
    with path.open("rb") as handle:
        return copy_and_check(handle, entry)


def download(target, entry):
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        partial = None
        try:
            request = Request(entry["url"], headers={"User-Agent": "OpenNeuro-ds008349-2.0.1-project"})
            with urlopen(request, timeout=90) as response, tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{target.name}.", suffix=".part", dir=target.parent, delete=False,
            ) as handle:
                partial = Path(handle.name)
                if not copy_and_check(response, entry, handle):
                    raise ValueError(f"Downloaded bytes differ from the pinned snapshot: {entry['path']}")
            partial.replace(target)
            return
        except HTTPError as error:
            if attempt == 3 or (error.code != 429 and error.code < 500):
                raise
        except (URLError, TimeoutError, ConnectionError, IncompleteRead):
            if attempt == 3:
                raise
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)
        time.sleep(2**attempt)


def verify_entry(entry, destination, verify_only):
    relative = PurePosixPath(entry["path"])
    target = destination.joinpath(*relative.parts)
    if relative.is_absolute() or ".." in relative.parts or not target.resolve().is_relative_to(destination):
        raise ValueError(f"Invalid destination path for {entry['path']}.")
    if is_verified(target, entry):
        return False
    if verify_only:
        raise ValueError(f"Missing or changed: {entry['path']}")
    download(target, entry)
    if target.suffix == ".eeg":
        print(f"Downloaded and verified {entry['path']}", flush=True)
    return True


def write_receipt(target, content):
    if target.is_file() and target.read_bytes() == content:
        return
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".part", dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=GROUPS, default="confirmation",
                        help="Demo heat run, both pilot sets, the locked cohort, or all project recordings.")
    parser.add_argument("--destination", type=Path, default=DATASET_ROOT, help="Dataset directory.")
    parser.add_argument("--workers", type=int, default=6, choices=range(1, 13), metavar="1–12")
    parser.add_argument("--verify-only", action="store_true", help="Verify local files and receipts without downloading.")
    args = parser.parse_args()
    destination = args.destination.resolve()
    entries, receipts = selection(args.group)
    gigabytes = sum(entry["bytes"] for entry in entries.values()) / 1e9
    print(f"{args.group}: {len(entries)} files, {gigabytes:.2f} GB at {destination}", flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            fetched = sum(pool.map(lambda entry: verify_entry(entry, destination, args.verify_only), entries.values()))
        for name, content in receipts.items():
            target = destination / name
            if args.verify_only:
                if not target.is_file() or target.read_bytes() != content:
                    raise ValueError(f"Missing or changed receipt: {name}")
            else:
                write_receipt(target, content)
    except (OSError, ValueError, IncompleteRead) as error:
        parser.exit(1, f"Download or verification failed: {error}\n")
    print(f"Verified {len(entries)} files ({fetched} downloaded, {len(entries) - fetched} reused).")


if __name__ == "__main__":
    main()
