"""把 manifest/ 和 mirror/ 推送到 Gitee 仓库（国内可访问），有变化才提交。

仓库名读 seeds.json 里的 gitee.repo / gitee.branch；
环境变量 GITEE_USER（Gitee 用户名）、GITEE_TOKEN（Gitee 私人令牌），GitHub Actions 里来自仓库密钥。
没配置时直接跳过，不算失败。

用法：python tools/sync_gitee.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(args, cwd, check=True):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    with open(os.path.join(ROOT, "seeds.json"), encoding="utf-8") as f:
        gitee = json.load(f).get("gitee", {})
    repo, branch = gitee.get("repo", ""), gitee.get("branch", "master")
    user, token = os.environ.get("GITEE_USER", ""), os.environ.get("GITEE_TOKEN", "")
    if not repo or not user or not token:
        print("没有配置 Gitee（seeds.json 的 gitee.repo，或密钥 GITEE_USER / GITEE_TOKEN），跳过同步")
        return
    # GITEE_REMOTE 只用于本地测试（指向一个本地空仓库）；正常运行不用设置
    remote = os.environ.get("GITEE_REMOTE") or f"https://{user}:{token}@gitee.com/{repo}.git"
    work = tempfile.mkdtemp()
    try:
        if run(["git", "clone", "--depth", "1", "-b", branch, remote, work], ROOT, check=False).returncode != 0:
            # 空仓库或分支还不存在：新建
            run(["git", "init", "-b", branch], work)
            run(["git", "remote", "add", "origin", remote], work)
        for name in ("manifest", "mirror"):
            src, dst = os.path.join(ROOT, name), os.path.join(work, name)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
        # 清单按字节签名：禁止换行转换
        with open(os.path.join(work, ".gitattributes"), "w", encoding="utf-8", newline="\n") as f:
            f.write("manifest/* -text\nmirror/** -text\n")
        run(["git", "config", "user.name", user], work)
        run(["git", "config", "user.email", f"{user}@users.noreply.gitee.com"], work)
        run(["git", "add", "-A"], work)
        if run(["git", "diff", "--cached", "--quiet"], work, check=False).returncode == 0:
            print("Gitee 上已是最新，不用同步")
            return
        run(["git", "commit", "-m", "自动同步配置源清单"], work)
        result = run(["git", "push", "origin", f"HEAD:{branch}"], work, check=False)
        if result.returncode != 0:
            # 不打印远程地址，避免令牌出现在日志里
            sys.exit("推送到 Gitee 失败：" + result.stderr.replace(token, "***")[-500:])
        print(f"已同步到 Gitee：{repo}（{branch}）")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
