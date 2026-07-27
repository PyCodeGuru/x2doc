# x2doc

## 5 分钟上手

```bash
cd /Users/paipai_tm/Work/tools/x2doc && python3 -m venv .venv && .venv/bin/python -m pip install -e . && .venv/bin/python -m playwright install chromium
```

```bash
cd /Users/paipai_tm/Work/tools/x2doc && .venv/bin/x2doc doctor --proxy 'http://127.0.0.1:7892'
```

```bash
cd /Users/paipai_tm/Work/tools/x2doc && .venv/bin/x2doc 'https://x.com/ma_zhenyuan/status/2081364662818599028' --proxy 'http://127.0.0.1:7892' --format md,pdf --images local --overwrite
```

完整说明见 [docs/使用指南.md](docs/使用指南.md)。

`x2doc` 是一个本地 CLI/Python 库，用于把 X（Twitter）推文和 Article 转换为结构化 Markdown 与 A4 PDF。

公开推文默认按 `cache,syndication,fxtwitter,vxtwitter,playwright` 降级；Article URL 直接进入 Playwright。抓取结果统一归一化为 `Document`，再输出 Markdown、HTML 中间表示与 PDF。

## 1. 安装

要求 Python 3.11+。推荐使用项目虚拟环境，避免污染系统 Python：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
```

开发与测试：

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

PDF 与 Article 使用 Playwright Chromium，首次安装后执行：

```bash
.venv/bin/playwright install chromium
```

WeasyPrint 不属于默认依赖。阶段三如需备选引擎再安装：

```bash
.venv/bin/python -m pip install -e '.[pdf-weasyprint]'
```

## 2. 首次使用

```bash
x2doc 'https://x.com/apimctestface/status/1253775785153884161' \
  --format md \
  --images local
```

主要选项：

```text
--format md|pdf|md,pdf|all
--out DIR                      默认 ./output
--images local|embed|none      默认 local
--front-matter/--no-front-matter
--refresh                      忽略缓存并重新抓取
--overwrite                    允许覆盖本次生成的已知文件
--lang zh|en                   默认 zh
--verbose                      显示诊断上下文
--proxy URL                    HTTP/HTTPS/SOCKS5 代理
--fetch-order PATHS            默认 cache,syndication,fxtwitter,vxtwitter,playwright
--cookies PATH                 JSON 或 Netscape cookies 文件
```

`--images none` 与包含 PDF 的格式始终互斥，并在联网前以退出码 1 拒绝。

## 3. Python API

API 保持同步；只有媒体下载内部使用 `asyncio`，并发上限为 5：

```python
from x2doc import convert

result = convert(
    "https://x.com/apimctestface/status/1253775785153884161",
    formats=["md", "pdf"],
)
print(result.outputs["md"])
print(result.fetch_path)
```

## 4. 输出目录

目录规则固定为：

```text
output/{handle}-{YYYYMMDD}-{slug}/
├── index.md
├── index.pdf
└── assets/
```

- 日期取推文发布时间的 Asia/Shanghai 日历日期。
- slug 使用 `slugify(title, allow_unicode=True, max_length=40)`。
- slug 为空时回退为 `tweet-{id}`。
- 目录已存在且没有 `--overwrite` 时，命令以退出码 1 结束。
- `--overwrite` 只替换本次生成的已知文件，不删除目录中的其它文件。

## 5. 标题与纯文本块推导

Syndication 只提供 `text/full_text`，没有可靠的原始富文本结构。`parsers/plaintext_blocks.py` 因此采用有损启发式，不能证明推导结果等同于作者原始排版：

- ` ``` ` 或 `~~~` 围栏转为代码块，保留内部缩进；未闭合围栏持续到 EOF。
- 独占一行的 `---` 转为分隔线。
- 连续 `•`、`- `、`* ` 行转为无序列表。
- 连续 `1.`、`2.` 等行转为有序列表。
- 仅由 `**文本**` 构成的独行转为二级标题。
- 其它连续非空行转为段落，空行结束当前块。

这些规则由 `tests/fixtures/plaintext/blocks.json` 快照固定。代码块之外会移除零宽字符；不会强制插入中英文空格。

