---
name: claude-code-session-extract
description: |
  Use when a user provides a Claude Code session ID or session JSONL file and needs
  to understand and continue that work. Also triggered by phrases like
  "恢复上下文", "接手这个 Claude Code 会话", "之前做到哪了",
  "从 Claude Code 记录恢复", "交接", "handoff".
  NOT when the session is from Codex (use codex-rollout-extract instead).
  NOT when the current conversation already has sufficient context.
---

# Claude Code Session Extract

## 概述

**核心能力**：从 Claude Code 的会话 JSONL 文件中提取上下文，生成结构化的交接报告。

### 与 Codex 的关键差异

| 维度 | Codex | Claude Code |
|------|-------|-------------|
| **核心恢复入口** | `task_complete`（Agent 自生成结构化报告） | **无此机制**，需要逆推 |
| **文件变更追踪** | 无原生支持 | `file-history-snapshot`（消息级快照） |
| **会话元信息** | `session_meta`（第一行） | 首条 `user` 消息的 metadata |
| **存储位置** | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | `~/.claude/projects/<project-dir>/<session-id>.jsonl` |
| **消息格式** | 事件类型驱动（`event_msg`） | 角色驱动（`user`/`assistant`/`system`） |

**核心挑战**：Claude Code 没有 `task_complete`，所以恢复上下文需要从文件变更链、工具使用模式和 agent 文本输出**逆推**工作摘要。准确性比 Codex 稍低，但 `file-history-snapshot` 提供了精确的文件变更追踪。

---

## 跨平台注意事项

| 问题 | 解决方案 |
|------|----------|
| Python 可执行名 | Windows: `python`，macOS/Linux: `python3`。优先 `python`，失败后 `python3` |
| 路径格式 | Python 脚本内用 `os.path.expanduser()` + `os.path.join()`，不在 Python 中硬编码 Windows/Git Bash 路径 |
| 编码 | 统一 `encoding='utf-8'` |

---

## Claude Code JSONL 结构

### 存储位置

```
~/.claude/projects/<project-dir>/<session-id>.jsonl
```

`<project-dir>` 是项目路径的编码形式（如 `home-user-project-name`，盘符和路径分隔符替换为 `-`）。

### 消息类型

| 类型 | 数量级 | 用途 |
|------|--------|------|
| `user` | ~100 | 用户输入（含 skill 调用、工具结果、排队操作） |
| `assistant` | ~150 | Agent 输出（文本 + 工具调用） |
| `system` | ~20 | 系统事件（local_command、api_error、turn_duration） |
| `file-history-snapshot` | ~10-15 | **文件变更快照**（每条消息对应的修改文件列表） |
| `queue-operation` | ~5-15 | 用户排队输入（Agent 正忙时用户追加的指令） |
| `custom-title` | ~3 | 会话标题 |
| `agent-name` | ~3 | Agent 名称 |

### 每条消息的公共字段

```json
{
  "uuid": "消息唯一 ID",
  "parentUuid": "父消息 ID（构成消息链）",
  "type": "user / assistant / system / ...",
  "timestamp": "ISO 时间戳",
  "sessionId": "会话 ID",
  "cwd": "工作目录",
  "gitBranch": "Git 分支",
  "version": "Claude Code 版本",
  "isSidechain": false,
  "forkedFrom": null
}
```

---

## 工作流程

```
① 定位文件 → ② 单次提取 → ③ 核对仓库状态 → ④ 合成报告
```

---

### ① 定位文件

用户可能提供：
- **Session ID**（如 `574f206c-700c-477a-84fa-46d05606c37d`）→ 用脚本 `--session` 自动定位
- **文件路径**（如 `~/.claude/projects/.../xxx.jsonl`）→ 直接传给脚本

```bash
# 按 session ID 自动定位
python scripts/claude_session_extract.py --session 574f206c-700c-477a-84fa-46d05606c37d

# 直接指定文件
python scripts/claude_session_extract.py /path/to/session.jsonl
```

### ② 单次提取

#### 方法 1：使用脚本（推荐）

```bash
# 完整提取
python scripts/claude_session_extract.py --session <session-id>

# 只输出工作摘要
python scripts/claude_session_extract.py --summary <session.jsonl>
```

脚本输出包含以下 section：

