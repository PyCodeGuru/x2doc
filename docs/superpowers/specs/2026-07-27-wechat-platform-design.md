# x2doc 双平台设计

## 目标与边界

x2doc 在保持现有 X 输出内容和抓取行为不回退的前提下，支持公开微信公众号文章。CLI 仍接受单个链接，平台识别、缓存、抓取、解析、媒体本地化和输出路径由平台适配器驱动。首版不处理需账号登录的微信私域内容，也不下载音视频正文。

## 方案比较与选择

1. 在现有流程中增加平台条件分支：改动少，但 X 假设继续泄漏，长期难维护。
2. 内置平台注册表：每个平台提供 URL 规范化、fetcher、parser、目录策略；核心只处理统一目标和文档。选择此方案，隔离清晰且复杂度适中。
3. Python entry-point 插件：扩展性最高，但两个内置平台不值得引入安装发现和版本兼容成本。

## 核心模型与注册表

`CanonicalTarget` 包含 `platform`、`route`、`source_id`、`canonical_url`、可用抓取路径和平台元数据。`PlatformAdapter` 注册 `match`、`normalize`、fetcher 工厂、`raw_kind` parser 映射和输出目录策略。平台注册顺序固定为 X、Wechat；不匹配时错误列出两种支持格式。

`Document.platform` 使用 `Platform` 枚举；微信文档可选 `original_link`。front matter 在 `source_url` 前增加 `platform`，除该字段外 X front matter 顺序不变。

## 数据流

CLI → `resolve_target` → 平台适配器 → v2 缓存 → 平台抓取链 → 平台 parser → `Document` → 通用媒体本地化 → Markdown/PDF。X 的 fetcher/parser 不改语义，只通过 X 适配器接入。

微信支持 `/s/<token>` 和 `/s?...` 两类 URL，移除追踪参数。抓取按 cache、static、playwright，微信域名默认直连。HTML parser 递归清洗脏 DOM，生成现有块模型；音视频用新的占位块保留链接和封面。

## 缓存与输出

v2 缓存路径为 `<cache>/<platform>/<source_id>.json`，envelope 增加 `platform`。读取 X v2 miss 时查找 v1 `<route>-<source_id>.json`，只使用本地 raw 重解析，原子写入 v2，并在旧文件旁写 `.migrated-v2` 标记，旧文件不删除。

输出固定为 `output/x/...` 和 `output/wechat/...`。迁移脚本默认 dry-run，`--apply` 才移动旧的 X 目录，目标冲突跳过。

## 网络与错误

`NetworkPolicy` 根据目标域名决定代理或直连。默认直连 `mp.weixin.qq.com`、`mmbiz.qpic.cn`、`res.wx.qq.com`；`--no-proxy-domains` 可重复且支持逗号分隔。微信删除、违规、参数错误映射退出码 2；验证/环境异常映射退出码 3。日志只显示脱敏代理或“直连”。

## 测试与验收

严格按 RED→GREEN：先覆盖平台注册、缓存迁移、代理选择和路径；再覆盖微信 URL、错误页、普通/技术 DOM、图片 Referer 与扩展名；最后覆盖 doctor 和 CLI。既有 X golden 不改正文，仅增加 platform front matter。三阶段分别提交，最后运行完整 pytest、Ruff、真实微信/X 转换、PDF 文本提取和离线缓存重渲染。