Tweet 标题规则固定为：展开链接并移除零宽字符后，取第一个非空逻辑行，去掉纯媒体短链；优先截到首个中英文句末标点，否则截到 80 个 Unicode 字符；标题末尾的中英文标点会被移除。标题为空时使用 `tweet-{id}`；标题是纯符号或纯 emoji 时保留标题，但 slug 为空，因此输出目录回退为 `tweet-{id}`。

Markdown front matter 固定包含 `schema_version`、`title`、`author`、`handle`、`source_url`、`published_at`、`published_at_utc`、`fetched_at`、`fetch_path`、`lang`、图片/thread 数量与 `tags`。`metrics` 保留在 `Document` 中，但不写入 front matter。`published_at` 与 `fetched_at` 统一使用 Asia/Shanghai，`published_at_utc` 单独保留 UTC。

来源区块使用专用锚点与两条独立引用行，不依赖 Markdown 行尾双空格，也不与正文 divider 混淆：

```markdown
<!-- x2doc:source -->

> 原文链接：[查看原文](https://x.com/...)
> 抓取时间：2026-07-27T08:30:00+08:00
```

## 6. 缓存与离线重解析

默认缓存位于：

```text
~/.cache/x2doc/{route}-{source-id}.json
```

顶层结构固定为：

```json
{
  "schema_version": 1,
  "route": "tweet",
  "fetch_path": "syndication",
  "raw_kind": "syndication_tweet",
  "fetched_at": "2026-07-26T12:30:00Z",
  "raw": {},
  "document": {}
}
```

- 版本匹配：直接读取 `document`，不联网。
- 版本不匹配且 `raw_kind` 已注册：使用当前 parser 重建 `document`，不联网。
- 缓存损坏或 `raw_kind` 未知：保留原文件供诊断，再视为 cache miss。
- `--refresh`：明确跳过缓存并重新联网抓取。
- 缓存和输出均使用临时文件 + 原子替换，降低中断造成半文件的风险。

## 7. Fixture 与 Golden 更新

默认测试不访问网络，网络 smoke test 被 `network` marker 排除。

显式通过代理刷新 Syndication fixture（同时记录来源 URL、UTC 抓取时间和响应 SHA-256）：

```bash
.venv/bin/python scripts/refresh_fixtures.py \
  'https://x.com/apimctestface/status/1253775785153884161' \
  tests/fixtures/syndication/single_image.json \
  --proxy 'http://127.0.0.1:7892' \
  --overwrite
```

脚本只保留 parser 字段白名单，不写 Cookie、token、请求头或跟踪字段。刷新后先审阅 JSON diff，再更新 golden：

```bash
.venv/bin/python scripts/update_golden.py \
  tests/fixtures/syndication/single_image.json \
  tests/fixtures/syndication/single_image.meta.json \
  tests/golden/single_image.md \
  --overwrite

git diff -- tests/fixtures tests/golden
.venv/bin/python -m pytest tests/test_tweet_json.py tests/test_markdown.py -q
```

中文长文本结构样本位于：

```text
tests/fixtures/syndication/chinese_long_text.json
tests/golden/chinese_long_text.md
```

Golden 的 `fetched_at` 来自 `.meta.json` 的 `golden_fetched_at`；真实转换默认取 fetcher 成功时的真实时钟。Python API 测试可通过 `clock=lambda: fixed_datetime` 注入固定时间，渲染器本身不读取或硬编码当前时间。

两个脚本默认拒绝覆盖，必须显式传入 `--overwrite`。fixture 刷新只写 parser 字段白名单；Cookie、token、请求头和跟踪字段不会入库。

如需主动运行网络 smoke test：

```bash
.venv/bin/python -m pytest -m network tests/test_network_smoke.py -q
```

## 8. 退出码

| 退出码 | 含义 | 典型情况 |
|---:|---|---|
| 0 | 成功 | Markdown 已生成 |
| 1 | 参数或输出冲突 | 非 X URL、非法选项、目录已存在 |
| 2 | 内容不可访问 | 删除、受保护、需要登录 |
| 3 | 网络错误 | 超时、DNS、限流重试耗尽 |
| 4 | 本地依赖缺失 | Chromium 或中文字体缺失 |
| 5 | 解析或渲染失败 | 上游字段变化、无法生成文档 |

