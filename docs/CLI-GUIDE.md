> 原CLI与工程完整说明；日常网页入口以根目录README为准。

# BUPT Insight · 北邮校园信息助手

Windows 11 本地运行的 Python CLI：信息门户独立认证、北邮人论坛抓取、SQLite 历史与版本去重、微信推送和桌面通知。基于 yantingweb/bupt-information-collector 开发，保留 BYR 原版面/正文选择器与人工登录流程。

**门户 HTTP/CAS 登录、真实通知正文采集及 BYR 采集已经通过本机联调。** 截至2026-10-14，已实际采集门户20条通知（18条文字正文、1条附件通知、1条图片通知）和七个 BYR 重点版面70篇原帖。Windows 普通测试及实际计划任务发送的测试弹窗均已由用户确认看到。附件和图片内容未做提取。按用户最新选择，微信渠道暂时关闭。浏览器认证 iframe 仍有空白问题，当前使用已经验证的 HTTP 方式。完整证据见 [源码审计](AUDIT.md) 和 [验收记录](VALIDATION.md)。

Phase 2 已增量加入 SQLite 在线备份、健康检查、结构化通知分析、个人画像及智能 Windows 提醒。当前本机模型模式为off，仅使用本地规则，未调用真实模型；云端门户/画像授权关闭。2026-10-16已配置本人真实兴趣与汇总偏好，新增历史评估和反馈，见[个性化审计与验证](PERSONALIZATION.md)。没有复杂前端、微服务或向量数据库。完整配置、恢复及隐私说明见 [Phase 2教程](PHASE2.md)，本轮验证见 [Phase 2验收](PHASE2-VALIDATION.md)。

## 安装：Windows 11 / PowerShell

安装 Python 3.11+（推荐 3.12）并启用 Python Launcher；安装 Microsoft Edge。进入本项目目录：

```powershell
cd D:\software\find
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 run.py init
```

默认用已安装 Edge，无须下载 Chromium。若改为 `net.browser: chromium`：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

不需要激活虚拟环境，因此不依赖 PowerShell 激活脚本执行策略。`requirements-tested.txt` 是本轮本机完整依赖版本快照（含测试依赖），可用于复现；日常安装用 requirements.txt。

本工作区已经建立 `.venv` 和不含凭据的 config.yaml。当前机器的 `python` 命令指向 Microsoft Store 占位程序，应使用上面的虚拟环境完整路径。

## 先完成真实信息门户联调

请在能访问学校内网的校园网/VPN上运行。**密码只在本地终端输入，不要发到聊天中。**

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py portal probe
.\.venv\Scripts\python.exe -X utf8 run.py credentials save
.\.venv\Scripts\python.exe -X utf8 run.py portal inspect --mode http --interactive
```

`credentials save` 使用不回显输入，学号和密码一起写入当前 Windows 用户 Credential Manager。`inspect --mode http` 使用官方CAS流程和本地凭据检查门户结构。当前电脑已经完成认证及选择器校准，无须重新输入。首次使用的新电脑需要完成本机配置；结构检查本身不代表通过通知正文验收。若遇验证码、扫码或MFA，须本人在官方界面完成；当前浏览器回退的实测限制见下文。

### 当前实测认证地址和浏览器限制

2026-10-13 本机访问 `http://my.bupt.edu.cn`，实际跳转到 `https://auth.bupt.edu.cn/authserver/login`，service 指向门户自身 `/system/resource/code/auth/clogin.jsp`。本机 `https://my.bupt.edu.cn` 连接失败。密码只提交到实际核验的 HTTPS 认证页；不会将密码提交到 HTTP 门户，也不会关闭证书检查。门户目前的 HTTP 回调及业务内容具有传输隐私限制，请只在学校允许的网络环境使用。

浏览器认证外层表单是隐藏的，界面由同源 `login-normal.html` iframe 呈现。本轮标准 Edge 自动化在有界面/无界面两种情况下均遇到 iframe 空白，**浏览器自动登录在本环境尚不可用**。程序识别此情况为 `browser_page_unavailable`，不隐藏自动化标记、不修改学校安全脚本。可先运行 `python run.py portal inspect --mode http --interactive` 使用 HTTP 方式检查本人已授权页面结构，再校准选择器；如学校策略禁止自动化，应遵守策略并请校方提供允许的访问方式。

### 校准真实门户适配器

本机 config.yaml 已从真实授权页面校准。模板保留手动校准字段供其他账号或门户改版时使用。`config.yaml` 的 `identity_selector`、`business_selector` 和 `lists` 默认空。必须在本人已授权的门户中检查并填写真实 DOM：

