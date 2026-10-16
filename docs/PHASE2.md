# Phase 2：可靠性与个性化分析

> 2026-10-16更新：本人已配置真实兴趣，新增反馈与真实历史评估；本文件的空白画像描述是Phase 2初次交付状态。当前结论见[个性化审计与验证](PERSONALIZATION.md)。

2026-10-15。在已有认证、抓取、SQLite和Windows通道上增量实现；没有重建真实基线，没有修改门户/CAS认证、BYR登录或Windows Toast底层实现。Phase 1审计与历史证据仍保留在AUDIT.md、VALIDATION.md。

## 快速使用

本机已开启安全自动备份和智能本地规则，模型模式为`off`，两个云端隐私授权为false，微信继续关闭。当前画像为空白，不包含虚构示例中的背景。所有命令在项目目录执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py health
.\.venv\Scripts\python.exe -X utf8 run.py backup list
.\.venv\Scripts\python.exe -X utf8 run.py profile path
.\.venv\Scripts\python.exe -X utf8 run.py profile validate
.\.venv\Scripts\python.exe -X utf8 run.py ai demo
.\.venv\Scripts\python.exe -X utf8 run.py ai evaluate
.\.venv\Scripts\python.exe -X utf8 run.py scan --push
```

新电脑可先`profile init`创建空模板。根据`profile path`输出在本地编辑YAML，填写年级、专业、学业阶段、研究方向、技能、项目、竞赛、目标、关注和排除项、提醒偏好，再执行`profile validate`。默认放在当前账号的`.local/data/<scope>/profile.yaml`。`examples/profile.example.yaml`全部虚构，并带`is_example: true`；加载器拒绝将它作为真实画像。不要把真实背景填入Git里的模板。

```powershell
# 先用 history 获取本地通知ID，分析与查看结果；不会创建新的推送记录
.\.venv\Scripts\python.exe -X utf8 run.py history --limit 10
.\.venv\Scripts\python.exe -X utf8 run.py ai analyze --id '复制本地通知ID'
.\.venv\Scripts\python.exe -X utf8 run.py ai show --id '复制本地通知ID'
```

`ai demo --notify`可向本机发送并记录一条明确标为虚构资料的智能测试提醒；不会访问真实模型。

`ai analyze`也支持`--limit 3`和`--mode off/mock/api`。`ai show`是本人本地查看工具，会显示分析文本；不要将私人输出贴入公共日志。常规scan、status、health、profile validate只输出数量、状态和指纹，不输出画像或正文。`ai show`可能显示旧策略/旧画像的最后一次结果，查看当前画像效果前重新analyze；推送只使用当前缓存键对应的结果。

## 在线备份与恢复

使用[Python Connection.backup](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)和[SQLite Online Backup API](https://www.sqlite.org/backup.html)，不直接复制正在运行的库。源库先完整性及外键检查，分批备份到同目录随机临时文件，源与备份再次检查，关闭句柄、fsync，再原子替换最终文件；SHA256和账号作用域写入清单。没有清单或校验不符的文件不会当有效备份恢复。

每次扫描结束检查是否到期；默认24小时一次，保留最近7份有效自动快照。配置`backup.enabled/interval_hours/keep`。手工`backup create`也属于snapshot保留集合；`before-restore`安全快照、损坏或孤立文件不由保留策略删除。备份在当前账号库的`backups/`子目录，沿用`.local`权限与Git排除。备份包含敏感原文和分析，**没有额外数据库加密**，请保管Windows账户、磁盘与备份介质。

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py backup create
.\.venv\Scripts\python.exe -X utf8 run.py backup list
.\.venv\Scripts\python.exe -X utf8 run.py backup verify 'snapshot-实际文件名.sqlite3'
# 第一步只预览；不会覆盖
.\.venv\Scripts\python.exe -X utf8 run.py backup restore 'snapshot-实际文件名.sqlite3'
# 自行核对预览后，使用它给出的当前库指纹；库变化后旧指纹无效
.\.venv\Scripts\python.exe -X utf8 run.py backup restore 'snapshot-实际文件名.sqlite3' --confirm '预览的SHA256'
```

