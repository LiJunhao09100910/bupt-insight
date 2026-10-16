# 可验证的个性化筛选：审计、使用与本轮验证

2026-10-16。在现有Python CLI与SQLite上增量改进，没有重写认证、BYR采集、SQLite基础存储或Windows通道。Phase 2历史验收仍保留；本文件区分工程能力、真实兴趣标签和模型效果。

## 真实实现审计

| 能力 | 实际发现 | 本轮处理 |
|---|---|---|
| 采集与存储 | 门户/BYR真实记录持续增长，库完整性正常；已有在线备份和作用域隔离 | 开发前在线备份，不清库、不重建基线 |
| 运行健康 | 当天12:30任务返回3221225786，BYR仍为running；任务已Ready且无Python任务残留 | 保留失败证据；正常扫描将旧记录改为interrupted，重新实际采集验证 |
| 画像 | 字段可编辑，但原为空白；背景、经历字段大多未参与本地匹配 | 使用本人明确提供的背景与四类兴趣，不猜研究细分方向或经历 |
| 相关性 | `analysis.rules`按原始短语包含关系判断；长短语易漏检，一个词出现也可能误判机会 | 增加可配置主题别名、机会意图、冲突提示与逐条原文证据；仍明确是规则 |
| 云端模型 | 接口、结构校验和超时回退已实现，无真实效果证明；画像未授权时会用本地结果覆盖AI相关性 | 评估报告区分AI+本地覆盖、授权模型画像及本地模型，不冒称独立AI个性化 |
| 提醒偏好 | 原高相关直接即时提醒，会绕过ordinary=digest | 增加relevant偏好，本人的普通相关消息也汇总 |
| 评估 | 旧24条虚构样本主要测分类/日期；没有真实用户无关提醒率和解释评分 | 冻结真实历史与真实画像；盲标表不展示预测；旧规则/新规则/API分开报告 |
| 反馈 | 原只有“收到”确认，没有“相关/无关”判断 | 新增版本和画像绑定的feedback，与delivery分离 |

Windows退出码对应Microsoft文档的[STATUS_CONTROL_C_EXIT](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55)，但不能凭代码断定是谁或什么操作中断了任务。本轮恢复正常运行不等于证明中断根因已消除。

## 画像：描述希望获得什么，附可检查的表达

本人画像只保存在`.local/data/<账号作用域>/profile.yaml`。用户明确提供的学业背景、科研/实习/竞赛/活动关注与汇总偏好已经写入；未提供的技能、经历、排除项留空。默认云端门户正文和画像授权仍关闭。

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py profile path
.\.venv\Scripts\python.exe -X utf8 run.py profile validate
.\.venv\Scripts\python.exe -X utf8 run.py recommend --limit 10
```

以下只演示配置格式，不是用户资料：

```yaml
interests:
  - name: 希望参与的科研方向
    description: 希望寻找实际可以申请参与的课题或研究助理机会
    terms: [科研, 实验室, research assistant]
    intents: [招募, 申请, 招新, 开放]
    avoid: []
preferences:
  ordinary: digest
  relevant: digest
  archive_uninterested: false
```

主题terms支持本人维护的中英文别名；intents表达希望看到的机会行为，只有主题且没有意图时降为medium而非断言是可参与机会；avoid命中时保留冲突提示。ASCII词有边界检查，例如AI不应匹配email。每个判断给出主题、命中表达、原文短证据和推断理由。正负兴趣冲突也不能自动断言无关。

这仍是可解释的词与意图规则，**不具有开放语义理解能力**：同义表达要显式添加，资格判断保持未知；“校内”“本科适用”等复杂条件未被可靠判定。description为未来模型提供语境，本地不会假装理解自然语言长描述。研究生比赛可能仍对本科用户有参考价值，不从年级直接判为无关。

本轮比较了替代方向：

- 原短语规则轻量、可复现，但容易漏掉“实习资源”与“实习生招聘”这类表达差异。
- 显式主题别名+意图适合当前小规模且可解释的改进，但仍需人工标签验证，不能代替语义模型。
- TF-IDF/字符n-gram相似度可本地运行，但仍偏字面、需阈值与标签，不足以直接判定资格或通知价值；本轮没有为形式完整而增加它。
- 本地Embedding或LLM有望补充隐含语义。[Sentence Transformers官方文档](https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)说明小语料也可直接计算相似度，因此未来即使采用，也不需要先引入向量数据库。相似度仍不等于个人价值或必须办理事项；需要同一冻结集公平比较。

## 反馈闭环与安全提醒

```powershell
# 从history/recommend获取本地通知ID
.\.venv\Scripts\python.exe -X utf8 run.py feedback add --id '本地通知ID' --label relevant
.\.venv\Scripts\python.exe -X utf8 run.py feedback add --id '本地通知ID' --label irrelevant
.\.venv\Scripts\python.exe -X utf8 run.py feedback list
.\.venv\Scripts\python.exe -X utf8 run.py recommend --id '本地通知ID'
```

标签支持important/relevant/irrelevant/unsure；`--quality 1..5`可另记本人对所见解释的评价。feedback记录原文哈希、画像哈希和时间；内容或画像变更后，旧判断不自动套用。单条irrelevant是本人对该版本的明确排除，可本地归档；不会从一次点击推导整个主题都不感兴趣。本人仍可通过编辑画像调整未来表达，尚无自动训练或全局兴趣漂移学习。

考试、学籍等安全保护、分析失败/不完整、低置信度，以及临近截止或高重要性判断，不会因为单条负反馈被盲目归档。important是显式优先标记。反馈、预览与评估不新增delivery、不更改“已收到”状态，也不会把已发送历史重新弹出来。初始明确的兴趣标注写入生产feedback时，已对delivery全表前后比较，状态完全一致。

注意：旧mandatory规则仍较宽泛，论坛讨论中提到考试/选课也可能被保守保护为即时提醒；本轮没有仅为减少弹窗而放松它。新画像的relevant=digest解决普通高相关即时弹窗，但不覆盖强制事务保护。普通汇总按既有每组5条实现，汇总不等于精准过滤。

## 可复现的真实历史评估

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py evaluate freeze --limit 40
.\.venv\Scripts\python.exe -X utf8 run.py evaluate list
.\.venv\Scripts\python.exe -X utf8 run.py evaluate label '批次名' --sample n001 --label relevant
.\.venv\Scripts\python.exe -X utf8 run.py evaluate run '批次名'
.\.venv\Scripts\python.exe -X utf8 run.py evaluate rate '批次名' --sample n001 --method interest --score 4
```

