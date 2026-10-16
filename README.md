# BUPT Insight

一个只在个人电脑上运行的北邮校园信息阅读器。把信息门户和北邮人论坛集中在一个页面：浏览科研、竞赛、实习、电子科创与教务信息，阅读、搜索、收藏，并按本人兴趣获得可解释的推荐。

**本地地址：[http://127.0.0.1:8765](http://127.0.0.1:8765)**

## 每天怎么用

本机已经配置好：双击桌面 **BUPT Insight** 即可打开。也可以双击项目目录的 **打开 BUPT Insight.cmd**。

- **为你推荐**：未读优先；较早历史放后面，推荐只是线索。
- **最新收录**：查看新收录或正文更新，发布时间单独显示。
- **全部历史**：不受推荐结果限制，按主题、来源、关键词查找。
- 点标题打开完整阅读面板，或打开学校/论坛原文。
- 阅读、收藏与反馈保存在本机；正文真正变化后会重新标为未读。
- 不感兴趣的内容可以恢复，不会永久删除；重要教务事项受保护。

关闭浏览器即可结束阅读。若想停止本地网页服务，双击桌面 **关闭 BUPT Insight** 或同名cmd。它只停止阅读服务，**不会停止Windows定时采集**。再次双击打开即可重新启动；重复打开不会再创建一个服务。

## Windows 11 安装

需要Python 3.12和Microsoft Edge。在项目目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 run.py init
```

第一次使用的新电脑需要本地配置账号和采集适配器：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py credentials save
.\.venv\Scripts\python.exe -X utf8 run.py portal test --mode http
.\.venv\Scripts\python.exe -X utf8 run.py login byr
.\.venv\Scripts\python.exe -X utf8 run.py scan --baseline
```

账号密码只在本地不回显输入，写入Windows Credential Manager。config.example.yaml的门户身份与列表字段需要按本人授权页面校准，**模板不能直接代替真实配置**。本机已完成配置，无须重新输入账号或重建基线。详细认证/适配说明见[CLI与安装指南](docs/CLI-GUIDE.md)。

安装桌面快捷方式：

```powershell
powershell.exe -NoProfile -File deploy/Install-ReaderShortcuts.ps1
```

也可以手动启动，关闭时按Ctrl+C：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py web --open
```

服务只监听127.0.0.1，默认端口8765；不支持通过参数开放公网。端口冲突时可用`web --port 8766 --open`。双击脚本仅对本次可信本地脚本使用ExecutionPolicy Bypass，不修改Windows全局策略；也可使用上面正常PowerShell方式启动。

## 自动更新与真实状态

复用现有Windows任务，每天07:30、12:30、19:00采集。新电脑注册一次：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py schedule install
```

网页每30秒检查本地更新，有变化会提示刷新，不会打断正在阅读的内容。网页上方显示两源**最后实际成功采集时间**，区分无新增、采集失败、登录过期和任务未完成；刷新网页不等于重新采集。

电脑关机、休眠、用户未登录或校园网/VPN不可达时可能无法更新。Web服务不承担采集任务；不打开网页也可以定时扫描。不要把收录时间当发布时间，较早资料会明确标记；旧活动是否有效仍需看原文。

## 个性化与反馈

当前网页只使用本地规则，不调用大模型。科研、实习、竞赛与活动等兴趣由本人在本地画像中编辑：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py profile path
.\.venv\Scripts\python.exe -X utf8 run.py profile validate
```

推荐面板给出推断与逐字原文证据；日期不足时明确未知，不猜报名资格。网页反馈会立即本地保存，采集任务忙时稍后同步到原反馈模块。收藏不等于重要反馈，“收到通知”也不等于“与我相关”。

附件、图片型正文目前只提示打开原文，未实现OCR或附件全文提取。规则可能误判或漏掉机会，所以保留完整历史入口。[画像、实际评估与限制](docs/PERSONALIZATION.md)。

## 本地数据与安全

`.local/data/<账号作用域>/insight.sqlite3`保存采集历史；同目录的`reader.sqlite3`保存阅读、收藏与反馈待同步记录。网页以只读连接读取采集库，阅读状态使用独立事务，避免等候长时间网络扫描。反馈同步遵守原OS写入锁，不触发重推或改变delivery。

原库沿用DELETE日志、FULL同步、单写入锁与在线备份。阅读记录在服务启动时按日额外在线备份，保留7份。两种库均未额外加密，依赖本人Windows账户和受限目录，应保管好设备和备份。

学校凭据、Cookie、Session、Token、真实画像、通知正文、数据库、日志、截图和备份都不提交Git。页面不加载远程字体、图片或脚本，正文按纯文本展示；本机Host检查、CSRF、SameSite Cookie和CSP限制跨站操作。云端私人门户/画像分析默认关闭，微信当前关闭。

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py health
.\.venv\Scripts\python.exe -X utf8 run.py backup create
.\.venv\Scripts\python.exe -X utf8 run.py backup list
```

恢复默认先预览并核对指纹，不能静默覆盖真实库。备份恢复和可选模型配置见[Phase 2指南](docs/PHASE2.md)。阅读记录的独立备份位于`reader-backups/`，原库恢复不会自动回退收藏与已读状态。

## 开发与GitHub同步

仓库：[LiJunhao09100910/bupt-insight](https://github.com/LiJunhao09100910/bupt-insight)。`origin`指向本仓库；`upstream`保留原项目地址与MIT历史，不强推覆盖远程。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
.\.venv\Scripts\python.exe -X utf8 -m tools.audit_git --staged
```

结构：`core/`为采集流水线与网页服务，`sources/`为两源适配器，`web/`为本地模板/CSS/JS，`deploy/`为Windows一键入口，`tests/`仅包含虚构测试数据，`docs/`为审计与验收。无Node构建链、前后端分离服务或向量数据库。

新增改动走正常分支/提交/推送流程；提交前检查`git diff --cached`和隐私审计。GitHub登录使用Git Credential Manager正常浏览器流程，**不要把密码或PAT写进远程URL**。审计检查待提交树和全部可达历史中的私有路径、已保存凭据及常见密钥格式，但仍需人工检查正文与个人资料。

[网页真实验收](docs/WEB-VALIDATION.md) · [源码与许可证审计](docs/AUDIT.md) · [原CLI完整指南](docs/CLI-GUIDE.md)

## 许可证

保留原项目[yantingweb/bupt-information-collector](https://github.com/yantingweb/bupt-information-collector)的MIT许可证及历史。where_to_study（GPL-3.0）和bupt-auth（MIT）仅作协议审计参考，未复制其实现。分发依赖需遵守各自许可证；本仓库不含私人校园数据库或认证状态。
