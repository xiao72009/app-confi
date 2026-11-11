"""下载一个配置地址，解码并分析：能不能用、有多少站点、带不带插件。

插件：配置里的 spider（jar）或站点类型 3 / js / py 接口，应用会下载并执行这些代码。
直连站点：类型 0（XML）或 1（JSON）的采集站接口，应用只发普通网络请求，不执行第三方代码。
"""
import sys
import time

import requests

from decode import decode, parse_json

HEADERS = {"User-Agent": "okhttp/4.12.0"}
TIMEOUT = 15


def fetch(url: str, timeout: float = TIMEOUT):
    """返回 (原始字节, 耗时毫秒)；失败抛异常。"""
    start = time.monotonic()
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.content, int((time.monotonic() - start) * 1000)


def is_plugin_site(site: dict) -> bool:
    api = str(site.get("api", ""))
    if site.get("jar"):
        return True
    if site.get("type") in (3, "3"):
        return True
    return api.endswith((".js", ".py")) or api.startswith("csp_")


def is_direct_site(site: dict) -> bool:
    return site.get("type") in (0, 1, "0", "1") and str(site.get("api", "")).startswith("http")


def analyse(config: dict) -> dict:
    sites = [s for s in config.get("sites", []) if isinstance(s, dict)]
    direct = [s for s in sites if is_direct_site(s)]
    plugin_sites = [s for s in sites if is_plugin_site(s)]
    return {
        "sites": len(sites),
        "direct": len(direct),
        "plugin_sites": len(plugin_sites),
        "spider": bool(config.get("spider")),
        "plugin": bool(config.get("spider")) or bool(plugin_sites),
        "direct_apis": [s.get("api") for s in direct],
    }


def inspect(url: str) -> dict:
    result = {"url": url, "ok": False}
    try:
        content, ms = fetch(url)
        result["ms"] = ms
    except Exception as e:  # noqa: BLE001 - 网络错误种类很多，统一记成失败原因
        result["error"] = type(e).__name__ + ": " + str(e)[:120]
        return result
    text = decode(content)
    config = parse_json(text)
    if not isinstance(config, dict) or not config.get("sites"):
        result["error"] = "不是有效的点播配置（没有 sites）"
        return result
    result.update(analyse(config))
    result["ok"] = True
    # 解码后的配置文本：搬运到 Gitee 时直接存这份（应用读到的就是普通 JSON）
    result["text"] = text
    return result


if __name__ == "__main__":
    for target in sys.argv[1:]:
        r = inspect(target)
        if r["ok"]:
            print(f"可用  {r['ms']:>5}ms  站点 {r['sites']:>3}  直连 {r['direct']:>3}  插件站 {r['plugin_sites']:>3}  spider={'有' if r['spider'] else '无'}  {target}")
        else:
            print(f"失败  {r.get('error')}  {target}")
