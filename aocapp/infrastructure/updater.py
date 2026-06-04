"""GitHub release lookup and platform asset matching using requests."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

import requests
from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)


class UpdateError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        status: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.body = body

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.url:
            parts.append(f"URL: {self.url}")
        if self.status is not None:
            parts.append(f"HTTP: {self.status}")
        if self.body:
            snippet = self.body
            if len(snippet) > 800:
                snippet = snippet[:800] + "..."
            parts.append(f"Body: {snippet}")
        return "\n".join(parts)


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int | None = None


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    published_at: str | None
    asset: ReleaseAsset | None
    prerelease: bool | None = None
    body: str | None = None


def _request_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "AOCapp_Updater",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_get_json(url: str) -> list[dict] | dict:
    logger.info(f"GET {url}")
    headers = _request_headers()
    try:
        resp = requests.get(url, headers=headers, timeout=(5, 10))
        status = resp.status_code
        logger.debug(f"Response status: {status}")
        if status >= 400:
            body = None
            try:
                j = resp.json()
                body = j.get("message") if isinstance(j, dict) else str(j)
            except Exception:
                body = resp.text
            raise UpdateError("GitHub API error", url=url, status=status, body=body)
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        try:
            return _http_get_json_via_curl(url, headers=headers)
        except Exception as fallback_exc:
            if isinstance(fallback_exc, UpdateError):
                raise fallback_exc
            raise UpdateError("GitHub API connection error", url=url, body=str(exc)) from fallback_exc


def _http_get_json_via_curl(url: str, headers: dict[str, str]) -> list[dict] | dict:
    if not shutil.which("curl"):
        raise UpdateError("curl not found for GitHub API fallback", url=url)

    cmd = ["curl", "-sSL", "--connect-timeout", "5", "--max-time", "10"]
    for k, v in (headers or {}).items():
        cmd.extend(["-H", f"{k}: {v}"])
    cmd.extend(["-w", "\n%{http_code}\n", url])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise UpdateError("GitHub API error (curl)", url=url, body=proc.stderr or proc.stdout)

    body, _, status_line = proc.stdout.rstrip("\n").rpartition("\n")
    try:
        status = int(status_line.strip())
    except ValueError:
        status = None
        body = proc.stdout

    if status and status >= 400:
        raise UpdateError("GitHub API error (curl)", url=url, status=status, body=body)

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise UpdateError("GitHub API returned invalid JSON (curl)", url=url, body=body[:800]) from exc


def _normalize_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64", "x64"):
        return "x64"
    if machine in ("i386", "i686", "x86"):
        return "x86"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine or "unknown"


def _select_asset_for_current_platform(tag: str, assets: list[dict]) -> ReleaseAsset | None:
    system = platform.system().lower()
    arch = _normalize_arch()

    def is_archive(name: str) -> bool:
        return name.lower().endswith(".zip")

    def match_os(name: str) -> bool:
        lower = name.lower()
        if system == "windows":
            return any(token in lower for token in ("windows", "win"))
        if system == "darwin":
            return any(token in lower for token in ("macos", "darwin", "osx", "mac"))
        return False

    def match_arch(name: str) -> bool:
        lower = name.lower()
        if arch == "x64":
            return any(token in lower for token in ("x64", "x86_64", "amd64", "win64", "64bit")) or not any(
                token in lower for token in ("x86", "i386", "win32", "32bit", "arm64", "aarch64")
            )
        if arch == "x86":
            return any(token in lower for token in ("x86", "i386", "win32", "32bit"))
        if arch == "arm64":
            return any(token in lower for token in ("arm64", "aarch64"))
        return True

    candidates: list[ReleaseAsset] = []
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name", "") or ""
        url = asset.get("browser_download_url", "") or ""
        if name and url and is_archive(name) and match_os(name) and match_arch(name):
            candidates.append(ReleaseAsset(name=name, download_url=url, size=asset.get("size")))

    if not candidates:
        return None

    def score(asset: ReleaseAsset) -> tuple[int, int]:
        lower = asset.name.lower()
        return (1 if tag.lower() in lower else 0, len(lower))

    return sorted(candidates, key=score, reverse=True)[0]


def list_releases(repo_slug: str, limit: int = 10) -> list[ReleaseInfo]:
    url = f"https://api.github.com/repos/{repo_slug}/releases?per_page={max(1, min(limit, 100))}"
    releases = _http_get_json(url)
    if not isinstance(releases, list):
        raise UpdateError("Unexpected GitHub API response (not a list)", url=url, body=str(releases))

    items = [
        ReleaseInfo(
            tag=release.get("tag_name") or release.get("name") or "",
            published_at=release.get("published_at"),
            asset=_select_asset_for_current_platform(
                release.get("tag_name") or release.get("name") or "",
                release.get("assets", []) or [],
            ),
            prerelease=release.get("prerelease"),
            body=release.get("body"),
        )
        for release in releases
        if isinstance(release, dict)
    ]
    items.sort(key=lambda release: release.published_at or "", reverse=True)
    return items[:limit]


def is_newer(tag_remote: str, tag_local: str) -> bool:
    def parse(tag: str) -> Version | str:
        normalized = re.sub(r"^[vV]", "", tag.strip())
        try:
            return Version(normalized)
        except InvalidVersion:
            return normalized.lower()

    remote = parse(tag_remote)
    local = parse(tag_local)
    if isinstance(remote, Version) and isinstance(local, Version):
        return remote > local
    return str(remote) > str(local)
