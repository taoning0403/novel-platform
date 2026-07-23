# 漫读 (novel-platform)

[English](README.md) · **简体中文**

漫读 v0.9.0（`novel-platform`）是一套私有、自托管的数字阅读与藏书整理站点，产品设计
面向个人、非商业部署。唯一管理员拥有共享的 EPUB/TXT 藏书；少量受邀人可以阅读已发布
Edition，管理员还可按凭证分别授予文件上传或 TXT 小说翻译能力。每个人分别保存自己的
进度、阅读设置、偏好、设备和会话。当前 Web 界面使用中文。

项目刻意不提供公开注册或目录、公开原文件下载、用户名/密码登录、评论、
社交、支付、广告及公开发布能力。

v0.9.0 引入不可变的 `library.read`、`library.upload`、`translation.use` 凭证能力、持久贡献者
归属及按创建者限制的删除规则。小说翻译由 Server 通过私网调用独立部署的 LinguaSpindle
v0.3.1；Provider 秘密不进入 Novel Platform 或浏览器。校验成功的 TXT Artifact 会成为翻译
发起人拥有的生成草稿 Edition，只有管理员可以发布。

当前仓库版本为 v0.9.0，仍属于 1.0 之前的软件。将站点暴露到互联网前，请先阅读
[当前项目状态](docs/PROJECT_STATE.md)和[部署手册](docs/staging-deployment.md)。

## 项目亮点

- 通过“检查—预览—提交”工作流导入 EPUB/TXT，保留追加式文件修订，并协调备份数据库与
  私有书库目录。
- 受邀阅读者通过有边界、已清洗的 Reader Projection 阅读，不直接接触原始源文件。
- 管理员使用常驻且经过用户验证的 Passkey；受邀人使用高熵、可轮换、仅展示一次且带显式
  能力快照的访问凭证。
- 上传或生成的 Book、Edition、文件、Import 与 Translation Run 归属到真实持久 User，同时
  保持唯一管理员馆藏 owner 与按创建者限制的操作规则。
- 通过仅 Server 可达的 LinguaSpindle 私网 HTTP 翻译可读 TXT，持久化幂等 Run、限制 Artifact
  导入，并提供创建者草稿预览和管理员发布。
- 会话绑定服务器授权设备，刷新令牌单次轮换，每个受保护请求重新验证当前授权状态；安全
  审计事件不记录原始秘密。
- 在共享管理员藏书的同时，确保每位阅读者的进度、阅读设置、首选 Edition、设备和会话
  相互隔离。
- React/Ant Design Web 端采用 Quiet Trace 设计系统，并提供专门的沉浸式 Reader 外壳。
- 发布门禁覆盖单元测试、PostgreSQL 集成测试、Web 测试、真实浏览器、重启持久性、备份/
  恢复及泄漏扫描。

## 架构

```text
Browser
  -> 同源 Nginx Web 入口
      -> React 18 + TypeScript + Ant Design 6
      -> FastAPI 模块化单体
          -> PostgreSQL
          -> 私有本地 EPUB/TXT 书库卷
          -> 可选私网 HTTP -> LinguaSpindle v0.3.1
                              -> 独立 SQLite/Artifact Volume/Provider secret
```

生产边界不依赖公开目录、公开对象存储、外部身份服务、分析服务、Worker、队列或 Redis。
持久边界详见[架构](docs/architecture.md)、[数据模型](docs/data-model.md)和
[决策索引](docs/DECISIONS.md)。

## 仓库结构

| 路径 | 用途 |
| --- | --- |
| `apps/web` | React/TypeScript 单页应用与 Web 测试 |
| `apps/server` | FastAPI 应用、领域/应用层、迁移、CLI 与测试 |
| `packages/api-client` | 生成的 OpenAPI 契约与 TypeScript schema |
| `scripts` | 验收、备份/恢复、部署、回滚及证据脚本 |
| `docs` | 当前状态、架构、数据模型、ADR 与部署手册 |
| `artifacts` | 已审查里程碑的脱敏验收与 Bundle 证据 |