```yaml
sources:
  portal:
    auth_mode: http  # http / browser / auto
    identity_selector: "实际账号身份区域的CSS选择器"
    identity_expected_text: "" # 默认在身份区域核对保存的学号；若只显示姓名，可填本人实际身份标记
    business_selector: "实际受保护业务区域的CSS选择器"
    frame_selector: "" # 通知在 iframe 中时填写；HTTP 模式应直接使用该 iframe 的实际列表 URL
    lists:
      - name: "本人可见的通知栏目"
        url: "http://my.bupt.edu.cn/本人实际通知列表路径"
        row_selector: "实际每条通知行的选择器"
        link_selector: "行内标题链接选择器"
        date_selector: "行内发布日期选择器"
        source_selector: "行内发布部门选择器"
        body_selector: "实际正文区域选择器"
        empty_selector: "页面明确显示暂无通知时的选择器"
```

上面只是字段说明，**不能直接作为真实门户配置**。不要把密码、Cookie、ticket 填进 URL 或配置。通知列表若纯 AJAX/SPA，应优先浏览器模式；HTTP适配器仅处理真实返回的 HTML，不猜测接口。`inspect` 的结构清单只用于辅助，本机已完成具体选择器适配：身份 .topinner、受保护业务 #tzxw、列表 ul.newslist > li、正文 #vsb_content .v_news_content。模板中的占位配置不能直接使用。静态身份和业务区域的名字不能随意选成导航栏，否则无法证明授权内容。

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py login portal --mode http
.\.venv\Scripts\python.exe -X utf8 run.py portal test --mode http
.\.venv\Scripts\python.exe -X utf8 run.py scan portal
```

`login portal` 与 `portal test` 共用严格验收：进入 my.bupt.edu.cn、身份标记匹配、受保护业务区域存在、真实通知列表可解析，且至少一条现有通知的标题/时间/来源/链接/正文可读。输出只给第一条元数据及正文长度；正文写入 SQLite 的操作由 scan 完成。若存在通知但正文失败，退出非零；明确空列表返回 `verified_empty_list`，并不声称读到了一篇通知。

**HTTP 模式**从门户实时重定向发现 CAS 地址和 service；动态读取 execution、CSRF 等字段，Session 管理全部 Cookie，校验 ST 回调与原 service 一致，让门户自己消费票据；不调用教学云 Token 接口或抢先 serviceValidate。挑战出现时转人工入口，不用 OCR。`auto` 对可回退的 HTTP 认证/解析问题尝试浏览器；本机请保持已验证的HTTP方式。

**浏览器模式**优先复用 DPAPI 会话；失效后从 Credential Manager 读取密码，自动填写当前官方表单。任务环境不等待无限人工验证，返回 `interaction_required` 后需本人执行 `login portal --interactive`。两种模式的状态格式独立，切换模式可能需要重新认证。

## 北邮人论坛：独立登录和采集

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py login byr
.\.venv\Scripts\python.exe -X utf8 run.py scan byr --boards Paper,ParttimeJob,MathModel
```

论坛与学校统一身份认证独立。浏览器中人工完成原项目 BYR 登录流程；只有登录标记改变且能读取真实版面列表才保存会话。保留 `table.board-list`、跳过置顶 `tr.top`、正文 `td.a-content`，没有用整页导航充当正文。

默认关注科研、实习、数学建模、创新实践、算法竞赛、教务及计算机学院：修改 `sources.byr.boards` 或 watchlist.json。其他学院可以加入原 watchlist 的 SICE、SEE、SA、SSE、SS 等代号；具体存在性及账号权限待真实验证。默认每版最新10条、请求间隔2.5秒，列表与正文重试2次。不要提高频率造成负担。

按版面+帖子 ID 唯一标识，以标题/来源/作者/发布时间/原帖正文哈希检测内容变化；回帖数和纯空白改变不会重新推送。重新抓取最新窗口内的原帖才能检测编辑；窗口外旧帖、附件内容、回复楼层不在当前覆盖范围。新通知与正文更新均可再次进入推送队列。登录过期明确报错。

旧项目 `.session/byr_state.json` 可在配置中使用其绝对路径，或放到新 session_dir 下同名的 `byr_state.json`。首次成功扫描会另存 DPAPI `byr_state.bin`，默认配置下以后优先读它；原 JSON 是敏感凭据，应在确认迁移后自行清除。注销命令会清除对应 .bin 和 .json。

