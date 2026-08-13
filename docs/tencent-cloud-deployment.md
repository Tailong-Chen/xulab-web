# XuLab 腾讯云境外/全球 CDN 部署（无需中国大陆备案）

可以继续使用腾讯云。这里采用的是腾讯云的**境外/全球加速**，不是中国大陆节点加速：COS 源站和 CDN 边缘节点放在香港、新加坡等境外地域，大陆访问通过国际链路到最近的境外节点。它不等同于中国大陆 CDN，不能保证所有运营商都达到大陆节点的延迟，但通常比 GitHub Pages 更稳定。

仓库已经包含自动发布流程。每次推送 `main` 分支时，GitHub Actions 会：

1. 检查静态页面。
2. 将变更文件同步到腾讯云 COS。
3. 删除目标前缀下已经从仓库移除的文件。
4. 调用腾讯云 CDN `PurgePathCache` 从站点根目录刷新 `xulab.cc`。

## 为什么之前的腾讯云资源可以直接访问

腾讯云 VOD/COS 的默认资源域名是全球可访问的，它不代表已经启用了中国大陆自定义域名 CDN。腾讯云 CDN 按加速区域区分规则：

- **中国大陆**：通常要求域名完成 ICP 备案。
- **境外**：可使用香港、新加坡等节点，不依赖中国大陆 ICP 备案。
- **全球**：包含中国大陆时，是否允许接入取决于控制台对该域名和加速区域的校验；若控制台要求备案，选择“境外”即可。

因此本项目不需要申请备案，也不把源站放在中国大陆地域。

## 1. 腾讯云资源配置

创建一个只用于本站的 COS 存储桶：

- 地域选择 `香港`（`ap-hongkong`）或 `新加坡`（`ap-singapore`）。
- 桶名记录完整 APPID，例如 `xulab-site-1250000000`。
- COS 静态网站首页设为 `index.html`。
- 允许 CDN 回源读取对象。建议桶本身私有读，由 CDN 回源鉴权访问。

在腾讯云 CDN 控制台添加加速域名：

- 加速域名：`xulab.cc`。
- 加速区域：选择**境外**；如果选择**全球**时控制台不要求备案，也可以选择全球。
- 源站：上面的 COS 桶，或其 COS 源站域名。
- 配置 HTTPS 证书，并开启 HTTP/2、HTTP/3、gzip/Brotli。
- 缓存规则：HTML 5 分钟；CSS、JS、图片、字体 7 天。

如果控制台在“全球”加速区域提示备案，这是正常的，改用“境外”即可。CDN 默认会给出一个类似 `xxxx.cdn.dnsv1.com` 的 CNAME。

不要在同一个 COS 前缀下存放其他人工维护文件。工作流使用 `--delete`，会删除该前缀下本地已不存在的对象。

## 2. DNS 切换

在 DNS 服务商处将 `xulab.cc` 指向腾讯云 CDN 提供的 CNAME：

- 删除 GitHub Pages 旧的 `A`、`AAAA` 和 GitHub CNAME 记录。
- 添加 `xulab.cc` 的 CNAME，值为腾讯云 CDN 的 CNAME。
- 同时为 `www.xulab.cc` 配置跳转或同一 CDN（如使用该域名）。
- DNS 切换完成前，可以先用 CDN 控制台提供的测试域名检查站点。

仓库里的 `CNAME` 文件只服务 GitHub Pages，不会被 `deploy_cos.py` 上传到 COS。

## 3. GitHub Actions 配置

在 GitHub 仓库的 `production` Environment 中添加 Secrets：

- `TENCENTCLOUD_SECRET_ID`
- `TENCENTCLOUD_SECRET_KEY`

添加 Variables：

- `TENCENT_COS_BUCKET`：完整桶名，必须包含 APPID。
- `TENCENT_COS_REGION`：`ap-hongkong` 或 `ap-singapore`。
- `TENCENT_CDN_DOMAIN`：`xulab.cc`（也可以填写 `https://xulab.cc`）。
- `TENCENT_COS_PREFIX`：通常留空；发布子目录时填不带首尾斜杠的前缀。

CAM 子用户只授予目标 COS 桶对象的列出、上传、删除权限，以及目标 CDN 域名的目录刷新权限。不要使用主账号永久密钥。

### 可直接导入的最小权限策略

仓库中的 [`docs/tencent-cam-policy.json`](tencent-cam-policy.json) 已按当前桶
`xulab-1304199935`、地域 `ap-hongkong` 和域名 `xulab.cc` 生成。进入
`访问管理 CAM -> 策略 -> 新建自定义策略 -> 按策略语法创建`，粘贴该 JSON，
保存后将策略绑定到 `xulab-web`。如果你的桶名或 APPID 不同，先替换策略中的
`1304199935` 和 `xulab-1304199935`。

该策略只覆盖工作流实际调用的 COS `GetBucket`、`PutObject`、`DeleteObject`
和 CDN `PurgePathCache`。不要把 `QcloudCOSFullAccess` 或管理员策略长期绑定给
部署用户；若腾讯云控制台提示 CDN 刷新策略必须使用 `*` 资源，这是该 API 的
资源粒度限制，其他 COS 权限仍然限定在本站桶内。

## 4. 首次发布

1. 先在控制台完成 COS、CDN、HTTPS 证书和 CNAME 配置。
2. 在 GitHub Actions 手动运行 `Deploy to Tencent COS CDN`。
3. 用 CDN 测试域名检查首页、栏目页、图片、视频和移动端菜单。
4. 切换 `xulab.cc` DNS 到腾讯云 CDN CNAME。
5. 从移动、联通、电信网络分别检查解析和访问。

## 5. 本地手动发布

```bash
python -m pip install cos-python-sdk-v5 tencentcloud-sdk-python
export TENCENTCLOUD_SECRET_ID='...'
export TENCENTCLOUD_SECRET_KEY='...'
export TENCENT_COS_BUCKET='xulab-site-1250000000'
export TENCENT_COS_REGION='ap-hongkong'
export TENCENT_CDN_DOMAIN='xulab.cc'

python scripts/check_site.py
python scripts/deploy_cos.py --dry-run
python scripts/deploy_cos.py --delete
```

`--dry-run` 只显示计划，不上传、不删除、不刷新 CDN。
