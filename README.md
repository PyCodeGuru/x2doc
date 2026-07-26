# x2doc

`x2doc` 将 X（Twitter）链接转换为结构化 Markdown，并在后续阶段支持 PDF。

当前正在实施阶段一垂直切片：公开单条推文经 Syndication 抓取、统一模型解析、缓存后输出 Markdown。详细设计与实施计划位于 `docs/superpowers/`。

## 开发环境

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

完整安装、CLI、缓存、fixture/golden 更新和已知限制会随阶段一交付同步补齐。
