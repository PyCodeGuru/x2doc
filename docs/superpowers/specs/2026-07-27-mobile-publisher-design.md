# x2doc 手机端安全发布设计

## 目标

你在 iPhone 的 KittyLitter Codex 对话中发送一个 X 或微信公众号链接，并明确要求“转换为 Markdown/PDF 并上传 GitHub”后，Mac mini 自动调用本地 x2doc，将本次输出单独提交并推送到 `PyCodeGuru/x2doc` 的 `main`，最后返回文件路径、GitHub URL 与提交哈希。

## 边界

- KittyLitter 只承担 Codex 消息通道，不修改 daemon、SSH、LaunchAgent 或保活脚本。
- 一次请求只接受一个 x2doc 支持的 URL，不接受额外 shell 参数。
- 一次请求只授权提交该 URL 新生成的 `output/<platform>/<document>/`。
- 不提交调用者当前工作区的暂存项、未提交代码或其他输出。
- GitHub 身份必须是 `PyCodeGuru`，远端必须是 `https://github.com/PyCodeGuru/x2doc.git`。
- 不在技能或脚本中保存 GitHub token、cookies 或代理密码。

## 架构

### Codex 个人技能

个人技能安装到 `~/.codex/skills/x2doc-publisher/`。其触发语义覆盖“把 X/微信公众号链接转成 Markdown、PDF 并上传/推送 GitHub”。技能只能调用仓库内固定脚本：

```text
/Users/paipai_tm/Work/tools/x2doc/scripts/x2doc-publish.sh URL
```

技能不得临时拼接 `git add .`、`git commit -a`、任意代理或另一套抓取工具。脚本失败时，技能返回失败阶段和修复建议，不宣称已上传。

### 隔离发布脚本

入口脚本位于 `scripts/x2doc-publish.sh`。核心逻辑由 `scripts/x2doc_publish.py` 实现，便于单元测试和可靠处理路径、子进程输出与 Git 状态。

发布器使用持久 worktree：

```text
/Users/paipai_tm/Work/tools/x2doc-publisher-worktree
```

该 worktree 从 `origin/main` 创建，使用自己的 `.venv`，生成文件和提交都发生在其中。日常开发目录只提供入口脚本，不参与暂存和提交。

## 数据流

1. 校验 URL，只允许 x2doc 已支持的平台。
2. 获取独占锁，防止两个手机请求同时发布。
3. 检查 M78；若 `127.0.0.1:7892` 可连接，则本次显式使用 `http://127.0.0.1:7892`，否则沿用合法环境代理或直连。
4. 校验 `gh api user` 为 `PyCodeGuru`，校验源仓库远端。
5. `git fetch origin main`，将发布 worktree 快进到 `origin/main`；若存在未推送提交、脏文件或分叉则停止。
6. 确保发布 worktree `.venv` 可导入 x2doc 且 Chromium 已安装；缺失时执行用户态安装。
7. 运行 `x2doc URL --format md,pdf --images local --overwrite --no-thread --out output`。
8. 从结构化运行结果获得输出目录，验证 `index.md`、`index.pdf` 和所有本地图片引用存在。
9. 仅执行 `git add -- <本次输出目录>`；若暂存区出现该目录外路径则停止。
10. 有变化时创建提交；无变化时复用当前提交。随后执行 `git push origin HEAD:main`。
11. 输出单行 JSON，包含状态、Markdown/PDF 路径、GitHub URL、提交哈希和是否产生新提交，供 Codex 稳定转述。

## 错误处理

- 参数或 URL 错误：退出码 1。
- 内容不可访问：保留 x2doc 退出码 2。
- 代理、X 或 GitHub 网络失败：退出码 3。
- Python、Chromium、字体、Git/gh 缺失：退出码 4。
- 转换、Git 边界或发布失败：退出码 5。
- 任一失败都输出明确阶段；没有成功 push 就不输出成功 GitHub URL。

## 测试

- 单元测试注入命令执行器、端口探针和文件系统临时目录。
- 覆盖 URL 校验、账号/远端校验、隔离暂存、无变化、并发锁、push 失败和 JSON 输出。
- shell 入口用假发布器做参数透传测试。
- 技能先做无技能基线压力测试，再用同一手机式提示做前向测试。
- 最终用用户给出的真实链接完成一次 Markdown/PDF/图片生成和 PyCodeGuru push，并核对 GitHub 文件。

## 非目标

- 不新增后台服务、消息队列、GitHub Action 或自托管 Runner。
- 不修改 KittyLitter、SSH、M78 或 macOS 系统级配置。
- 不支持一条消息批量发布多个链接。
- 不自动处理需要登录 cookies 的受保护内容。
