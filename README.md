# claude-code-session-extract

从 Claude Code 会话 JSONL 文件中提取上下文，生成结构化的交接报告。

## 用法

```bash
# 按 session ID 自动定位并提取
python scripts/claude_session_extract.py --session <session-id>

# 直接指定文件
python scripts/claude_session_extract.py <session.jsonl>

# 只输出工作摘要
python scripts/claude_session_extract.py --summary <session.jsonl>
```

## 与 codex-rollout-extract 的关系

| | codex-rollout-extract | claude-code-session-extract |
|---|---|---|
| 目标格式 | Codex JSONL | Claude Code JSONL |
| 核心恢复入口 | `task_complete` | 文件变更链逆推 |
| 存储位置 | `~/.codex/sessions/` | `~/.claude/projects/` |