## 微信与 Windows 提醒

### 微信：PushPlus 优先，Server酱 Turbo 备选

注册/登录服务官网、绑定微信接收身份并按官方页面关注/激活对应公众号，取得 Token/SendKey。密钥仍只在本地输入：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py credentials token --channel pushplus
.\.venv\Scripts\python.exe -X utf8 run.py test-push pushplus
# 或使用 Server酱 Turbo 的 SCT SendKey
.\.venv\Scripts\python.exe -X utf8 run.py credentials token --channel serverchan
.\.venv\Scripts\python.exe -X utf8 run.py test-push serverchan
```

然后把 config.yaml 的 `push.channels.pushplus.enabled` 或 `serverchan.enabled` 改为 true。默认两个微信渠道都关闭，Windows 桌面开启。test-push 只发送新建的虚构测试消息，不顺带发送真实通知积压。Server酱当前仅支持标准 Turbo SCT SendKey，SCTP/其他新协议不会被错误拼接到旧接口。

微信 HTTP 200 不代表成功：PushPlus 业务 code=200、Server酱 code=0 仅记为 `accepted`（受理）。看到微信后可确认：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py delivery list
.\.venv\Scripts\python.exe -X utf8 run.py delivery confirm 你的记录ID
```

PushPlus 支持额外的官方 AccessKey 回执查询（AccessKey 与消息 Token 不同）：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py credentials token --channel pushplus_access_key
.\.venv\Scripts\python.exe -X utf8 run.py delivery check 你的记录ID
```

官方 status=2 记为 `provider_delivered`，仍不代表阅读。按用户最新选择，本机暂时只使用 Windows 提醒，没有执行微信真实发送，**微信端到端验收待完成**。

服务额度、实名认证、订阅/激活状态、消息接收窗口、公众号平台规则会影响接收。按当前官方后台为准，不承诺固定每日条数；默认三次扫描也可能超过免费配额。[PushPlus API](https://www.pushplus.plus/doc/guide/api.html)、[回执接口](https://www.pushplus.plus/doc/guide/openApi.html)、[接收限制](https://www.pushplus.plus/doc/guide/limit.html)、[Server酱官方 SendKey 文档](https://sct.ftqq.com/docs/getting-started/sendkey/)。已核对官方文档与网站可达性，不能据此推断个人账号发送能力。

第三方推送服务可读取提交的标题和内容，服务商及微信规则共同影响隐私。私有门户消息默认仅发送标题、来源、发布时间及通用提醒，不发送正文、正文截取、私人链接、Cookie、ST 或学校密码；标题本身也可能包含私人信息，应自行评估是否启用微信。BYR 默认将原帖视为公开，发送短摘录与链接；如关注的版面属于私人内容，请在 config.yaml 设置 `sources.byr.private: true`，将整个 BYR 源标为 private 后使用。

### Windows 系统通知

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py test-push desktop
```

使用 Windows 原生 Toast API，通过隐藏 PowerShell 子进程提交；抓取文本以 XML转义+Base64作为数据传递，不插入脚本代码。显示标题、来源、短正文，配置点击打开原文（点击行为尚未人工验收）。关闭弹窗：`push.channels.desktop.enabled: false`。

本轮普通测试通知和实际计划任务测试通知均已显示且用户确认。勿扰模式、Windows通知设置、未登录交互式桌面可能影响显示；非交互环境失败安全降级到 SQLite。`submitted` 只代表系统提交，看到后可人工确认 `received`。