批次目录在当前账号的evaluations/下：dataset.json固定原文、版本、哈希、画像与评估日期；manifest校验快照及作用域；labels.csv用于盲标；review.md仅本地查看原文；report-all.json记录每条预测与解释。review将网页文字按代码块显示，避免把不可信图片/HTML渲染成远程请求。首次试采样发现按门户发布部门分层会过度抽到门户，保留该试批次，正式批次改按门户一层+七BYR版面分层，固定哈希排序轮转抽样。

本轮正式批次`20261016T103345-c617c612`含40条：BYR35、门户5；用户明确标注8条BYR真实历史，其中1条important、6条relevant、1条irrelevant。用户查看了标题并可选查看本地正文，**没有证据证明逐篇读完正文**，所以这是初步兴趣标签，不是资格、当前有效性或正文完整理解的金标准。其余32条未标注，不计算准确率。

抽样时预先固定calibration/test，已标8条各占4条；test恰好全是relevant，没有important或irrelevant，因此test重要召回率为null，不能用这组数据证明强制事项召回或全面降低无关率。全部8条的描述性统计只用于说明现状，不替代独立测试。

| 指标 | 原短语规则 | 主题+意图规则 |
|---|---:|---:|
| 8条中相关/重要信息识别覆盖 | 1/7 | 6/7 |
| 已标test相关信息覆盖 | 0/4 | 3/4 |
| 已标8条的重要提醒保留 | 1/1 | 1/1 |
| 已标8条中无关提醒占比 | 1/8 | 1/8 |
| 自动提取匹配证据覆盖 | 0/8 | 6/8 |
| 40条本地推理耗时（一次测量） | 约0.009秒 | 约0.016秒 |
| 外部API调用与计费 | 0 | 0 |

“相关/重要识别覆盖”只表示high或medium，不是所有提醒的召回：两种方法尚会把unknown汇总，因此无关提醒占比没有改善。缺失的相关项为一种未配置别名的会议组队信息；没有在看到test标签后修改规则并重报成绩。8条明确反馈在本地重放后，1条无关版本归档、1条手动重要标记即时、其余6条汇总；没有实际重发历史。单条负反馈能对已知版本归档，这是交互纠错能力，不可把同一标签用于纠错后再声称独立预测准确。

解释证据覆盖只是自动可核对的出处率，不等于解释质量。用户在同一真实重要样本上对旧解释给0分、新解释给4分，已原样记录；原问题提示1—5分，但用户主动给0分，因此评分接口扩展为0—5分，不默默抬高原分数。仅一项帮助评分不能概括解释整体质量。真人评分绑定方法与具体解释哈希，未评分项为null，不用模型自评代替。置信度也是启发值或模型自报，不是校准后的概率。

默认evaluate run只比较两种本地规则，将API标为未运行。显式`--method api`复用已有独立模型接口及隐私检查：无模型/地址报告not_configured，私有授权不足或失败记fallback_not_ai，不拿规则回退冒充AI成功；全批次仍有总预算，未完成项单独列出，不把它们丢出报告后宣称高准确率。未授权画像时AI后由本地规则覆盖相关性，这只能算混合方法；完整模型个性化比较需本人授权或本地模型。

本轮没有调用真实模型，没有索取密钥、没有发送门户正文或画像。实际token与云端费用未知时为null，不猜测；本地规则仅无API费用，不代表电脑运行零成本。

## 代码、回归与下一步

主要改动：profile新增Interest与relevant偏好；personalization实现证据匹配；feedback新增独立表；evaluation实现冻结、标注、指标、方法/解释评分；CLI新增recommend、feedback、evaluate。analysis的策略版本更新，旧缓存不复用；smart只增强相关性和显式反馈策略，原认证与数据基线保留。顺便修正ai --mode误写portal.auth_mode的CLI分支。

完整回归**136项通过**，原123项测试保留，新增主题意图、词边界、冲突、画像/正文版本反馈隔离、事务保护、评估不改投递、缺标签null、快照篡改、私人API阻止、解释评分隔离及不可信Markdown显示。完整结果与运行证据见[personalization-validation.json](personalization-validation.json)。

下一步先盲标更多真实样本，尤其补齐test中的重要和无关项；连续记录一至两周“确实值得看/不值得看”及解释帮助评分。之后在同一冻结集联调本人允许的本地或云端模型，并与规则比较召回、无关率、解释评分、失败率和实际token费用。没有这些证据前，不宣称AI优于规则，也不自动扩大过滤范围。

本轮真实完整扫描门户20条（2条新、18条未变），BYR70篇（3条新、2条修改、65条未变），两源无错误，10条待处理消息完成本地分析并通过原Windows通道提交；显示/阅读未另行确认，不将submitted当received。随后真实计划任务小样本两源no_new、退出0，完整配置已恢复，见[计划任务复测](personalization-scheduler-validation.json)。库完整性ok，重新在线备份，健康状态healthy。此前异常任务记录仍保留interrupted。