| Section | 说明 |
|---------|------|
| **SESSION INFO** | 标题、session ID、工作目录、分支、版本 |
| **STATISTICS** | 消息计数、文件变更数、API 错误数 |
| **TOOL USE DISTRIBUTION** | 工具调用频率分布 |
| **USER MESSAGES** | 用户实际输入（过滤工具结果） |
| **FILE CHANGE CHAIN** | 文件变更时间线（核心恢复依据） |
| **LAST ASSISTANT OUTPUTS** | 最后几条 Agent 文本输出 |
| **QUEUED OPERATIONS** | 用户排队的输入 |
| **WORK INFERENCE** | 逆推的工作摘要 |
| **DECISION HINT** | 自动判断是否需要深入 |

#### 方法 2：手动提取（备选）

**读 session info**：

```python
import json
with open(filepath, 'r', encoding='utf-8') as f:
    first = json.loads(f.readline())
    print(first.get('sessionId'), first.get('cwd'), first.get('gitBranch'))
```

**提取文件变更链**：

```python
with open(filepath, 'r', encoding='utf-8') as f:
    for line in f:
        obj = json.loads(line)
        if obj.get('type') == 'file-history-snapshot':
            snap = obj.get('snapshot', {})
            backups = snap.get('trackedFileBackups', {})
            if backups:
                print(f'[{snap.get("timestamp", "")}] {list(backups.keys())}')
```

**提取最后几条 Agent 文本输出**：

```python
texts = []
with open(filepath, 'r', encoding='utf-8') as f:
    for line in f:
        obj = json.loads(line)
        if obj.get('type') == 'assistant':
            msg = obj.get('message', {})
            for c in msg.get('content', []):
                if c.get('type') == 'text' and c.get('text', '').strip():
                    texts.append(c['text'].strip())
for t in texts[-3:]:
    print(t[:500])
    print('---')
```

### ③ 核对仓库状态

同 Codex skill：`git log`、`git status`、`git branch` 验证。

### ④ 合成交接报告

**Claude Code 没有 task_complete**，所以报告的「已完成工作」部分需要从以下信息逆推：

```
工作摘要 = 文件变更链（哪些文件改了） + 工具使用模式（做了什么操作） + 最后几条 Agent 输出（结论/计划）
```

报告格式：

```markdown
# 上下文恢复报告（Claude Code）

## 来源信息
- 原始 Agent: Claude Code
- Session ID: [从文件提取]
- 工作目录: [cwd]
- 分支: [gitBranch]
- 版本: [version]
- 会话标题: [custom-title]

## 已完成的工作（逆推）

> 注意：Claude Code 无 task_complete，以下为从文件变更链和 Agent 输出逆推的结论。

| 文件 | 变更次数 | 说明 |
|------|----------|------|
| [file path] | N | 从 agent 最后输出推断 |

## 工具使用统计

| 工具 | 次数 |
|------|------|
| Bash | N |
| Read | N |

## 最后 Agent 输出

[最后 1-3 条 Agent 文本输出，这是最接近"工作总结"的信息]

## 验证结果

| 检查项 | 状态 |
|--------|------|
| git log 一致性 | Y/N |
| 工作树匹配 | Y/N |

## 已知问题
1. ...

## 下一步计划
1. ...
```

---

## 提取决策树

```
有 file-history-snapshot 且 trackedFileBackups 非空？
├─ YES → 从文件变更链逆推工作内容
│        + 结合最后 assistant 输出获取结论
│        → 通常足够合成报告
└─ NO
    ├─ 有 assistant 文本输出？
    │   ├─ YES → 从 Agent 输出推断工作
    │   └─ NO → 从 tool_use 调用统计推断
    └─ 需要深入 user 消息和 tool_result 重建上下文
```

---

## 核心原则

1. **先验证，再报告** — 会话记录可能过时
2. **不加幻觉** — 没有 task_complete 就不要假装有，标注「逆推」
3. **文件变更链优先** — `file-history-snapshot` 是最可靠的工作证据
4. **最后输出最重要** — Agent 的最后几条文本输出最接近当前状态
5. **不破坏已有工作** — 只读取不写入
6. **单次遍历** — 所有信息一次提取完成
7. **空值过滤** — 所有提取加 `if msg.strip()`
