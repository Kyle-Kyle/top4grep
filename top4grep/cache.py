import hashlib
import json
import re
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
USER_AGENT = "top4grep/0.0.0 (+https://github.com/Kyle-Kyle/top4grep)"
HTTP_TIMEOUT_SECONDS = 15
TEXT_MISSING_SENTINEL = "__top4grep_missing__"
JSON_MISSING_SENTINEL = {"__top4grep_missing__": True}
MISSING = object()

DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)


def build_http_session():
    retry_policy = Retry(
        total=5,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry_policy)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
        }
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


HTTP = build_http_session()


def slugify(value, max_length=80):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-").lower()
    if not slug:
        slug = "item"
    return slug[:max_length]


def cache_key_path(root, key, suffix, hint=None):
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    stem = slugify(hint or key)
    return root / f"{stem}-{digest}{suffix}"


def read_text(path):
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if text == TEXT_MISSING_SENTINEL:
        return MISSING
    return text


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def read_bytes(path):
    if not path.exists():
        return None
    missing_path = path.with_suffix(f"{path.suffix}.missing")
    if missing_path.exists():
        return MISSING
    return path.read_bytes()


def write_bytes(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def read_json(path):
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data == JSON_MISSING_SENTINEL:
        return MISSING
    return data


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def cached_get_text(url, cache_path, timeout=HTTP_TIMEOUT_SECONDS):
    cached = read_text(cache_path)
    if cached is MISSING:
        return None
    if cached is not None:
        return cached

    response = HTTP.get(url, timeout=timeout)
    if response.status_code == 404:
        write_text(cache_path, TEXT_MISSING_SENTINEL)
        return None
    response.raise_for_status()
    write_text(cache_path, response.text)
    return response.text


def cached_get_json(url, cache_path, timeout=HTTP_TIMEOUT_SECONDS):
    cached = read_json(cache_path)
    if cached is MISSING:
        return None
    if cached is not None:
        return cached

    response = HTTP.get(url, timeout=timeout)
    if response.status_code == 404:
        write_json(cache_path, JSON_MISSING_SENTINEL)
        return None
    response.raise_for_status()
    data = response.json()
    write_json(cache_path, data)
    return data


def cached_get_bytes(url, cache_path, timeout=HTTP_TIMEOUT_SECONDS):
    cached = read_bytes(cache_path)
    if cached is MISSING:
        return None
    if cached is not None:
        return cached

    response = HTTP.get(url, timeout=timeout)
    if response.status_code == 404:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.with_suffix(f"{cache_path.suffix}.missing").write_text("", encoding="utf-8")
        return None
    response.raise_for_status()
    write_bytes(cache_path, response.content)
    return response.content
