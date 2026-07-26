# x2doc 设计规格

## 1. 目标与边界

`x2doc` 是面向 macOS、Python 3.11+ 的本地命令行工具，将 X（Twitter）单条推文、Article 和 thread 转换为结构化 GitHub Flavored Markdown，并可进一步输出 PDF。工具不依赖付费 X API，优先使用免登录公开数据源，在必须登录时支持导入 cookies。

首个交付切片严格限定为“单条推文 URL → Syndication → `Document` → Markdown”。该切片通过示例输出评审后，再依次扩展 Article、thread 和 PDF。WeasyPrint 仅作为可选 extra，不属于默认安装或验收范围。

## 2. 核心判据

- 可靠性优先：公开数据源失败时按明确路径降级，错误可诊断。
- 简单优先：抓取、解析、模型、媒体和渲染分层，各模块只承担一个职责。
- 离线优先：已缓存内容可在断网时重解析和重新渲染。
- 结构保真：标题、列表、引用、代码、链接、图片与表格通过统一块模型表达，不直接暴力转换 HTML。
- 可演进：X 接口或 DOM 改动由 fetcher/parser 契约测试尽早发现。

## 3. URL 路由与抓取链

入口首先调用 `resolve_route(url)`，校验域名并将链接分类为 `tweet` 或 `article`：

- `x.com/<user>/status/<id>` 与兼容 Twitter 域名归为 `tweet`。
- `x.com/i/article/<id>` 归为 `article`。
- 非 X/Twitter 域名或无法识别的路径立即返回中文错误，并以非零状态退出。

Article 直接进入 Playwright，不尝试 Syndication、FxTwitter 或 VxTwitter。Tweet 在无有效缓存时依次尝试 Syndication、FxTwitter、VxTwitter、Playwright；每次尝试记录结构化失败原因，成功后明确记录实际使用路径。

核心调度、缓存、解析和渲染采用同步调用。只有媒体下载和 thread 抓取使用 `asyncio`，共享并发上限 5，避免让 CLI 和 Python API 暴露异步语义。

## 4. 统一数据模型

Pydantic 模型包含 `Document`、`Author`、`Media` 和判别联合 `Block`。`Document` 保存来源、作者、标题、上海时区发布时间、原始 UTC 时间、语言、正文块、媒体、指标、thread、原始响应以及抓取路径。

块类型覆盖段落、标题、无序列表、有序列表、引用、代码、图片、视频封面、表格、分隔线、链接卡片、mention 和 hashtag。渲染器只消费模型，不依赖任何 fetcher 的原始字段。

JSON 解析器根据 `entities.urls[].expanded_url` 展开短链；仍未展开的 `t.co` 链接在联网时执行受限的重定向解析，离线时保留原链接并发出告警。DOM 解析器按块级元素建立模型，保留代码缩进和媒体在正文中的位置。

Syndication 的 `full_text` 不包含可靠的富文本块信息，因此由独立的 `parsers/plaintext_blocks.py` 执行有损启发式解析。规则按优先级固定为：三反引号或三波浪线围栏及其内部内容转为代码块；独占一行的 `---` 转为分隔线；以 `•`、`- ` 或 `* ` 开头的连续行转为无序列表；以 `1.`、`2.` 等数字加句点开头的连续行转为有序列表；仅由 `**文本**` 构成的独行转为二级标题；其余连续非空行转为段落，空行结束当前块。该解析无法还原 X 未提供的原始语义，必须在代码注释和 README 中标注为“有损启发式”，规则通过输入文本到块模型的快照测试固定。

标题推导规则固定如下：Article 优先使用 DOM 提供的标题；Tweet 对展开链接并移除零宽字符后的 `full_text`，取第一个非空逻辑行，去掉纯媒体短链，折叠普通空白，再截取第一个 `。`、`！`、`？`、`.`、`!` 或 `?` 及其前文；若 80 个 Unicode 字符内没有句末标点则截断到 80 字符；结果为空时回退为 `tweet-<id>`。标题推导不修改正文。

## 5. 缓存设计

缓存文件位于 `~/.cache/x2doc/<route>-<source-id>.json`，缓存 key 必须包含 route，避免 tweet 与 article 标识碰撞。顶层结构固定为：

