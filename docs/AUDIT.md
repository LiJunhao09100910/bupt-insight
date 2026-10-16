# 源码审计与文件级实施方案

审计日期：2026-10-13（北京时间）。读取的是实际 Git 源码，不以 README 作为功能证据。

| 仓库 | 审计提交 | 许可证 |
|---|---|---|
| yantingweb/bupt-information-collector | eaacbee8ae0525ccc0e13b625891a2dc0b8c0441 | MIT |
| Nemoyuzx/where_to_study | 114195057404339fbde575c916775b398b696fb7 | GPL-3.0，具体分发须遵守原仓库许可证 |
| byrdocs/bupt-auth | b0771c23c1d60c501dd0b570f475ae14c3c3c14b | MIT |

参考项目克隆在工作区外 `D:\software\bupt-insight-references`，没有嵌套提交它们。

## 主项目

- `core/browser.py`：使用 Playwright storage_state JSON；文件存在曾被当成 logged_in。`login()` 依赖 probe，可选 verify；输出前 80 字符登录标记，可能泄露 Token。含 webdriver、plugins、languages 伪装。本次保持浏览器查找与生命周期接口，移除伪装执行；BYR 登录必须访问版面验证，改 DPAPI 加密，不打印登录标记。
- `sources/byr.py`：列表 `table.board-list`，跳过 `tr.top`，标题 `/article/`，原帖正文 `td.a-content`。保留这些选择器和人工浏览器登录流程；原 fetch 仅列表，read 独立短正文，Cookie 有值不足以验证业务。新增列表重试、登录表单识别、限频全文读取、正文错误状态；SQLite 用版面+帖子 ID 与内容哈希检测更新。
- `sources/portal.py`：原实现仅公开院系公告，通用链接+日期抽取，未实现 my.bupt.edu.cn 认证；无正文 read 实现。原实现保存在 `sources/public_portal.py`，新版同名模块专用于受保护门户。真实门户选择器已完成本机账号校准；未配置的模板仍明确报 adapter_unverified，禁止用公开公告替代私有通知验收。
- `core/push.py`：PushPlus/Server酱原实现只判断 HTTP 200；JSON pushed.json 按 URL 统一去重，无法分别补发失败渠道，也不能重新推送内容更新。保留原多渠道模块，修正两个微信发送器并收敛异常输出；新生产入口使用 `core/notifications.py` 的结构化结果与 SQLite outbox。飞书/SMTP等旧接口未接入新版 CLI。
- `core/store.py`、`run.py`：原 JSON seen/items/pushed 不支持事务性通知版本，URL 去 query 会合并不同 notice ID。新版 CLI 改由 `core/database.py`、`core/pipeline.py` 调度；旧 JSON 不自动混入新数据库。

## where_to_study

实际读取 `src-tauri/src/{auth,classrooms,assignments,credential_store,session_cache}.rs` 与 `wts-cli/src/credentials.rs`。

- `classrooms.rs::login_uncached`：移动教务 `jwglweixin.bupt.edu.cn`，提交 userNo/pwd；业务 code=1，取得该系统 token，解析 expires_in/expiresIn。它不是门户 CAS 会话。
- `assignments.rs::authenticate`：HTTPS authserver/login，CAS service 固定为 **ucloud**；解析 execution，多条 Set-Cookie 合并；POST 后严格校验 ucloud 回调，再以 ticket、grant_type=third 换 apiucloud OAuth Token。后续 Blade-Auth 属于教学云。不能拷贝它的 service 或兑换接口用于门户。
- `credential_store.rs`：桌面 Windows 路径调用 CredReadW/CredWriteW/CredDeleteW，GENERIC 与 LOCAL_MACHINE 持久化，仍仅当前用户可见；Zeroizing 和 Debug 仅输出 presence。移动、其他桌面系统有独立 backend。
- **容易误读之处**：`wts-cli/src/credentials.rs` 使用 user-only 文件 cli-credentials.json；不能把桌面安全存储结论推广到整个仓库。本项目没有采用其文件明文凭据方案。
- `session_cache.rs`：进程内、凭据作用域、TTL、并发登录串行化，账号改变以 epoch 撤销旧请求；只对明确 authentication_expired 重认证一次，403、500、解析失败不伪装成过期。借鉴会话状态区分，本项目不移植其 Rust 实现。
- `auth.rs` 还允许 BUPT_USERNAME/BUPT_PASSWORD 环境变量；本项目学校密码只用 getpass + Credential Manager，不接受命令参数、YAML、env。

