import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .cache import DATA_DIR, RAW_DIR

BUNDLE_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"


def default_db_path(data_dir=DATA_DIR):
    return Path(data_dir) / "papers.db"


def iter_bundle_files(data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    db_path = default_db_path(data_dir)

    if db_path.exists():
        yield db_path, Path("papers.db")

    raw_dir = data_dir / "raw"
    if raw_dir.exists():
        for path in sorted(raw_dir.rglob("*")):
            if path.is_file():
                yield path, Path("raw") / path.relative_to(raw_dir)


def build_bundle_manifest(entries):
    files = []
    total_bytes = 0
    for source_path, archive_path in entries:
        size = source_path.stat().st_size
        files.append({"path": archive_path.as_posix(), "size": size})
        total_bytes += size

    return {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
    }


def create_cache_bundle(output_path, data_dir=DATA_DIR):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    entries = list(iter_bundle_files(data_dir))
    manifest = build_bundle_manifest(entries)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))
        for source_path, archive_path in entries:
            bundle.write(source_path, archive_path.as_posix())

    return {
        "output_path": output_path,
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "archive_bytes": output_path.stat().st_size,
    }


def resolve_extract_path(data_dir, archive_name):
    data_dir = Path(data_dir).resolve()
    target = (data_dir / archive_name).resolve()
    if target != data_dir and data_dir not in target.parents:
        raise ValueError(f"Refusing to extract outside data directory: {archive_name}")
    return target


def install_cache_bundle(bundle_path, data_dir=DATA_DIR, replace=False):
    bundle_path = Path(bundle_path)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if replace:
        raw_dir = data_dir / "raw"
        if raw_dir.exists():
            shutil.rmtree(raw_dir)
        db_path = default_db_path(data_dir)
        if db_path.exists():
            db_path.unlink()

    extracted_files = 0
    manifest = None
    with zipfile.ZipFile(bundle_path, "r") as bundle:
        if MANIFEST_NAME in bundle.namelist():
            manifest = json.loads(bundle.read(MANIFEST_NAME).decode("utf-8"))

        for info in bundle.infolist():
            if info.is_dir() or info.filename == MANIFEST_NAME:
                continue
            target = resolve_extract_path(data_dir, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted_files += 1

    return {
        "bundle_path": bundle_path,
        "data_dir": data_dir,
        "extracted_files": extracted_files,
        "manifest": manifest,
    }