```json
{
  "schema_version": 1,
  "route": "tweet",
  "fetch_path": "syndication",
  "raw_kind": "syndication_tweet",
  "fetched_at": "2026-07-26T00:00:00Z",
  "raw": {},
  "document": {}
}
```

版本匹配时直接读取 `document`。版本不匹配但 `raw` 可用时，根据显式维护的 `raw_kind → parser` 映射表选择当前 parser，重建 `document` 并原子更新缓存，不发起网络请求。首批映射为 `syndication_tweet → parse_syndication_tweet`、`fxtwitter_tweet → parse_mirror_tweet`、`vxtwitter_tweet → parse_mirror_tweet`、`playwright_tweet_dom → parse_tweet_dom`、`playwright_article_dom → parse_article_dom`。未知 `raw_kind` 视为缓存不可解析。只有缓存不存在、损坏、缺少可解析的 `raw`，或显式指定 `--refresh` 时才联网；`--refresh` 的行为在 README 中明确说明。

缓存写入使用临时文件加原子替换，避免中断留下半文件。缓存损坏时保留原文件并给出可理解的告警，不静默吞掉问题。

## 6. Thread 行为

默认 `auto` 模式在检测到同作者自回复关系后尝试补全 thread；`--thread` 强制尝试，`--no-thread` 禁止补全。thread 请求使用 `asyncio` 并发执行，最多 5 个在途请求，最终按发布时间和回复关系稳定排序。

免登录模式若只能取得单条且无法确认 thread 完整性，CLI 必须显式提示：“当前仅获取到单条推文；如需补全 thread，请提供 `--cookies PATH`。”该提示不是静默 debug 日志，在默认日志级别可见。Python API 将同等信息放入结果警告集合。

免登录模式只承诺根据 `in_reply_to_status_id_str` 向上回溯同作者父链，不能枚举未知的后续回复。向下补全仅在 Playwright 已加载有效 cookies 时实现；即使指定 `--thread`，无 cookies 时也必须遵守该边界并显示上述提示。

## 7. 媒体处理

媒体下载器使用 `asyncio`，并发上限 5。`local` 模式按内容哈希去重并保存为 `assets/NNN-<hash8>.<ext>`；`embed` 生成 data URI；`none` 保留远程 URL。下载失败时 Markdown 回退到原始 URL，并输出告警。

扩展名优先根据响应 `Content-Type` 判断，URL 后缀只作回退。文件写入采用临时文件和原子替换，避免产生不完整图片。

## 8. Markdown 与 PDF

Markdown 渲染输出 UTF-8、LF、YAML front matter、thread 分隔标记和来源区块。中文清理只移除零宽字符并压缩多余空行，不强制插入中英文空格，不修改代码块内容。图片缺少说明时按出现顺序生成“图 N”。

PDF 默认使用 markdown-it-py 生成 HTML，再由 Playwright Chromium 输出 A4 PDF。渲染前检测可用中文字体；未找到时停止并提供明确安装建议。图片转换为绝对 `file://` URL，CSS 控制分页、代码溢出、引用样式、页眉标题和页脚页码。

`weasyprint` 不进入默认依赖，配置为 `pdf-weasyprint` optional extra；它是兼容性备选，不纳入核心验收标准。

`--images none` 与任何包含 `pdf` 的输出格式互斥，因为 PDF 的离线渲染不能依赖未本地化的远程资源。该组合在网络或抓取开始前作为参数错误拒绝，退出码为 1，并提示改用 `local`/`embed` 或仅输出 Markdown。

## 9. CLI 与 Python API

CLI 保持附件定义的选项，并补齐 `--refresh`、`--thread-marker/--no-thread-marker`。`--format` 接受 `md`、`pdf`、`md,pdf` 和 `all`，解析后去重并验证。默认输出目录为 `./output`，默认图片模式为 `local`。

