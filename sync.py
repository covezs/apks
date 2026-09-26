#!/usr/bin/env python3
"""镜像开源 APK 最新版到本仓库 Releases，维护 manifest.json 供公众号检索。
apps.json 配置要跟踪的上游；有新版本才下载、发 Release、更新清单。"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["OWNER_REPO"]  # 如 covezs/apks
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "apks-sync",
}


def api(url, data=None, headers=None, method=None):
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    body = data if isinstance(data, bytes) else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    return urllib.request.urlopen(req)


def get_json(url):
    with api(url) as r:
        return json.load(r)


def find_release_by_tag(tag):
    try:
        with api(f"{API}/repos/{REPO}/releases/tags/{urllib.parse.quote(tag)}") as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def main():
    with open("apps.json") as f:
        apps = json.load(f)
    manifest = {}
    if os.path.exists("manifest.json"):
        with open("manifest.json") as f:
            manifest = json.load(f)

    for app in apps:
        name, upstream, pattern = app["name"], app["repo"], app["pattern"]
        rel = get_json(f"{API}/repos/{upstream}/releases/latest")
        version = rel["tag_name"]
        if manifest.get(name, {}).get("version") == version:
            print(f"[skip] {name} {version}")
            continue
        asset = next((a for a in rel.get("assets", []) if re.search(pattern, a["name"])), None)
        if not asset:
            print(f"[warn] {name}: 上游 {version} 没有匹配 {pattern} 的资源", file=sys.stderr)
            continue

        # 下载上游 APK
        with api(f"{API}/repos/{upstream}/releases/assets/{asset['id']}",
                 headers={"Accept": "application/octet-stream"}) as r, open(asset["name"], "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        print(f"[dl] {asset['name']} ({asset['size'] // 1048576} MB)")

        # 本仓库发 Release（同一 tag 已存在则复用）
        tag = f"{name}-{version}"
        my_rel = find_release_by_tag(tag)
        if not my_rel:
            with api(f"{API}/repos/{REPO}/releases", data={
                "tag_name": tag,
                "name": f"{name} {version}",
                "body": f"镜像自 {upstream} {version}\n上游: {rel['html_url']}",
            }) as r:
                my_rel = json.load(r)
            print(f"[release] {tag}")

        # 上传资产
        with open(asset["name"], "rb") as f:
            up_url = (f"{UPLOADS}/repos/{REPO}/releases/{my_rel['id']}/assets"
                      f"?name={urllib.parse.quote(asset['name'])}")
            api(up_url, data=f.read(), headers={"Content-Type": "application/octet-stream"})
        os.remove(asset["name"])

        manifest[name] = {
            "version": version,
            "file": asset["name"],
            "url": f"https://github.com/{REPO}/releases/download/{tag}/{urllib.parse.quote(asset['name'])}",
            "upstream": rel["html_url"],
            "size": asset["size"],
        }
        print(f"[ok] {name} -> {manifest[name]['url']}")

    with open("manifest.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