## 环境要求

- Docker Engine 与 Compose v2
- 本地 Web 检查需要 Node.js 18.18+ 和 pnpm 10.33.2
- 本地 Server 检查需要 Python 3.12+ 和 uv 0.8.x
- 完整验收门禁需要 Chromium

## 本地启动

克隆仓库并复制无秘密配置模板：

```bash
git clone https://github.com/taoning0403/novel-platform.git
cd novel-platform
cp .env.example .env
```

若环境不只是一次性开发用途，请分别执行以下命令三次，并把三个独立结果分别填入 `.env`
中的三个认证秘密占位项：

```bash
openssl rand -hex 32
```

随后启动本地栈：

```bash
docker compose up --build --detach
```

开发默认配置使用 `http://localhost:3000`、`WEBAUTHN_RP_ID=localhost`、非 Secure Cookie，
并启用 OpenAPI。`compose.yaml` 默认还会把 Web、API 和 PostgreSQL 端口映射到宿主机。这些
默认值仅用于本地开发，严禁直接暴露到公网；公网部署请使用受控的 staging 配置与部署
手册。

通过 Server CLI 初始化唯一管理员：

```bash
docker compose run --rm --no-deps --entrypoint novel-platform server \
  admin init --display-name '站点管理员'
```

命令只显示一次短期、单次使用的管理员凭证。不要重定向到文件、粘贴到聊天、保存在环境
变量中，或让它进入 Shell 历史。打开 `http://localhost:3000/login`，输入凭证并立即注册
第一个 Passkey。完成注册前，恢复会话无法访问书库或管理页面。

之后管理员日常通过“使用安全设备登录”进入站点。在“管理 → 阅读者与凭证”中创建受邀人，
按需选择上传/翻译能力并立即保存新凭证；每份完整凭证只展示一次。能力变更必须 reissue，
旧凭证、设备、会话与刷新令牌立即失效。

停止服务但保留 PostgreSQL 和书库数据：

```bash
docker compose stop
```

只有明确执行一次性环境重置时才删除两个命名卷：

```bash
docker compose down --volumes
```

## 认证模型

- 阅读者身份是持久对象；重新签发访问凭证不会重建进度、设置或偏好。
- 每份受邀凭证强制包含 `library.read`，可选的 `library.upload` 与 `translation.use` 是数据库中
  不可变的签发快照；JWT 或前端状态都不是授权权威。
- 阅读者访问凭证和管理员恢复凭证至少包含 256 位随机性；PostgreSQL 仅保存按域隔离的
  HMAC 与安全提示。
- 设备授权使用服务器生成的 HttpOnly 设备秘密 Cookie；IP 和 `client_instance_id` 均不
  是认证因子。
- Access JWT 只保存在浏览器内存；刷新令牌通过 HttpOnly Cookie 单次轮换，数据库只保存
  HMAC；重放会撤销所属会话。
- 每个受保护请求都会重新加载 User、Session、Device 及凭证/Passkey 状态，因此过期、
  暂停、撤销、重置和紧急锁定立即生效。
- 管理员日常使用常驻、经过用户验证的 WebAuthn Passkey；恢复凭证由 CLI 生成、仅能使用
  一次，且会话只允许注册或重置 Passkey。

三个 Server 秘密必须随机、至少 32 字节且互不相同：

- `AUTH_JWT_SECRET`：Access JWT 签名；
- `AUTH_HASH_SECRET`：刷新令牌与限流哈希；
- `AUTH_CREDENTIAL_HASH_SECRET`：阅读者、恢复及设备凭证哈希。

禁止提交 `.env`，也不得在日志或报告中泄露秘密、凭证、令牌、Cookie、WebAuthn Challenge、
数据库密码、存储键/路径或书籍内容。

## 部署必需配置

生产环境必须满足：