输出目录固定为 `<out>/<handle>-<YYYYMMDD>-<slug>/`。日期取 `published_at` 的 Asia/Shanghai 日历日期；handle 去掉前导 `@` 并进行安全字符清理；slug 使用 `slugify(title, allow_unicode=True, max_length=40)`，结果为空时回退 `tweet-<id>`。目录已存在且未指定 `--overwrite` 时，在写入任何文件前报错并以退出码 1 结束；`--overwrite` 只替换该次生成的已知文件，不删除目录中的无关文件。

同步 Python API 为：

```python
from x2doc import convert

result = convert(url, formats=["md", "pdf"])
```

API 返回包含输出路径、警告和所用抓取路径的结果对象；可预期错误使用自定义异常层次，CLI 将其翻译为中文提示和非零退出码。

## 10. 错误与安全边界

系统区分非法 URL、内容删除、账号受保护、需要登录、限流、网络不可达、浏览器缺失、中文字体缺失和媒体下载失败。Cookie 日志只显示文件路径和加载数量，绝不输出 `auth_token`、`ct0` 或完整 Cookie 内容。

网络请求采用固定 User-Agent、20 秒超时、最多 3 次指数退避。HTTP 429 尊重 `Retry-After`，不无限重试。重定向解析限制协议为 HTTP/HTTPS，并限制跳转次数。

CLI 退出码固定为：`1` 参数或输出冲突（非法 URL、非法选项、目录已存在）；`2` 内容不可访问（删除、受保护、需要登录或权限不足）；`3` 网络错误（超时、DNS、代理、限流重试耗尽）；`4` 本地依赖缺失（Playwright/Chromium、可选引擎、中文字体）；`5` 解析或渲染失败。成功固定为 `0`。所有自定义异常必须映射到其中之一，未知内部异常归入 5，并在 `--verbose` 下显示诊断上下文。

## 11. 测试策略

解析和渲染层严格采用 TDD：先写失败测试并确认失败原因，再实现最小代码。三个离线 fixture 覆盖普通推文、四图推文和 Article HTML，断言统一模型和 Markdown 结构。

Fetcher 使用契约测试，验证请求构造、响应分类、降级语义和统一返回结构；默认测试不访问真实网络。`-m network` 的 smoke test 独立存在且默认跳过。

项目提供 fixture 刷新脚本，显式接收 URL 和输出路径，默认拒绝覆盖，要求用户主动提供 `--overwrite`。脚本输出前清理 cookies、token 和不稳定追踪字段，防止凭据进入仓库。Golden Markdown 快照通过独立脚本或 `pytest --update-golden` 显式更新；默认测试永不自动改写 golden 文件，更新命令、差异审阅步骤和提交要求写入 README。

## 12. 分阶段实施与验收

阶段一的第一步是对一条公开、含单图的普通短推文真实请求一次 Syndication，将响应脱敏并落为 fixture；随后冻结 parser 实际使用的字段及契约。阶段一实现单条推文垂直切片：URL 校验与路由、Syndication fetcher、纯文本块启发式 parser、Tweet JSON parser、`Document` 模型、缓存、输出目录、Markdown 渲染、CLI/API 最短路径。完成后展示该单图短推文生成的 `index.md`，等待评审。

阶段二实现 FxTwitter/VxTwitter 补齐、Playwright Article、DOM parser、cookies 和 thread。阶段三实现媒体本地化、HTML/PDF、字体检查、可选 WeasyPrint 和完整文档。

原附件中的长文样本以及 6 条验收标准整体归入阶段三终验，不阻塞阶段一或阶段二评审。每阶段运行对应 pytest 与 Ruff；阶段三最终执行可编辑安装、离线缓存重渲染、非法 URL 非零退出、长文 Markdown 结构和 Playwright PDF 回归。真实 X 内容可能随时间变化，因此对验收示例同时保留 fixture 快照和一次可选网络验证。

## 13. 已知限制

- 受保护账号仍要求有效且有权限的 cookies，工具不能绕过访问控制。
- 视频仅保存可用封面和原始链接，不保证下载视频正文。
- 投票和第三方嵌入可能降级为链接卡片。
- X 的公开接口与 DOM 会变化，契约或快照测试失败时需要更新对应适配器。
- 无登录公开数据源通常不能可靠枚举全部回复，因此 thread 完整性依赖可用元数据或 cookies。