所有恢复和备份CLI与采集使用同一个OS锁。仅接受当前账号备份目录的文件名，禁止跨作用域或路径穿越。原库可读时恢复前创建安全快照，合并当前库已投递/已建立基线的内容哈希凭据，减少退回旧快照后的重复推送；历史汇总中不确定的批次保留unknown，需人工核对。备份之后新增但未备份的原文可能不在恢复库中，安全快照保留它们。

如果当前库已损坏，拒绝原地覆盖，因为其投递记录无法可靠合并。可运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py backup recover-copy 'snapshot-实际文件名.sqlite3'
```

它在同一账号目录生成已验证的`recovered-*.sqlite3`副本，待发送状态置unknown，**不切换生产路径、不覆盖损坏库**。需人工核对备份后的数据缺口和投递后再安排切换；本版没有自动激活损坏库恢复副本的功能。此前`.local/recovery/20261014-080910/`证据不在任何保留/恢复清理范围内。

备份失败不会阻止抓取落库和已有提醒，但scan报告backup.failed并返回非零。健康检查分别显示成功采集年龄、最后实际获取数据年龄、最近失败/卡住任务、可校验备份年龄和失败投递数。默认超过24小时没有成功采集或获取数据会报告attention；no_new且total>0仍算有效采集，空列表不等同于取到了通知。health依赖本地sync_runs，不声称退出码0或网站HTTP200就是业务正常。计划任务没有运行时health命令也不会自己唤醒电脑，需查看计划任务与日志。

## 模型与隐私配置

```yaml
ai:
  mode: "off"                # off / mock / api
  base_url: ""               # OpenAI兼容 /v1 根地址，不含/chat/completions
  model: ""                  # 自行填服务商支持的模型名称
  response_format: json_schema
  timeout_seconds: 8
  retries: 1
  budget_seconds: 12
  max_per_run: 20
  max_input_chars: 6000
  allow_private_cloud: false
  allow_profile_cloud: false
smart:
  enabled: true