- 同源 HTTPS；
- `AUTH_COOKIE_SECURE=true`；
- 稳定且与可注册域名匹配的 `WEBAUTHN_RP_ID`；
- `WEBAUTHN_ORIGINS` 为显式 HTTPS JSON 列表；
- 显式设置 `CORS_ORIGINS` 与 `TRUSTED_HOSTS`；
- `OPENAPI_ENABLED=false`；
- 使用前述三个相互独立的秘密；
- 反向代理受控，并覆盖而不是透传客户端提供的转发头。

`compose.staging.yml` 只发布 Nginx，API 与 PostgreSQL 保持在私有网络。Nginx 只信任单一
宿主边缘对等地址以恢复真实客户端 IP，对公开认证入口限流；Uvicorn 只信任 Nginx 的固定
内部地址。启用翻译时额外叠加 `compose.translation.yml`：只有 `server` 加入既有外部
`linguaspindle-private` 网络，不增加宿主端口；Provider Key 只保留在 LinguaSpindle。完整
步骤见[部署手册](docs/staging-deployment.md)。

## 安全

staging/production 的安全敏感配置采用失败关闭策略，但本仓库不能替代部署审查或独立安全
评估。暴露到互联网前，应更换全部开发秘密、使用同源 HTTPS、保持 PostgreSQL/API 私网、
验证可信代理对等地址、关闭生产 OpenAPI，并实际测试备份与恢复。

疑似漏洞请按[中文安全策略](SECURITY.zh-CN.md)私下报告。不要在公开 Issue 中附带真实凭证、令牌、
Cookie、个人数据、存储路径或导入的书籍内容。

## Server CLI

在已配置的 Compose 环境执行命令：

```bash
docker compose run --rm --no-deps --entrypoint novel-platform server COMMAND
```

该一次性形式仅用于本地开发或已经停止的栈。运行中的 staging 服务使用固定私有 IP；再启动
一个 `server` 容器会与在线 Server 地址冲突。此时应按部署手册改用
`docker compose ... exec -T server novel-platform COMMAND`。

可用命令组：

```text
admin init --display-name NAME
admin recovery create
admin credentials reset
admin sessions revoke-all
admin status
admin lock
admin unlock
auth migration preflight
auth migration convert [--target-admin-id UUID] [--map-admin-to-reader UUID ...]
auth migration audit
auth audit cleanup
```

`admin init`、`admin recovery create` 和 `admin credentials reset` 会输出一份新的单次使用
原始凭证。系统不会打印既有 Passkey 或凭证；其他输出经过脱敏，不包含令牌或存储键/路径。

使用 `admin lock` 可立即停止管理员访问并撤销管理员会话，只有 Server CLI 能解除锁定。
`admin credentials reset` 会撤销 Passkey 与全部管理员会话，再输出用于注册新 Passkey 的
恢复凭证。

## 共享书库与贡献者边界

唯一管理员始终是 Book、Edition、StoredFile、Import、Translation Run 和 Series 的显式
馆藏所有者；资源归属另行记录实际创建/发起的持久 User。受邀人只能看到经过过滤的可读
投影：

- 至少包含一个 `ready` 且有当前文件 Edition 的 Book；
- `ready` 且有当前文件的 Edition；
- 至少包含一个可见 Book 的 Series；
- 受保护封面和安全的 EPUB/TXT Reader section/resource。

只读凭证只能更新自己的进度、状态、Reader Settings、首选/最近打开 Edition、设备名称及
会话/设备撤销。`library.upload` 允许文件型创建/追加并管理本人上传资源；
`translation.use` 独立允许翻译可读 TXT 并管理本人 Run/生成 Edition。两者都不授予 Series、
原文件下载、生成译本发布、阅读者/站点/审计或 Passkey 管理。Book 创建者不能删除含他人
贡献的整本 Book。后端同时检查当前 capability 与资源 creator；隐藏按钮不是安全控制。

v0.4 已验收的 Reader、文件修订、Edition 身份、source/supersedes、进度冲突和 Series 不变量
保持不变。

