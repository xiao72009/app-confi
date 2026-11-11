# 配置源清单仓库

四叶草TV 的远程配置源清单。应用会从这个仓库读取 `manifest/sources.json`，用内置公钥校验 `manifest/sources.json.sig` 签名，通过后把清单里的配置源排在内置列表前面使用。配置源失效时，只要这里的清单更新了，应用就能用上新地址，不需要重新发版。

清单由仓库里的定时任务每天自动生成：

1. 检查 `seeds.json` 里的种子配置源能不能用；
2. 在 GitHub 上搜索新的配置，只收**不带插件**、直连站点实测能返回片库的；
3. 把不带插件的配置和直播列表**搬运一份到 Gitee**（国内可访问），清单里 Gitee 副本排最前；
4. 地址列表有变化才重新签名；清单和副本推送到 GitHub 和 Gitee。

**为什么要 Gitee**：用户的网络可能连不上境外网站，GitHub 和它的镜像（gh-proxy、jsDelivr）都打不开。定时任务跑在 GitHub 的服务器上（境外），负责把东西搬到 Gitee，用户的应用只从 Gitee 和国内能访问的地址拿。清单有签名，放在 Gitee 上也不怕被篡改。

## 第一次设置

1. **新建一个公开仓库**（jsDelivr 和 gh-proxy 镜像只能读公开仓库），把本目录里的全部内容（含 `.github`、`.gitattributes`）放到仓库根目录，推送到 `main` 分支。
2. **添加签名私钥**：仓库 Settings → Secrets and variables → Actions → New repository secret
   - Name：`MANIFEST_SIGNING_KEY`
   - Secret：`C:\Users\hello\siyecao-manifest-signing\private_key.pem` 文件的**全部内容**（包括 `-----BEGIN PRIVATE KEY-----` 和 `-----END PRIVATE KEY-----` 两行）
3. **设置 Gitee（国内用户必需）**：
   - 在 Gitee 新建一个**公开**仓库（名字建议起得普通些，例如 `app-config`，避免被当成影视资源仓库审核下架），初始化时勾选生成 README；
   - Gitee 设置 → 私人令牌 → 生成新令牌，勾选 `projects` 权限，复制令牌；
   - 回到 GitHub 仓库的 Actions 密钥里再加两个：`GITEE_USER`（Gitee 用户名）、`GITEE_TOKEN`（刚才的令牌）；
   - 编辑本仓库的 `seeds.json`，把 `gitee.repo` 填成 `Gitee用户名/仓库名`（分支默认 `master`，和 Gitee 新仓库一致）。
4. **打开定时任务**：仓库 Actions 页面，如果提示需要启用就点启用；然后选“更新配置源清单”，点 Run workflow 手动跑一次，确认成功。
5. **告诉开发者两个仓库名**（格式 `用户名/仓库名`）：GitHub 的填进应用的 `ConfigManifest.REPO`，Gitee 的填进 `ConfigManifest.GITEE_REPO`，重新编译。

### Gitee 的限制

- 单个文件超过 1MB 时 Gitee 要求登录才能下载。现在最大的副本（hkuc 配置）约 170KB，没问题；如果以后加了很大的配置，定时任务日志里留意文件大小。
- Gitee 会审核公开仓库内容，这类仓库有被下架的风险。万一被下架：换一个新仓库，更新 `seeds.json` 和应用里的 `GITEE_REPO`。应用里还有离线缓存和饭太硬、肥猫这类自有域名的配置兜底。

## 日常维护

- **增减种子源**：编辑 `seeds.json`。每组是同一份配置的几个镜像；`plugin: true` 表示站点依赖插件（应用会下载并运行 jar），只放你信任的来源。
- **调整自动发现**：`seeds.json` 里的 `discover`（搜索关键词、最多收几个、至少几个站点实测可用）。
- **本地试跑**（需要 Python 3 和 `pip install requests cryptography`）：
  ```bash
  python tools/build_manifest.py --discover
  python tools/sign_manifest.py --key 私钥文件路径
  python tools/inspect_config.py 配置地址     # 单独检查某个配置地址
  GITEE_USER=用户名 GITEE_TOKEN=令牌 python tools/sync_gitee.py   # 手动同步到 Gitee
  ```

## 安全说明

- **私钥只放两个地方**：你电脑上的 `private_key.pem` 和仓库的 Actions 密钥。不要提交进任何仓库，也不要发给别人。私钥文件请另外备份一份。
- 应用只认用这把私钥签过名的清单，别人即使篡改了镜像上的清单，应用也会拒绝。
- 签名只保护清单本身；`mirror/` 里的配置副本没有签名，能改它们的只有能登录你 Gitee / GitHub 账号的人，所以两个账号都要开启两步验证。
- 如果私钥泄露：重新生成一对密钥，更新仓库密钥，并把新公钥换进应用的 `ConfigManifest.PUBLIC_KEY` 后重新发版。
- 自动发现只收不带插件的配置：插件是会在电视上运行的代码，陌生来源的插件可能有害。
- 定时任务运行在国外的服务器上，有些国内配置源会拒绝境外访问，检查时显示失败。种子源不会因此被删掉，只是排到后面；自动发现的新源必须检查通过才会收录。
