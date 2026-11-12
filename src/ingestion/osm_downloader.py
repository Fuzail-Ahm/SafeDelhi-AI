"""
SafeDelhi AI — Geofabrik Northern Zone OSM PBF Downloader.

Downloads the Northern Zone PBF archive and corresponding MD5 checksum,
verifies file size, HTTP headers, and cryptographic integrity.
"""

import datetime
import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import requests

GEOFABRIK_NORTHERN_ZONE_URL = "https://download.geofabrik.de/asia/india/northern-zone-latest.osm.pbf"
GEOFABRIK_MD5_URL = "https://download.geofabrik.de/asia/india/northern-zone-latest.osm.pbf.md5"


def download_osm_pbf(
    source_url: str = GEOFABRIK_NORTHERN_ZONE_URL,
    md5_url: Optional[str] = GEOFABRIK_MD5_URL,
    output_path: str = "data/raw/osm/northern-zone-latest.osm.pbf",
    chunk_size: int = 1024 * 1024,  # 1 MB
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    Downloads an OSM PBF file while computing MD5 and SHA-256 on the fly.
    Verifies download against Content-Length and remote .md5 file if available.
    """
    dest_path = Path(output_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    download_start_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[{download_start_utc}] Initiating download from: {source_url}")

    # Session with standard headers
    session = requests.Session()
    session.headers.update({"User-Agent": "SafeDelhi-AI/1.0 (Public Research; Women Safety Analysis)"})

    # 1. Fetch remote MD5 if url provided
    expected_remote_md5 = None
    if md5_url:
        try:
            print(f"Fetching MD5 reference file: {md5_url}")
            resp_md5 = session.get(md5_url, timeout=30)
            if resp_md5.status_code == 200:
                parts = resp_md5.text.strip().split()
                if parts:
                    expected_remote_md5 = parts[0].strip()
                    print(f"Remote MD5 reference: {expected_remote_md5}")
        except Exception as e:
            print(f"Warning: Failed to fetch remote MD5 file: {e}")

    # 2. Stream download of PBF
    resp = session.get(source_url, stream=True, timeout=timeout)
    resp.raise_for_status()

    resolved_url = resp.url
    remote_last_modified = resp.headers.get("Last-Modified")
    remote_etag = resp.headers.get("ETag")
    content_length_header = resp.headers.get("Content-Length")
    expected_bytes = int(content_length_header) if content_length_header else None

    print(f"Resolved URL: {resolved_url}")
    print(f"Remote Last-Modified: {remote_last_modified}")
    print(f"Expected Size: {expected_bytes} bytes ({expected_bytes / (1024*1024):.2f} MB)" if expected_bytes else "Size unknown")

    md5_hasher = hashlib.md5()
    sha256_hasher = hashlib.sha256()
    bytes_downloaded = 0

    temp_dest = dest_path.with_suffix(".tmp")
    with open(temp_dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                md5_hasher.update(chunk)
                sha256_hasher.update(chunk)
                bytes_downloaded += len(chunk)
                if expected_bytes:
                    pct = (bytes_downloaded / expected_bytes) * 100
                    mb = bytes_downloaded / (1024 * 1024)
                    print(f"\rProgress: {mb:.1f} MB / {expected_bytes / (1024*1024):.1f} MB ({pct:.1f}%)", end="", flush=True)

    print()
    download_end_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    computed_md5 = md5_hasher.hexdigest()
    computed_sha256 = sha256_hasher.hexdigest()

    # Verify content length
    if expected_bytes is not None and bytes_downloaded != expected_bytes:
        temp_dest.unlink(missing_ok=True)
        raise IOError(f"Byte count mismatch: downloaded {bytes_downloaded} bytes, expected {expected_bytes}")

    # Verify MD5 against remote md5 file if fetched
    md5_matched = None
    if expected_remote_md5:
        md5_matched = (computed_md5.lower() == expected_remote_md5.lower())
        if not md5_matched:
            temp_dest.unlink(missing_ok=True)
            raise ValueError(f"MD5 mismatch! Computed: {computed_md5}, Remote: {expected_remote_md5}")

    # Atomic move to final destination
    temp_dest.replace(dest_path)
    print(f"Download complete: {dest_path} ({bytes_downloaded} bytes)")
    print(f"Computed MD5: {computed_md5}")
    print(f"Computed SHA-256: {computed_sha256}")

    metadata = {
        "source_url": source_url,
        "resolved_url": resolved_url,
        "download_started_utc": download_start_utc,
        "download_completed_utc": download_end_utc,
        "remote_last_modified": remote_last_modified,
        "remote_etag": remote_etag,
        "file_size_bytes": bytes_downloaded,
        "md5_checksum": computed_md5,
        "sha256_checksum": computed_sha256,
        "expected_remote_md5": expected_remote_md5,
        "md5_verified": md5_matched,
        "local_file_path": str(dest_path),
    }

    return metadata


if __name__ == "__main__":
    meta = download_osm_pbf()
    import json
    print(json.dumps(meta, indent=2))