## 匿名页面与索引

匿名页面只请求 `/api/v1/site`，展示站点名称、非商业用途、隐私文本、统一登录入口及可选
的真实 ICP 备案信息。ICP 号为空时不渲染任何备案信息。SPA 构建中不嵌入目录元数据，匿名
状态也不会请求目录。

FastAPI 对非健康检查响应添加 `X-Robots-Tag: noindex, nofollow, noarchive`，Nginx 对 HTML/
静态响应应用同样策略。这只是认证的补充，不能代替访问控制。

## v0.8.0 升级到 v0.9.0

v0.9.0 新增 Alembic `20260723_0006`：删除无文件占位 Edition/Book 及其偏好、进度和关系；
将保留内容的贡献者回填为唯一馆藏 owner；现有受邀凭证只回填 `library.read`；并建立
Translation Run 表。站点未完成 v0.5 转换、owner 不唯一、存在活动 Import 或文件引用异常时
迁移会失败关闭。迁移不提供 downgrade；回滚必须恢复同一份协调 PostgreSQL + 书库备份。

迁移前必须记录脱敏统计、停止写入、生成 `scripts/backup-library.sh` 备份，并通过
`scripts/restore-library.sh --test`。实际服务器迁移或可丢弃环境 reset 仍需针对精确目标另行
批准。不得删除或重建 LinguaSpindle SQLite、Artifact Volume、容器或网络。数据库升级后再
配置非秘密的 `LINGUASPINDLE_*`，核对 v0.3.1、私有 DNS、无宿主端口及强制幂等；只有翻译
环境就绪时才把 `compose.translation.yml` 叠加到 Server 部署。

## v0.7.0 升级到 v0.8.0

v0.8.0 加固认证与可信代理，不新增数据库迁移，也不改变已验收的 API、角色、书库、文件
修订或 Reader 状态契约。staging/production 必须使用 `AUTH_COOKIE_SAMESITE=strict`；构建
staging Web 镜像时，必须把实测的唯一宿主边缘对等地址写入 `STAGING_REAL_IP_PEER`；可通过
`AUTH_DEVICE_COOKIE_TTL_DAYS` 独立配置设备 Cookie 生命周期。

通过[部署手册](docs/staging-deployment.md)中的受保护流程部署，并验证真实 HTTPS 代理链、
Passkey 仪式、认证入口限流与 Cookie 属性。仅回滚应用到已验收 v0.7.0 构建时，不需要
Alembic downgrade，也不需要恢复数据库或书库。

## v0.6.0 升级到 v0.7.0

v0.7.0 只改变 Web 设计系统、交互布局、静态资源和应用版本，不新增 API、数据库、认证、
授权、权限或部署拓扑迁移。通过既有流程部署已审查的 v0.7.0 镜像，并验证真实 HTTPS 登录、
角色导航、书库过滤、阅读者管理、Upload、Reader、noindex 和健康检查。

应用回滚只需重新部署已验收的 v0.6.0 提交或镜像；不得仅因该应用回滚执行 Alembic
downgrade 或恢复 PostgreSQL/书库数据。

## v0.5.0 升级到 v0.6.0（历史）

v0.6.0 改变 Web 组件基础与静态 Bundle，不新增 API、数据库、认证或部署拓扑迁移。通过
既有流程部署 v0.6.0，并验证真实 HTTPS 登录、角色导航、Upload、Reader、管理、noindex 与
健康检查。回滚到 v0.5.0 时同样无需数据库 downgrade 或数据恢复。

## v0.4.0 升级到 v0.5.0

没有协调完成 PostgreSQL + 书库备份及隔离恢复测试前，禁止对在线数据运行 Alembic。

1. 停止 Web/API 写入并生成 `scripts/backup-library.sh` 备份。
2. 执行隔离的 `scripts/restore-library.sh --test BACKUP_DIRECTORY`。
3. 将 schema 升级到 Alembic `20260715_0005`。
4. 执行 `auth migration preflight`。
5. 若管理员或内容所有者存在歧义，显式选择 `--target-admin-id`，并通过
   `--map-admin-to-reader` 逐一映射其他管理员；转换命令拒绝猜测。