## 扫描、存储与故障恢复

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py scan --baseline  # 首次建立基线，当前启用渠道不推历史通知
.\.venv\Scripts\python.exe -X utf8 run.py scan --push
.\.venv\Scripts\python.exe -X utf8 run.py push             # 重试当前启用渠道的待处理/明确失败消息
.\.venv\Scripts\python.exe -X utf8 run.py status
.\.venv\Scripts\python.exe -X utf8 run.py history --limit 20
.\.venv\Scripts\python.exe -X utf8 run.py history --id '从历史输出复制的通知ID'
```

不需要同时启用两个源。门户失败不会阻止 BYR；推送失败不会丢掉通知。scan 不带 --push 也会保存原文和生成 outbox；之后可以单独 push。当前版本处理所选关注源的有效新正文/文本更新，基础模式的范围通过版面和栏目控制，smart.enabled开启时使用已校验的分析或本地规则分级；AI失败仍基础提醒。详见Phase 2教程。未完成正文抓取的列表元数据仍存库，但不推送；已确认存在学校附件的纯附件通知会按标题提醒，并明确附件正文尚未提取。附件名称、链接变化也会触发更新检测。已有完整正文不被临时失败覆盖。

默认 `.local\data\<账号作用域>\insight.sqlite3`（位于本项目目录下），四张主表：

| 表 | 内容 |
|---|---|
| notices | 原始标题、时间、来源、URL、正文、私有标记、哈希、当前版本 |
| analyses | 历史预留表；Phase 2分析使用独立analysis_cache |
| deliveries | 每通知版本/渠道的 outbox、状态、尝试次数、流水号 |
| sync_runs | 每源采集时间、数量、错误与失败状态 |

学校密码不进数据库。保存新账号会生成独立随机作用域，旧账号历史和未发消息不会发送给新账号。旧作用域仍留在本机，清除凭据不等于删除历史；请保管好本机用户账户和数据备份。数据库保存通知原文，**目前没有对 SQLite 内容加密，专用 .local 目录已在本机限制为当前用户、SYSTEM和管理员访问**，宜启用 Windows设备/磁盘加密，勿共享或放到公共同步目录。

区分 `ok / no_new / adapter_unverified / network_failed / login_expired / access_denied / structure_changed / partial_failed`。采集/推送失败退出非零，计划任务可看到失败。每渠道分别记录，不因一个渠道成功而跳过另一个失败渠道。

明确业务拒绝会有限重试；网络读取超时、服务端500或发送中崩溃记 `unknown`，避免服务实际上受理后再自动发一遍。先核对微信/服务后台，再显式执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py delivery retry 你的记录ID
.\.venv\Scripts\python.exe -X utf8 run.py push
```

第三方发送和本地数据库不能跨网络事务提交，因此不宣称绝对 exactly-once。当前按版本和渠道防重，模糊结果交由本人核对。失败队列即使下次无新通知也会被处理；同一个 OS 文件锁防止定时任务重叠运行。

## 每天定时扫描

先完成真实账号、正文、微信/桌面测试，再注册：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py schedule install
# 自定义每天时间，使用 Windows 系统时区，请确认设为 UTC+8 北京时间
.\.venv\Scripts\python.exe -X utf8 run.py schedule install --times '07:30,12:30,19:00'
# 查运行结果或立刻试跑
Get-ScheduledTaskInfo -TaskName BUPTInsight
Start-ScheduledTask -TaskName BUPTInsight
# 移除
.\.venv\Scripts\python.exe -X utf8 run.py schedule remove
```

使用当前用户、有限权限、Interactive登录模式，保证使用同一 Credential Manager 和 DPAPI 身份；运行器通过隐藏 PowerShell 启动，并将安全状态输出记入 `.local/logs/scheduler.log`；不保存 Windows 登录密码，不启用 SYSTEM运行。注册后回查触发器数量，重复安装替换同名任务。脚本默认阻止重叠，最长45分钟。若版面多，请减少 rows_per_board/版面数量或合理调整超时。

电脑关机不能运行；默认不主动唤醒休眠，错过时间后尽可能补跑；用户未登录、VPN断开、校园网络不可达时无法采集。桌面通知还要求可用交互式桌面。校内会话过期和验证码/MFA可能需要人工重新认证，无法保证输入一次后永久免操作。本机已注册每天07:30、12:30、19:00运行的BUPTInsight任务；实际任务已执行并发送测试提醒，用户确认收到。验收证据见 docs/VALIDATION.md；在其他电脑上仍需按上面的命令注册。

## 安全退出和清除

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py logout portal
.\.venv\Scripts\python.exe -X utf8 run.py logout all --clear-credentials
```

logout 删除本项目本地会话，不声称能撤销学校/其他浏览器或设备的全部登录状态；需要时访问学校官方退出页面。`--clear-credentials` 同时清除学校凭据、两个微信密钥、PushPlus AccessKey及AI密钥。单独清除学校凭据也支持 `credentials clear`。`credentials token` 输入空字符串可以删除对应推送密钥。

会话采用当前用户 Windows DPAPI，不能跨用户/电脑直接复用。程序无明文凭据 fallback，不发送账号密码给第三方代理，不上传学校 Cookie/验证码，不绕过学校限制。Python 字符串在内存中不能保证即时清零；凭据在认证时短暂存在内存，关闭进程后释放。config.yaml、.env、.local/ 状态/数据库/恢复副本/日志和测试输出均在 .gitignore 中排除；提交前仍应检查暂存内容。

