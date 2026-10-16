# BUPT Insight 验收记录

日期：2026-10-14，北京时间。实际环境：本机 Windows、Edge、Python 3.12.14；校园网或学校 VPN。源码与许可证审计见 [AUDIT.md](AUDIT.md)，安装和全部 CLI 用法见 [README](../README.md)。

## 当前结果

门户正确凭据的 HTTP/CAS 认证已经实际成功，校验了当前账号身份、受保护业务区域及真实通知列表，取得标题、发布时间、来源、链接及正文。门户20条中18条有文字正文，1条仅有附件，1条仅有图片；后两种内容明确标注未提取，不编造正文。BYR七个版面共70篇原帖已实际读取正文。密码初次输入错误导致的401属于此前失败尝试，不代表当前状态。

Windows普通测试通知、实际Windows计划任务发送的虚构测试通知均由用户明确确认看到了。计划任务试跑同时在当前数据库生成门户及BYR采集记录，不能只凭任务退出码0判断成功。按用户最新选择暂时只使用Windows提醒，微信关闭，没有真实微信收件验收。

## 功能验收表

| 功能 | 状态 | 证据与限制 |
|---|---|---|
| 三个项目源码与许可证审计 | 实际验证通过 | 固定提交、文件级改造、MIT/GPL边界见AUDIT.md |
| 门户直接HTTP/CAS认证、ST回调 | 实际验证通过 | 真实账号授权页面；动态参数及HTTPS认证；不同系统Token未混用 |
| 当前账号身份与受保护业务校验 | 实际验证通过 | `.topinner`、`#tzxw`；匿名访问同页面会转官方CAS |
| 门户通知列表和文字正文 | 实际验证通过 | 20条元数据，其中18条真实文字正文 |
| 附件/图片通知识别 | 实际验证通过 | 各1条，明确未提取附件或图片内正文 |
| 附件文字提取、图片OCR | 待验证 | 尚未开发 |
| 门户有效会话复用 | 实际验证通过 | 已登录会话访问时密码POST次数为0 |
| 门户重复采集去重 | 实际验证通过 | 重复20条no_new；实际任务小样本再次no_new |
| 浏览器认证iframe呈现 | 失败 | 标准Edge实际iframe为空；未绕过学校安全脚本 |
| 浏览器自动登录回退、验证码/MFA | 待验证 | 已实现入口和人工提示，未完成真实账号成功联调 |
| 门户HTTPS业务入口 | 失败 | 当时连接失败；官方HTTP门户→HTTPS CAS正常，业务HTTP存在传输隐私限制 |
| BYR独立登录、列表和原帖正文 | 实际验证通过 | Paper、ParttimeJob、MathModel、Innovation、ACM_ICPC、AcademicAffairs、SCS，各10篇 |
| BYR帖子ID与重复扫描去重 | 实际验证通过 | 首次与重复扫描已比较；Task试跑重复样本no_new |
| 正文更新触发新版本推送 | 仅模拟测试通过 | 虚构正文修改及哈希、版本、渠道唯一约束测试 |
| 过期、空列表、网络错误、结构变化区分 | 仅模拟测试通过 | 分类分支测试；另有真实错误密码响应验证，不把所有异常当无新通知 |
| Windows Credential Manager与DPAPI | 实际验证通过 | 实际本机组件往返；学校凭据仅本地输入，Cookie加密保存 |
| SQLite原文、历史和采集记录 | 实际验证通过 | 真实内容入库；新库完整性检查通过，旧损坏库保留，见下文 |
| 推送失败重试、故障隔离与未知结果 | 仅模拟测试通过 | 故障注入；unknown不盲目重发，不丢弃原文 |
| Windows弹窗与通知中心显示 | 实际验证通过 | 用户确认普通测试及实际计划任务虚构测试提醒 |
| Windows点击原始链接 | 待验证 | 已实现protocol activation，未人工点击验证 |
| 非交互式桌面安全降级 | 待验证 | 已实现检查和落库，未以非交互身份实测 |
| Windows Task Scheduler安装与执行 | 实际验证通过 | 当前用户Interactive任务；实际采集记录及用户确认收到提醒 |
| 每天三次、多日稳定运行 | 待验证 | 已设07:30、12:30、19:00；尚无多日观察证据 |
| 微信官方API地址、业务码核对 | 实际验证通过 | 核对官方PushPlus/Server酱文档，不代表收件成功 |
| 微信发送、隐私裁剪与回执逻辑 | 仅模拟测试通过 | 业务失败、超时、accepted/provider_delivered区分测试 |
| 微信真实发送与收件 | 待验证 | 用户选择暂不使用，两个微信渠道关闭 |
| AI分析与个人知识库 | 待验证 | 按阶段优先级尚未开发；analyses仅预留表 |

## 自动化测试

最近运行：`.venv\Scripts\python.exe -X utf8 -m pytest -q --junitxml=.test-output/results.xml`，**70 passed，9.58秒，0失败、0错误、0跳过**。摘要见[test-summary.json](test-summary.json)。包括本机Credential Manager/DPAPI实际组件测试，以及Edge加载虚构HTML；认证协议与学校页面分支使用Mock、脱敏或虚构样例，不能据此声称学校真实登录。测试没有发送微信、没有使用或输出真实密码。

另已完成Python编译、依赖一致性和PowerShell语法检查。真实账号、采集和任务验收来自单独实际运行。

## 存储问题与修复记录

早期计划任务试跑出现交互环境与任务环境数据记录不一致，随后原AppData数据库完整性检查失败。具体根因没有定论，不能声称退出码0的旧试跑已完成业务。已暂停原试跑并保留原文件及副本，复制到`.local/recovery/20261014-080910/`。官方SQLite恢复工具在副本上仅恢复1条通知，不能声称90条历史全部救回。

当前使用项目目录下`.local/data/<账号作用域>/insight.sqlite3`，采用DELETE日志、FULL同步、单进程写入锁，打开时先quick_check；损坏时停止写入并要求保留原库。`.local`在本机限制当前用户、SYSTEM及管理员访问，且不入Git。有效加密会话迁入新目录，密码仍在Credential Manager。当前窗口中的校园通知通过重新采集建立基线，避免重推历史；这是重新抓取，不是恢复全部旧历史。

修复后实际计划任务在同一新库生成portal/byr运行记录，两源样本均no_new，虚构提醒投递一次并由用户确认看到。证据见[scheduler-live-validation.json](scheduler-live-validation.json)、[scheduled-toast-validation.json](scheduled-toast-validation.json)。完整重建记录见[restored-live-baseline.json](restored-live-baseline.json)。仍需日常备份和多日运行观察。

## 可复核证据与后续

- [门户联调](portal-live-validation.json)：真实20条、正文类型、匿名访问与会话复用；不含正文、密码、Cookie或ST。
- [完整首次基线](full-baseline-validation.json)与[当前重建基线](restored-live-baseline.json)：历史运行与修复后运行分开记录。
- [审计](AUDIT.md)：三个仓库实际源码、提交、认证边界、文件改造与许可证。
- 当前每天07:30、12:30、19:00执行，系统时区为China Standard Time。电脑关机不能运行，默认不唤醒休眠；用户未登录、校园网/VPN断开或人工认证挑战可能中断。
- 先观察所选Windows提醒链路多日稳定性，再考虑附件提取、用户授权的AI与个人画像；微信如未来启用，必须另做真实收件验收。
