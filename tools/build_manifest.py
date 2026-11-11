"""生成配置源清单 manifest/sources.json。

1. 检查 seeds.json 里每个种子镜像：能否下载、解码后是不是有效配置、耗时多少。
   种子组永远保留：检查通过的组排前面，失败的排后面（云端在国外，部分国内源会拒绝境外访问，不能因此丢掉）。
2. 加 --discover 时：用 GitHub 搜索发现新配置，只收不带插件、直连站点实测能返回片库的（最多 max_accept 个），排在种子后面。
3. 只有地址列表和上次不同才改写清单文件（耗时变化不算），避免每天产生无意义的提交。

用法：python tools/build_manifest.py [--discover]
环境变量 GITHUB_TOKEN（可选）：GitHub Actions 里自动提供，搜索限额更高。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inspect_config import HEADERS, fetch, inspect  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = os.path.join(ROOT, "seeds.json")
OUT = os.path.join(ROOT, "manifest", "sources.json")
API = "https://api.github.com"


def log(*args):
    print(*args, flush=True)


# ---------- 种子检查 ----------

def check_live(url: str) -> dict:
    try:
        content, ms = fetch(url)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "ok": False, "error": type(e).__name__}
    text = content.decode("utf-8", "replace")
    channels = sum(1 for line in text.splitlines() if "://" in line)
    ok = ("#EXTM3U" in text or "#genre#" in text) and channels > 0
    return {"url": url, "ok": ok, "ms": ms, "channels": channels, "text": text}


def expand(group: dict, proxies: list) -> list:
    """组的全部地址：写死的 urls，加上 github 原始地址展开出的“加速前缀 + 原始地址”、jsDelivr、fastly、原始地址"""
    urls = list(group.get("urls", []))
    raw = group.get("github")
    if raw:
        urls += [p + raw for p in proxies]
        match = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)", raw)
        if match:
            cdn = f"gh/{match.group(1)}/{match.group(2)}@{match.group(3)}/{match.group(4)}"
            urls += [f"https://cdn.jsdelivr.net/{cdn}", f"https://fastly.jsdelivr.net/{cdn}"]
        urls.append(raw)
    return urls


def check_group(group: dict, live: bool, proxies: list) -> dict:
    results = [check_live(u) if live else inspect(u) for u in expand(group, proxies)]
    alive = sorted([r for r in results if r["ok"]], key=lambda r: r["ms"])
    dead = [r for r in results if not r["ok"]]
    for r in results:
        state = f"可用 {r['ms']}ms" if r["ok"] else f"失败 {r.get('error')}"
        log(f"  [{group['name']}] {state}  {r['url']}")
    return {"name": group["name"], "plugin": group.get("plugin", False), "ok": bool(alive), "urls": [r["url"] for r in alive + dead], "ms": alive[0]["ms"] if alive else None,
            "mirror": group.get("mirror"), "text": alive[0].get("text") if alive else None}


# ---------- 自动发现 ----------

def github_get(path: str, params=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "config-manifest"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    r = requests.get(API + path, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def check_cms_site(api: str) -> bool:
    """直连采集站能否返回片库：type 1 是 JSON 接口，type 0 是 XML 接口"""
    url = api + ("&" if "?" in api else "?") + "ac=videolist&pg=1"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return False
        text = r.text
        if text.lstrip().startswith("{"):
            data = r.json()
            return isinstance(data.get("list"), list) and len(data["list"]) > 0
        return "<video>" in text or "<video " in text
    except Exception:  # noqa: BLE001
        return False


REPO_PATTERNS = [re.compile(r"raw\.githubusercontent\.com/([^/]+)/([^/]+)/"), re.compile(r"/gh/([^/]+)/([^/@]+)@")]


def seed_repos(seeds: dict) -> set:
    """种子里已有的 GitHub 仓库（用户名/仓库名，小写），自动发现时跳过"""
    repos = set()
    for group in seeds["vod"] + seeds["live"]:
        for url in group.get("urls", []) + ([group["github"]] if group.get("github") else []):
            for pattern in REPO_PATTERNS:
                match = pattern.search(url)
                if match:
                    repos.add((match.group(1) + "/" + match.group(2)).lower())
    return repos


def discover(seeds: dict) -> list:
    rule = seeds["discover"]
    known = seed_repos(seeds)
    repos = []
    for query in rule["queries"]:
        try:
            data = github_get("/search/repositories", {"q": query, "sort": "updated", "order": "desc", "per_page": 20})
        except Exception as e:  # noqa: BLE001
            log("搜索失败", query, e)
            continue
        for item in data.get("items", []):
            name = item["full_name"]
            if name.lower() in known or any(r["full_name"] == name for r in repos):
                continue
            repos.append(item)
    repos = repos[: rule["max_repos"]]
    log(f"发现候选仓库 {len(repos)} 个")
    accepted = []
    for repo in repos:
        name, branch = repo["full_name"], repo.get("default_branch", "main")
        try:
            files = github_get(f"/repos/{name}/contents/", {"ref": branch})
        except Exception:  # noqa: BLE001
            continue
        for f in [x for x in files if x.get("type") == "file" and x["name"].endswith(".json")][:10]:
            result = inspect(f["download_url"])
            if not result["ok"] or result["plugin"] or result["direct"] < rule["min_direct_sites"]:
                continue
            working = sum(1 for api in result["direct_apis"][:8] if check_cms_site(api))
            log(f"  候选 {name}/{f['path']}：直连 {result['direct']}，实测可用 {working}")
            if working < rule["min_working_sites"]:
                continue
            accepted.append({
                "name": f"发现：{name}/{f['path']}",
                "github": f"https://raw.githubusercontent.com/{name}/{branch}/{f['path']}",
                "mirror": "found-" + re.sub(r"[^a-z0-9]+", "-", f"{name}-{f['path']}".lower()).strip("-")[:60],
                "text": result["text"],
                "plugin": False,
                "ok": True,
                "working": working,
                "ms": result["ms"],
            })
            break  # 每个仓库最多收一份
    accepted.sort(key=lambda g: (-g["working"], g["ms"]))
    return accepted[: rule["max_accept"]]


# ---------- 生成清单 ----------

PROXIES = []
FOREIGN_HOSTS = ("jsdelivr.net", "githubusercontent.com", "github.com")


def region_rank(url: str) -> int:
    """国内能访问的可能性：0 Gitee 副本；1 加速前缀中转、自有域名；2 jsDelivr 和 GitHub 直连（国内基本不通）"""
    if "gitee.com/" in url:
        return 0
    if any(url.startswith(p) for p in PROXIES):
        return 1
    return 2 if any(h in url for h in FOREIGN_HOSTS) else 1


def entries(groups: list) -> list:
    out = []
    for group in groups:
        for url in group["urls"]:
            out.append({"url": url, "name": group["name"], "plugin": group.get("plugin", False), "checked": group["ok"]})
    # 稳定排序：同一档里保持原来的组顺序（检查通过的在前）
    out.sort(key=lambda e: region_rank(e["url"]))
    return out


def mirror_to_gitee(groups: list, gitee: dict, kind: str):
    """把不依赖插件、检查通过的组写一份副本到 mirror/<kind>/，并把 Gitee 地址插到该组最前"""
    if not gitee.get("repo"):
        return
    folder = os.path.join(ROOT, "mirror", kind)
    os.makedirs(folder, exist_ok=True)
    ext = "json" if kind == "vod" else "txt"
    # 先清掉上次的副本：自动发现的配置每天可能不同，旧副本不能一直留着
    for old in os.listdir(folder):
        if old.endswith("." + ext):
            os.remove(os.path.join(folder, old))
    for group in groups:
        if group.get("plugin") or not group.get("ok") or not group.get("mirror") or not group.get("text"):
            continue
        name = f"{group['mirror']}.{ext}"
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(group["text"])
        group["urls"].insert(0, f"https://gitee.com/{gitee['repo']}/raw/{gitee.get('branch', 'master')}/mirror/{kind}/{name}")


def url_lists(manifest: dict):
    return [e["url"] for e in manifest.get("vod", [])], [e["url"] for e in manifest.get("live", [])]


def main():
    with open(SEEDS, encoding="utf-8") as f:
        seeds = json.load(f)
    proxies = seeds.get("proxies", {}).get("list", [])
    PROXIES[:] = proxies
    log("检查点播种子：")
    vod = [check_group(g, False, proxies) for g in seeds["vod"]]
    log("检查直播种子：")
    live = [check_group(g, True, proxies) for g in seeds["live"]]
    # 检查通过的组排前面（组内已按耗时排好），失败的组保留在后面
    vod = [g for g in vod if g["ok"]] + [g for g in vod if not g["ok"]]
    live = [g for g in live if g["ok"]] + [g for g in live if not g["ok"]]
    if "--discover" in sys.argv:
        log("自动发现：")
        found = discover(seeds)
        log(f"收录发现的配置 {len(found)} 个")
        # 发现的配置也展开成各加速前缀的地址（只检查过 raw 地址，前缀地址和种子一样排在国内可访问的那一档）
        for group in found:
            group["urls"] = expand(group, proxies)
        vod += found
    gitee = seeds.get("gitee", {})
    mirror_to_gitee(vod, gitee, "vod")
    mirror_to_gitee(live, gitee, "live")
    manifest = {"version": 1, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "vod": entries(vod), "live": entries(live)}
    old = None
    if os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
    if old is not None and url_lists(old) == url_lists(manifest):
        log("地址列表没有变化，不改写清单")
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log(f"已写入 {OUT}：点播 {len(manifest['vod'])} 个地址，直播 {len(manifest['live'])} 个地址")


if __name__ == "__main__":
    start = time.monotonic()
    main()
    log(f"用时 {time.monotonic() - start:.1f}s")