6. 执行 `auth migration convert ...`：合并内容所有权，保留内容与阅读 ID/状态，清除旧密码
   哈希并撤销旧 Device、Session 与 Refresh Token；不会生成阅读者明文凭证。
7. 针对挂载的书库卷执行 `auth migration audit`。
8. 分别轮换旧 JWT、刷新哈希及新的凭证哈希秘密，报告中不得记录秘密值。
9. 通过 CLI 生成管理员恢复凭证并注册 Passkey，再逐个身份重新签发阅读者凭证。

新数据库可跳过转换：`admin init` 会完成初始化并输出唯一的原始初始化凭证。

## 备份、恢复与回滚

在已配置宿主机上生成协调备份：

```bash
./scripts/backup-library.sh
```

脚本会短暂停止写入，生成 PostgreSQL custom dump、书库归档与 manifest，并在发布备份目录前
拒绝数据库/文件引用不一致。Dump 包括凭证与 capability、Passkey、设备、会话、站点设置、
审计、Book、Edition、贡献者归属、Translation Run、文件修订、Series、偏好、设置和进度；
manifest 明确排除 LinguaSpindle 数据及资源。

始终先在隔离资源中测试恢复：

```bash
./scripts/restore-library.sh --test \
  /srv/novel-platform/data/backups/novel-platform-v090-TIMESTAMP
```

测试会校验 manifest 哈希、Alembic revision、永久文件 checksum、临时引用以及 capability、
归属和 Translation Run 表，随后只删除临时数据库和卷。真正恢复 staging 还必须设置
`ALLOW_STAGING_RESTORE=1`、传入
`--staging` 并精确确认数据库名；脚本不会自动执行 Alembic downgrade。

回滚意味着停止写入，并从同一份已验证升级前备份恢复相互匹配的代码、数据库和书库卷。
迁移、转换或完整性审计失败时，公开应用必须保持停止。

## 开发检查

安装锁定依赖：

```bash
pnpm install --frozen-lockfile
cd apps/server && uv sync --frozen && cd ../..
```

Web 与生成契约：

```bash
pnpm api:generate
pnpm api:check
pnpm lint
pnpm test
pnpm build
pnpm bundle:report
```

Server：

```bash
cd apps/server
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest tests/unit
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost/ISOLATED_TEST_DB \
  uv run pytest tests/integration
```

集成测试必须使用 PostgreSQL，禁止使用 SQLite 或在线数据。

## 自动验收

v0.9.0 发布门禁使用唯一、一次性的 Compose project 与隔离 PostgreSQL，先重放仍适用的
认证/Reader/代理行为，再验证当前 capability、贡献归属、迁移、翻译、Web、备份和泄漏契约：

```bash
pnpm acceptance
# 等价命令
pnpm acceptance:v090
```

门禁保留 v0.5 的 84 项适用标准和 v0.8 的 9 项代理/认证加固标准，再增加 11 项 v0.9 标准：
能力生命周期、四身份 actor/resource 策略、legacy API 移除与迁移、私网服务幂等/控制/原子
导入、重翻与草稿发布、服务隔离、泄漏防护、协调备份/恢复、桌面/320 px 视觉证据及精确
清理。合成 fake transport 必须通过；真实 v0.3.1 + Mock Provider 与真实 OpenAI-compatible
Provider 在完成配置前均为 `PENDING_OPERATOR_CONFIG`，门禁不会把 fake/Mock 结果称为真实 AI
翻译。

脱敏产物为 `artifacts/acceptance-v090.{md,json}`，继承回归证据写入
`artifacts/acceptance-v090-regression*`，视觉证据位于 `artifacts/visual-v090/`。远端 migration、
网络、HTTPS/Passkey、Provider、持久化和清理在另行授权前保持 `DEPLOYMENT_PENDING`。只有
诊断失败的隔离环境时才设置 `KEEP_ACCEPTANCE_ENV=1`。