## bupt-auth

实际读取 `index.ts`、`utils.ts`、`LICENSE`。

- `getCookieAndExecution` 从实际页面提取 execution；Cookie 只取首个 Set-Cookie，无法保证完整复杂会话。
- `login` 使用 ucloud service；POST 必须 302，取 Location ticket。默认把票据换为教学云 access/refresh Token，并读取角色；`cas:true` 调 serviceValidate 返回 CAS 身份属性。CAS 身份成功和门户业务会话成功是两项验收。
- 动态验证码 ID 来自页面 config.captcha；支持人工 callback 与 byrdocs OCR。**本项目不使用 OCR，不把学校 Cookie 或验证码上传第三方**。遇验证码/MFA使用官方浏览器人工处理。
- 本项目不调用 serviceValidate 提前消耗门户 Service Ticket；让票据返回其原始 service，由门户自身建立会话。
- `utils.ts` 测试输入会写 BUPT_ID/BUPT_PASS 环境变量；本项目不采用。

## 认证边界

| 系统 | 认证产物 | 本项目处理 |
|---|---|---|
| 移动教务 | jwglweixin token | 不使用 |
| 统一身份认证 CAS | TGC / service 专用 ST | 仅沿门户真实跳转、动态表单、Cookie jar |
| 教学云 | apiucloud access/refresh Token、Blade-Auth | 不使用 |
| 信息门户 | my.bupt.edu.cn 自身业务 Cookie/页面 | 身份区域、受保护业务区域、通知列表、正文共同验证 |
| BYR 论坛 | 原 nforum Cookie 与 browser state | 独立浏览器 context，人工登录，版面与正文验证 |

## 文件级方案与落实

| 文件 | 改造职责 |
|---|---|
| `core/portal_auth.py` | PortalAuthenticator HTTP/CAS、浏览器回退、人工认证入口；HTTP真实账号联调已通过；浏览器方式仍受官方iframe空白限制 |
| `core/http.py` | 学校 host、HTTPS 密码目标、跳转限制、ST 与 service 回调核验 |
| `core/security.py` | Windows Credential Manager、DPAPI、注销，无明文 fallback |
| `sources/portal.py` | 严格可配置列表/正文解析与空列表/结构变化分类 |
| `core/browser.py`、`sources/byr.py` | 保留原选择器与浏览器登录，独立增量正文抓取 |
| `core/schema.py` | body/private、保留 query notice ID |
| `core/database.py` | notices/analyses/deliveries/sync_runs、版本与 per-channel outbox |
| `core/notifications.py` | 官方微信 API、业务码、回执、隐私摘要、Windows Toast |
| `core/pipeline.py`、`core/locking.py` | 源故障隔离、定时重入锁、失败恢复 |
| `core/cli.py`、`run.py` | 无前端 CLI、安全本地输入、测试与状态入口 |
| `deploy/Install.ps1` | 当前用户交互式任务、时间配置、注册后回查 |
| `tests/`、`docs/VALIDATION.md` | 虚构 HTML/Mock/本机组件验证，真实结果分开记录 |

## 许可证处理

保留主项目根目录 MIT LICENSE 与原版权声明。没有复制 where_to_study 的实现代码、资源或二进制；仅研究协议行为并独立编写 Python，故不把 GPL 源码混入 MIT 文件。若未来移植 GPL 实现或分发其派生作品，必须按 GPL 要求提供对应源码和许可，不能仅附一句署名。

bupt-auth 仅作协议审计参考，没有移植 TypeScript。若未来复制其代码，随分发保留 byrdocs MIT 版权与许可全文。外部 Python 库由各自许可证约束，打包分发应附依赖许可；目前提供 requirements 与实际验证环境版本清单，不打包第三方二进制。