## 9. Cookie 说明

支持 Cookie-Editor 等扩展导出的 JSON，以及 Netscape cookies.txt；只注入 X 所需的 `auth_token` 与 `ct0`。日志只输出文件路径与加载条目数，不输出值。不要把 Cookie 文件提交到仓库；受保护账号仍要求当前登录账号具备访问权限。

Chrome 导出步骤：登录 `x.com` → 安装并打开 Cookie-Editor → Export → 选择 JSON（或 Netscape）→ 保存到仓库外的私有路径，然后传入：

```bash
x2doc 'https://x.com/i/article/ARTICLE_ID' --cookies /secure/path/x-cookies.json
```

## 10. 已知限制

- Article 直接路由到 Playwright；X 若向免登录浏览器返回登录壳，会以退出码 2 提示提供 cookies，不会把壳页面伪装成正文。
- 免登录 thread 只承诺向上回溯父链；向下补全仅允许在 Playwright + cookies 下进行。
- 免登录只取得单条时，CLI 会显式提示使用 `--cookies PATH`。
- PDF 使用 Chromium，渲染前检测 PingFang SC / Noto Sans CJK SC / Source Han Sans SC；WeasyPrint 仍仅为 optional extra。
- 视频正文、投票和第三方嵌入尚未处理；未来可能降级为封面或链接。
- X 公开接口字段与页面 DOM 会变化；解析快照和 fetcher 契约测试用于尽早暴露变化。

## 11. 分阶段验收

- 阶段一：含单图普通短推文 → Syndication → Document → Markdown。
- 阶段二：镜像补齐、Playwright Article、cookies、thread。
- 阶段三：媒体完整化、HTML/PDF、长文样本和原规格 6 条最终验收标准。

## 12. 受限网络下配置代理

`x2doc` 把代理作为全局网络配置，Syndication、后续镜像 fetcher、Playwright 和图片下载共用同一选择结果。优先级固定为：

```text
--proxy > X2DOC_PROXY > HTTPS_PROXY > ALL_PROXY > 直连
```

支持 `http://`、`https://`、`socks5://`，也支持带认证信息的 `user:pass@host:port`。命令行示例：

```bash
x2doc 'https://x.com/apimctestface/status/1253775785153884161' \
  --proxy 'http://127.0.0.1:7892' \
  --format md \
  --images local
```

长期使用建议设置工具专属变量，避免影响同一终端中的其它程序：

```bash
export X2DOC_PROXY='socks5://127.0.0.1:7892'
x2doc 'https://x.com/apimctestface/status/1253775785153884161'
```

认证代理示例（密码中的 `@`、`:` 等特殊字符需进行 URL 百分号编码）：

```bash
x2doc 'https://x.com/user/status/1' \
  --proxy 'http://user:p%40ss@proxy.example.com:8080'
```

日志只显示脱敏后的 `scheme://host:port`，不会打印用户名和密码。不要把含凭据的命令写入共享 Shell 历史、脚本或仓库；更推荐把它放入权限受控的环境配置中。

常见问题：

- 本地加速器的“mixed”端口通常同时接受 HTTP 与 SOCKS5，但应以客户端配置为准。
- `127.0.0.1` 只对当前机器有效；容器或远程主机不能直接复用宿主机环回地址。
- 设置了系统代理不等于 Playwright 自动继承。x2doc 会解析上述优先级，并在浏览器启动时显式传入代理。

## 13. 网络连通性探针

探针把直连和指定代理并列测量，不修改 x2doc 抓取降级链，也不会重试掩盖失败：

```bash
.venv/bin/python scripts/probe_network.py \
  --proxy 'http://127.0.0.1:7892' \
  --timeout 8
```

输出使用真实资源路径，记录 DNS、TCP、TLS、HTTP 状态、响应字节、JSON 顶层键和耗时。最后还会让已安装的 Playwright Chromium 分别直连、显式走代理访问 `https://x.com/robots.txt`。

设计规格与阶段一实施计划：

- `docs/superpowers/specs/2026-07-26-x2doc-design.md`
- `docs/superpowers/plans/2026-07-26-x2doc-stage1.md`