## 自动化测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

覆盖虚构 CAS/门户 HTML、恶意跳转、动态参数、ST回调、业务页面验证、原 BYR选择器与虚构页面抓取、SQLite版本/渠道去重、失败恢复、隐私、故障隔离、进程锁。Windows组件测试会创建带随机名称的虚构 Credential Manager 项并在 finally 删除，同时验证真实 DPAPI往返；不接触真实学校凭据、不访问微信发送接口。测试输出限定在 `.test-output/tmp`，运行测试会清理该专用临时目录，不要将自己的文件放进去。

详见 [验收记录与当前结果](VALIDATION.md)。

## 下一步：按验收门槛推进

1. 已完成本机 HTTP 门户认证和列表/正文校准；继续观察会话过期与网络中断恢复。官方浏览器 iframe 空白仍需按校方策略排查。
2. BYR重点版面已完成真实采集。按用户选择暂时使用桌面；未来启用微信后仍需实际接收确认。持续多日观察重认证、限频与失败队列。
3. Phase 2已实现OpenAI兼容分析、严格证据校验、失败回退、缓存和隐私开关；真实模型API及真实画像个性化效果尚待验证。先完善个人画像并观察规则误报，再显式授权和联调所选模型。
4. 结构化画像及匹配接口已经提供；后续在独立复标样本上评估模型，再按需要扩展Markdown/PDF导入与检索。

## 许可证与原项目

保留根目录 MIT LICENSE。主项目：[bupt-information-collector](https://github.com/yantingweb/bupt-information-collector)。认证行为参考：[where_to_study](https://github.com/Nemoyuzx/where_to_study)（GPL-3.0，仅审计，未复制代码）及 [bupt-auth](https://github.com/byrdocs/bupt-auth)（MIT，仅审计）。文件级发现、协议边界和分发注意事项见 [AUDIT.md](AUDIT.md)。

实际门户入口包含 index.jsp 到学生首页的静态脚本跳转。HTTP 适配器只跟随已观察到的同门户字面量跳转，不执行任意网页脚本。真实通知列表含较旧的置顶公告，本机配置启用 sort_latest_first，按发布日期选择扫描窗口。重新保存学校凭据可运行 `deploy/Reenter-Credentials.ps1`，所有输入保留在本地。

### 手动执行和计划任务的数据一致性

2026-10-14 本机联调曾发现 AppData 路径下两个执行入口的数据库记录不一致，并出现完整性异常。原始文件及恢复副本保存在 `.local/recovery/`，未覆盖；正式库改为工作区内受保护的 `.local/data/`，采用 SQLite DELETE 日志模式和 FULL 同步，继续由操作系统文件锁保证单写入者。打开数据库先执行 quick_check，异常时停止写入并明确报 storage_corrupt，不自动清空或假报成功。

跨执行入口的计划任务试跑已核对真实 sync_runs 记录、通知投递和 integrity_check；不只检查任务退出码。工作状态中提供 database_path，便于确认各入口使用同一文件。Phase 1修复时曾通过重新采集建立基线；Phase 2未重建或清空它。当前新增在线备份与恢复防覆盖，见docs/PHASE2.md。不要删除或提交 .local；迁移到另一台电脑时需重新保存 Windows 凭据并重新认证DPAPI会话。

## Phase 2 日常入口

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py backup create
.\.venv\Scripts\python.exe -X utf8 run.py backup list
.\.venv\Scripts\python.exe -X utf8 run.py health
.\.venv\Scripts\python.exe -X utf8 run.py profile path
.\.venv\Scripts\python.exe -X utf8 run.py profile validate
.\.venv\Scripts\python.exe -X utf8 run.py ai demo
.\.venv\Scripts\python.exe -X utf8 run.py ai evaluate
```

新电脑用profile init创建空白画像；本机已创建，直接编辑profile path给出的本地文件。真实密钥只用ai key本地安全输入，不要发到聊天。ai.mode使用字符串`"off"/"mock"/"api"`。恢复默认只预览，不会静默覆盖。完整API配置、授权范围、模拟评估和剩余限制见[Phase 2教程](PHASE2.md)。

## 个人兴趣与实际效果评估

已增加`recommend`本地解释预览、`feedback`相关/无关反馈，以及`evaluate`真实历史冻结、盲标和方法对比。反馈不会重发已通知历史；私人评估快照只留在账号隔离的.local目录。完整使用方式、8条本人真实兴趣标注结果和未验证限制见[个性化审计与验证](PERSONALIZATION.md)。