历史门禁 `acceptance:v010` 至 `acceptance:v080` 及其证据保持可运行、可追溯；v0.9 不会
改写历史证据来伪装无文件创建仍兼容。

## 已废止的验收语义

v0.5.0 明确废止依赖以下历史行为的断言：

- 用户名/密码或 Web Setup Token 认证；
- 管理员密码修改/重置；
- 通过 Web 创建本地用户名/密码用户；
- 每位普通 member 拥有并上传到隔离的个人书库；
- 普通 member 下载原始源文件或修改内容。

v0.9.0 还废止公开 metadata-only Book/Edition 创建，以及“受邀凭证永远不能写入”的断言。
新内容必须来自文件型导入或校验后的生成结果；受邀写入同时依赖当前 capability 与按创建者
限制的资源策略。

这些行为不会以兼容后门形式保留。仍有效的 BookEdition、文件修订、安全 Reader、私有状态、
Series、持久性、备份/恢复和泄漏断言均在当前门禁中重放。

## API 分组

全部 API 使用 `/api/v1`：

- `/site`：安全的公开站点配置；
- `/auth`：凭证/Passkey 登录、注册、刷新、身份、登出与会话；
- `/devices`、`/users/me`：当前阅读者私有控制；
- `/admin/readers`、`/admin/site`、`/admin/audit`：仅管理员管理；
- `/books`、嵌套 `/editions`、`/series`：可读查询与 capability/creator 感知的馆藏变更
  （Series 仍仅管理员）；
- `/imports`：管理员或 `library.upload` 检查/提交/文件修订，并按 actor 隔离；
- 嵌套 `/translation-runs` 与 `/translations`：按 actor 隔离的 TXT 翻译创建、列表、控制、
  同步、草稿预览和管理员发布；
- `/editions/{id}/file`：仅管理员原始下载；
- 受保护 Book 封面和 `/editions/{id}/reader/*`：安全可读资源；
- `/books/{id}/preferences`、`/reader/settings`、`/reader/recent`：当前阅读者私有状态；
- `/health`：最小进程/数据库探针。

持久边界详见[架构](docs/architecture.md)、[数据模型](docs/data-model.md)与
[决策索引](docs/DECISIONS.md)。

## 参与贡献

欢迎提交 Issue 与 Pull Request。变更应遵守已记录的产品和安全边界，补充聚焦测试，并运行
覆盖所改表面的检查。认证、授权、存储、部署或数据不变量的持久变更应同时提交 ADR。

普通缺陷与提案使用公开 Issue；漏洞必须使用[中文安全策略](SECURITY.zh-CN.md)中的私下报告流程。

## AIGC 声明

本项目开发过程中使用以下大语言模型参与辅助：

- OpenAI GPT-5.6；
- Moonshot AI Kimi K3。

模型参与代码生成、审查、文档编写与设计讨论等辅助工作。所有采纳的模型输出均由人类维护者
审阅并决定；项目设计、许可证、安全决策及发布产物责任均由人类维护者承担。列出模型仅用于
披露工具使用情况，不授予模型作者身份或所有权，也不表示模型提供方对本项目作出背书。

## 许可证与第三方声明

项目源代码采用 [Apache License 2.0](LICENSE)。文中“非商业”描述的是当前产品定位与内置
功能，不是对 Apache License 2.0 所授予权利的额外限制。

第三方组件保留各自许可证。Psycopg 3 的 LGPL-3.0-only 声明见 [NOTICE](NOTICE)。项目许可证
不授予对运营者导入的 EPUB/TXT、封面、元数据或其他内容的权利；运营者应自行确保拥有使用
这些内容的合法权利。

维护者联系邮箱：[alnemark0403@gmail.com](mailto:alnemark0403@gmail.com)。
