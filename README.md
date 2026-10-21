# BUPT Insight

一个只在个人电脑上运行的北邮校园信息阅读器。把信息门户和北邮人论坛集中在一个页面：浏览科研、竞赛、实习、电子科创与教务信息，阅读、搜索、收藏，并按本人兴趣获得可解释的推荐。

**本地地址：[http://127.0.0.1:8765](http://127.0.0.1:8765)**

## 每天怎么用

本机已经配置好：双击桌面 **BUPT Insight** 即可打开。也可以双击项目目录的 **打开 BUPT Insight.cmd**。

- **为你推荐**：仅保留近30天未读、有明确兴趣依据且未过期的机会，普通最多8条、每类最多3条；重要教务另列。已读内容移出精选，完整历史不删除。
- **最新收录**：查看新收录或正文更新，发布时间单独显示。
- **全部历史**：不受推荐结果限制，按主题、来源、关键词查找。
- **本科科研招募**：汇集近90天科研合作、导师和实验室招募，默认按发帖时间排序，已读仍可查看。分别展示本科资格、在研/补实验和署名的原文线索；未提及的事项明确标为未知，不推断二作、三作或尚未投稿。
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

论坛采集按关注版面逐一读取列表，再逐帖读取首帖正文，不是全站关键词搜索或无限遍历。默认优先科研与论文版（Paper）前3页、每页最多30条，其余关注版面首页最多10条；补充机器学习、机器人和信通学院版。列表通常按最后回复排序，因此推荐与科研专栏使用原始发帖时间，旧帖被顶起不会变成新招募。置顶帖不采集，跨页按链接去重。可在本机 `sources.byr.board_overrides` 调整版面的 `pages` 和 `rows_per_page`（上限分别10和100）；分页失败会保留已获取内容并报告部分失败。

科研专栏排除明确只招研究生、不招本科、已招满、已截止及求指导类信息；未写截止时间的条目仍需自行确认是否在招。仅有“发表论文”“主要作者发表经历”不视为本次合作的署名承诺。图片、附件、历史置顶和未覆盖版面可能仍有遗漏。

电脑关机、休眠、用户未登录或校园网/VPN不可达时可能无法更新。Web服务不承担采集任务；不打开网页也可以定时扫描。不要把收录时间当发布时间，较早资料会明确标记；旧活动是否有效仍需看原文。

## 个性化与反馈

当前网页只使用本地规则，不调用大模型。科研、实习、竞赛与活动等兴趣由本人在本地画像中编辑：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py profile path
.\.venv\Scripts\python.exe -X utf8 run.py profile validate
```

推荐面板给出推断与逐字原文证据；日期不足时明确未知，不猜报名资格。网页反馈会立即本地保存，采集任务忙时稍后同步到原反馈模块。收藏不等于重要反馈，“收到通知”也不等于“与我相关”。

网页按标题主题与明确适用对象分类，正文中偶然出现“科研”“申请”不会把人事事务变成科研机会。“必须掌握某技能”也不等于必须办理的教务事项。明确限定研究生/博士后的机会不会按本科生机会推荐；资格不明确时仍需核对。规则筛选不是人工核实，首页少量精选也不代表已验证推荐准确率。

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
