# 信息门户：手动导出与服务器导入

信息门户 `my.bupt.edu.cn` 只解析到校园内网地址，云服务器没有到该网段的路由，
CAS 回调也无法完成。因此本项目不提供服务端门户采集，而是：

```
校网内的个人电脑                          服务器
┌──────────────────────┐   scp    ┌──────────────────────────┐
│ tools/portal_export.py│ ───────► │ run.py portal import      │
│ 人工登录 → 抓列表/正文 │  bundle  │ 校验 → 入库 → 分类/展示    │
└──────────────────────┘          └──────────────────────────┘
```

服务器只做「校验 + 入库」，不需要门户账号、不需要校园网。

## Bundle 格式（`bupt-portal-bundle` v1）

单个 JSON 文件（可选 `.json.gz`），UTF-8：

```json
{
  "format": "bupt-portal-bundle",
  "version": 1,
  "bundle_id": "<items 的 sha256>",
  "generated_at": "2026-11-01T18:00:00+08:00",
  "client": {"tool": "portal-export/1.0", "portal": "http://my.bupt.edu.cn", "days": 90},
  "window": {"days": 90},
  "stats": {"items": 12, "ok": 10, "attachment_only": 1, "image_only": 1, "body_failed": 0, "errors": []},
  "items": [
    {
      "id": "portal:<sha1(canonical url)>",
      "title": "关于……的通知",
      "url": "http://my.bupt.edu.cn/...",
      "published": "2026-10-30 09:00",
      "department": "科学技术研究院",
      "list": "通知公告",
      "body": "正文纯文本",
      "body_status": "ok",
      "attachments": [{"name": "附件1.pdf", "url": "http://my.bupt.edu.cn/..."}],
      "fetched_at": "2026-11-01T17:59:00+08:00"
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `bundle_id` | 对 `{format,version,items}` 规范化 JSON 的 SHA-256；服务器重算，不一致即拒绝 |
| `items[].id` | 稳定标识，仅审计用；服务器仍按规范化 URL 去重 |
| `url` | 会去掉 `ticket`/`jsessionid`/`utm_*`，避免会话参数进入数据库 |
| `body_status` | `ok` / `attachment_only` / `image_only` / `body_failed` |
| `stats` | 供人查看，不参与校验 |

设计取舍：

- **单文件、可读 JSON**：便于人工核对，也便于 `scp` 与归档；gzip 仅用于体积。
- **幂等**：同一 `bundle_id` 重复上传直接返回 `already_imported`；同 URL 内容变化才会产生新版本。
- **不依赖客户端状态**：导出端不做“已上传”判断，服务器去重，避免两边不一致。
- **初筛在客户端**：`--days 90`、`--max 300` 控制窗口；服务器仍会按主题分类与推荐规则处理。

## 一条命令：导出 → 上传 → 导入

```bash
cp portal_client.example.yaml portal_client.yaml   # 校准列表/选择器，填写 server
python -X utf8 tools/portal_sync.py --save-credentials   # 一次，密码加密保存
python -X utf8 tools/portal_sync.py
```

脚本行为：

- 登录默认 `login.mode: http`：直接提交官方 CAS 表单，**不打开浏览器**。
  门户的可见登录表单在 iframe 里，自动化下常是空白（手动 Firefox/Edge 偶尔也会），
  HTTP 方式绕开该问题，也是原项目实际验证过的路径。
- 凭据二选一：`login.username/password` 写入 `portal_client.yaml`（文件已在
  `.gitignore` 中），或 `--save-credentials` 加密保存到
  `secrets/portal.enc`（密钥单独放 `secrets/portal.key`）。
- `login.mode: browser` 保留 Playwright + Edge 人工登录，作为备选。
- 默认读取仓库根目录的 `portal_client.yaml`，bundle 写到 `portal-out/`（相对路径）。
- 上传优先使用 paramiko（一次密码提示，也支持 SSH 密钥）；未安装时回退 `scp`/`ssh`。
- 常用参数：`--bundle FILE` 跳过导出直接上传；`--no-upload` 只导出；
  `--days/--max` 控制窗口；`--host/--user` 覆盖服务器地址。

只导出、不上传：

```bash
python -X utf8 tools/portal_sync.py --no-upload
```

## 手动上传（等价流程）

```bash
scp portal-*.json <server>:/var/lib/bupt-insight/portal-inbox/
```

服务器上：

```bash
cd /opt/bupt-insight/app
sudo -u bupt /opt/bupt-insight/venv/bin/python -X utf8 run.py portal import \
  /var/lib/bupt-insight/portal-inbox/portal-20261101-180000.json
```

- 成功后会移动到 `data/portal-inbox/imported/`；`--keep` 保留原文件。
- `--force` 忽略 `bundle_id` 去重（例如服务器库重建后）。
- `--push` 导入后立即运行分析与推送（默认不推送）。
- 导入会写一条 `source='portal'` 的 `sync_runs`，网页「信息来源」显示最近导入时间。

## 安全

- bundle 含门户私人正文：只经 `scp` 传输，服务器落盘 0600，不要提交 Git；
  `.gitignore` 已排除 `portal-*.json`、`portal_client.yaml`。
- 导入后文件默认移动到账号数据目录，仍属私人数据，备份策略与数据库一致。
- 服务器从不保存门户密码；本机也不保存（每次手动登录）。