```

- `off`不调用模型：smart开时用本地规则，smart关时完全保留基础提醒。
- `mock`使用明确标记的确定性模拟结果，不访问网络，不能当作真实模型联调。
- `api`调用兼容Chat Completions，优先json_schema；服务不支持时可显式改json_object，仍须本地严格校验，不自动降级结构约束。接口按[OpenAI官方结构化输出文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)实现；不同兼容服务的参数支持需要另行联调。

密钥在本地交互式终端用`python run.py ai key`保存至现有Windows Credential Manager，也支持进程环境`LLM_API_KEY`。Base URL和模型支持`LLM_BASE_URL/LLM_MODEL`覆盖。不要把密钥写入config.yaml、.env、命令行或Git。`logout all --clear-credentials`也会删除AI密钥。

**两个独立授权：** 外部API分析portal源或private=true通知，必须手工设`allow_private_cloud: true`；外部API接收结构化画像，还须独立设`allow_profile_cloud: true`。没有授权时门户只在本地规则分析；画像授权关闭时模型收到空画像，在本地进行实际画像匹配。启用前应了解第三方服务的数据保留政策；没有统一承诺可以代替它的政策。

实际模型请求只包括标题、最多6000字符正文、发布日期、来源代号，以及经授权的结构化画像。不发送原始URL、通知ID、作者、Cookie、Session、ST或学校凭据。对文本中的链接、邮箱、长数字标识和常见认证字段进行最小化脱敏；无法保证识别所有姓名或私人信息，所以脱敏**不能代替授权**。只允许外部HTTPS，禁止含凭据/query的Base URL、禁止重定向、不使用环境代理。loopback地址`127.0.0.1/::1/localhost`可使用本地HTTP模型并在本机处理私人内容；本地模型是否另行外传由用户控制，当前尚未做真实本地模型联调。

## 分析、证据与提醒策略

结构化结果由Pydantic严格校验，字段涵盖类别、摘要、关键事项、截止及证据、资格、重要性、个人相关性、理由、帮助、资格匹配未知、行动、待核实项与置信度。用explicit/inferred/unknown区分原文、推断和未知。摘要首版采用原文摘录，资格和关键事项逐字证据必须属于实际模型输入；日期必须有明确完整年份和截止语义，多截止或相对日期不猜测。仅规范到天，原文证据保留时刻；不能以结构化日期替代原文18:00等时刻。

正文和画像均作为不可信数据，system提示要求不执行其指令。没有工具、链接访问或任意代码执行。检测到常见提示注入、正文不完整、拒绝、无效JSON、缺少证据或低置信度会回退；提示注入检测不是万能防线，模型输出仍可能有语义错误，用户需打开原文核实。系统始终不宣称资格已被正式验证。

缓存键包含通知ID、原文哈希、版本、画像哈希、模型/地址、策略版本及隐私策略，画像或策略变化后不会复用旧分析。失败结果30分钟冷却；失败可用本地规则结果保存在独立analysis_cache。原有analyses预留表保留不动。资料版本和投递记录相互独立；重新分析不生成新的delivery，因此不会仅因换模型、改画像而再弹窗。

采集完成后，在默认12秒总预算内分析最多20条待提醒通知。真实API运行在可终止的本地子进程，每条默认8秒上限，即使DNS或读取卡住也不会无限阻塞；只对429/502/503/504有限重试，不对超时反复请求。预算用尽的其余消息正常基础提醒，不为等待AI而扣留。分析结果只保存在本机；查看旧通知分析可显式运行ai analyze。

优先级顺序：

1. 标题/正文涉及考试、学籍、注册、选课、必修、强制等事项，由本地规则保护为即时提醒，不被兴趣排除。
2. 已验证的分析结果为高重要性、高相关性，或明确截止在未来两天内，优先即时提醒。
3. 普通消息每轮汇总，每组最多5条；点击打开该组首条原文，其余用history查看。汇总状态/成员持久化，失败仍整组重试，不拆分重复发。unknown不自动重发，核对后对任一成员执行delivery retry会显式重发整组。
4. 只有本人开启`preferences.archive_uninterested`，结果可信且低相关，并且通知确实命中本人排除词时才归档。不完整正文、无分析或模型失败均保留基础提醒。

本地画像匹配首版是明确关键词匹配，不是语义检索：可解释但会漏掉同义词和隐含机会；空画像时相关性unknown，不猜测真实专业/经历。结构化画像目前足以建立可验证闭环，暂不引入RAG。`KnowledgeProvider`接口保留未来本地Markdown/PDF检索与出处；尚无文档导入、Embedding或向量数据库。

## 测试与评估

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --junitxml=.test-output/phase2-results.xml
.\.venv\Scripts\python.exe -X utf8 run.py ai evaluate
```

保留原70项测试。新增在线快照、未提交写入隔离、恢复防覆盖/回执合并、损坏拒绝、保留策略、健康检查、画像、证据/日期校验、隐私、提示注入、缓存、AI超时、API输出失败、汇总持久化、显式重试及原提醒回退。兼容API传输测试使用真实子进程和只含虚构内容的loopback HTTP测试服务器；不访问任何真实模型。测试不读取学校真实凭据或真实数据库，不将真实正文复制到fixture。

固定24条手工编写并逐条指定标签的虚构短通知，16条开发样本、8条挑战样本。开发助手指定初始标签，用户于2026-10-15明确确认其中7条类别、截止及关键事项标签正确。真人复核子集7/7分类、7/7截止与7/7关键句正确，含2条强制事项均保留提醒。复核时展示了预先给出的标签，并非独立盲标；其余17条未经真人复核，不能声称整组为无偏金标准。当前规则分类21/24（87.5%），开发16/16、挑战5/8；7条强制事项提醒召回7/7；完整年份截止日期抽取与未知判定24/24，单一关键句字面召回24/24。三条分类错误保留在评估报告中，没有只选成功案例。以上只评估local/mock规则，不是LLM分数；小样本与简短语句也不能推断真实学校长文准确率。

完整指标、混淆矩阵及不足见[phase2-evaluation.json](phase2-evaluation.json)。真实验证与模拟验证总结见[PHASE2-VALIDATION.md](PHASE2-VALIDATION.md)。
