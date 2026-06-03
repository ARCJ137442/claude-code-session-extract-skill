#!/usr/bin/env python3
"""
Claude Code Session Extractor — 单次遍历 JSONL，提取会话上下文。

与 Codex 的关键区别：Claude Code 没有 task_complete 事件，
需要从文件变更链、工具使用模式和 agent 文本输出逆推工作摘要。

用法：
    # 1. 按 session ID 自动定位
    python claude_session_extract.py --session <session-id>

    # 2. 直接指定文件
    python claude_session_extract.py <session.jsonl>

    # 3. 只输出工作摘要（用于快速交接）
    python claude_session_extract.py --summary <session.jsonl>
"""
import json
import os
import sys
import glob
from collections import Counter


def find_session(session_id, claude_home=None):
    """给定 session ID，在 .claude/projects/ 中搜索对应文件。"""
    if claude_home is None:
        claude_home = os.path.expanduser("~/.claude")

    projects_dir = os.path.join(claude_home, "projects")
    pattern = os.path.join(projects_dir, "**", f"{session_id}.jsonl")
    for f in glob.glob(pattern, recursive=True):
        return f

    return None


def extract(filepath, mode="full"):
    """
    单次遍历 Claude Code JSONL 文件，提取所有关键信息。
    mode: "full" | "summary"
    """
    result = {
        "session_info": {},
        "user_msgs": [],
        "assistant_texts": [],
        "tool_uses": [],
        "tool_use_counts": Counter(),
        "file_changes": [],       # [(timestamp, [files])]
        "file_change_set": set(),  # 所有变更过的文件
        "system_events": [],      # (subtype, content_preview)
        "queue_ops": [],          # 用户排队的输入
        "session_title": "",
        "total_user_msgs": 0,
        "total_assistant_msgs": 0,
        "total_tool_results": 0,
        "api_errors": 0,
    }

    with open(filepath, "r", encoding="utf-8") as f:
        first_line = True
        for line in f:
            obj = json.loads(line)
            t = obj.get("type", "")

            # --- 第一条 user 消息提取 session info ---
            if first_line and t == "user":
                first_line = False
                result["session_info"] = {
                    "sessionId": obj.get("sessionId", ""),
                    "cwd": obj.get("cwd", ""),
                    "gitBranch": obj.get("gitBranch", ""),
                    "version": obj.get("version", ""),
                    "entrypoint": obj.get("entrypoint", ""),
                }

            # --- user 消息 ---
            if t == "user":
                result["total_user_msgs"] += 1
                msg = obj.get("message", {})
                content = msg.get("content", "")
                is_meta = obj.get("isMeta", False)

                # 过滤 tool_result（这是工具返回值，不是用户输入）
                if isinstance(content, list):
                    for c in content:
                        if c.get("type") == "tool_result":
                            result["total_tool_results"] += 1
                            continue
                        if c.get("type") == "text":
                            text = c.get("text", "").strip()
                            if text:
                                result["user_msgs"].append({
                                    "text": text[:2000],
                                    "isMeta": is_meta,
                                    "timestamp": obj.get("timestamp", ""),
                                })
                elif isinstance(content, str):
                    text = content.strip()
                    if text:
                        result["user_msgs"].append({
                            "text": text[:2000],
                            "isMeta": is_meta,
                            "timestamp": obj.get("timestamp", ""),
                        })

            # --- assistant 消息 ---
            elif t == "assistant":
                result["total_assistant_msgs"] += 1
                msg = obj.get("message", {})
                content = msg.get("content", [])

                if isinstance(content, list):
                    for c in content:
                        if c.get("type") == "text":
                            text = c.get("text", "").strip()
                            if text:
                                result["assistant_texts"].append({
                                    "text": text[:2000],
                                    "timestamp": obj.get("timestamp", ""),
                                })
                        elif c.get("type") == "tool_use":
                            tool_name = c.get("name", "unknown")
                            result["tool_use_counts"][tool_name] += 1
                            # 记录有内容的工具调用（Bash 命令、Read 文件等）
                            inp = c.get("input", {})
                            detail = ""
                            if tool_name == "Bash":
                                detail = inp.get("command", "")[:200]
                            elif tool_name == "Read":
                                detail = inp.get("file_path", "")[:200]
                            elif tool_name in ("Write", "Edit"):
                                detail = inp.get("file_path", "")[:200]
                            elif tool_name == "Grep":
                                detail = inp.get("pattern", "")[:200]
                            elif tool_name == "Glob":
                                detail = inp.get("pattern", "")[:200]
                            elif tool_name == "Agent":
                                detail = (inp.get("description", "") + " " + inp.get("prompt", ""))[:200]
                            elif tool_name == "WebFetch":
                                detail = inp.get("url", "")[:200]
                            elif tool_name == "WebSearch":
                                detail = inp.get("query", "")[:200]
                            result["tool_uses"].append({
                                "tool": tool_name,
                                "detail": detail.strip(),
                                "timestamp": obj.get("timestamp", ""),
                            })

            # --- system 消息 ---
            elif t == "system":
                subtype = obj.get("subtype", "")
                content = obj.get("content", "")
                if subtype == "api_error":
                    result["api_errors"] += 1
                if subtype in ("local_command", "api_error"):
                    result["system_events"].append({
                        "subtype": subtype,
                        "content": (content[:200] if isinstance(content, str) else ""),
                        "level": obj.get("level", ""),
                    })

            # --- file-history-snapshot ---
            elif t == "file-history-snapshot":
                snap = obj.get("snapshot", {})
                backups = snap.get("trackedFileBackups", {})
                if backups:
                    files = list(backups.keys())
                    result["file_changes"].append({
                        "timestamp": snap.get("timestamp", ""),
                        "messageId": snap.get("messageId", ""),
                        "files": files,
                    })
                    result["file_change_set"].update(files)

            # --- queue-operation ---
            elif t == "queue-operation":
                content = obj.get("content", "")
                if content and content.strip():
                    result["queue_ops"].append({
                        "text": content.strip()[:500],
                        "timestamp": obj.get("timestamp", ""),
                    })

            # --- custom-title / agent-name ---
            elif t == "custom-title":
                title = obj.get("customTitle", "")
                if title:
                    result["session_title"] = title
            elif t == "agent-name":
                name = obj.get("agentName", "")
                if name and not result["session_title"]:
                    result["session_title"] = name

    return result


def print_full(result):
    """格式化输出完整提取结果。"""
    info = result["session_info"]

    # --- SESSION INFO ---
    print("=" * 60)
    print("SESSION INFO")
    print(f"  Title:     {result['session_title'] or '(untitled)'}")
    print(f"  SessionID: {info.get('sessionId', 'N/A')}")
    print(f"  CWD:       {info.get('cwd', 'N/A')}")
    print(f"  Branch:    {info.get('gitBranch', 'N/A')}")
    print(f"  Version:   {info.get('version', 'N/A')}")
    print(f"  Entrypoint:{info.get('entrypoint', 'N/A')}")
    print()

    # --- STATISTICS ---
    print("=" * 60)
    print("STATISTICS")
    print(f"  User messages:      {result['total_user_msgs']}")
    print(f"  Assistant messages:  {result['total_assistant_msgs']}")
    print(f"  Tool results:       {result['total_tool_results']}")
    print(f"  API errors:         {result['api_errors']}")
    print(f"  Files changed:      {len(result['file_change_set'])}")
    print(f"  File change events: {len(result['file_changes'])}")
    print(f"  Queued operations:  {len(result['queue_ops'])}")
    print()

    # --- TOOL USE DISTRIBUTION ---
    if result["tool_use_counts"]:
        print("=" * 60)
        print("TOOL USE DISTRIBUTION")
        for tool, count in result["tool_use_counts"].most_common():
            print(f"  {tool}: {count}")
        print()

    # --- USER MESSAGES (非 meta) ---
    real_user_msgs = [m for m in result["user_msgs"] if not m["isMeta"]]
    if real_user_msgs:
        print("=" * 60)
        print(f"USER MESSAGES ({len(real_user_msgs)} total, showing first 5)")
        for i, m in enumerate(real_user_msgs[:5]):
            ts = m["timestamp"][:19] if m["timestamp"] else ""
            print(f"  [{i+1}] ({ts}) {m['text'][:300]}")
            print()

    # --- FILE CHANGE CHAIN ---
    if result["file_changes"]:
        print("=" * 60)
        print(f"FILE CHANGE CHAIN ({len(result['file_changes'])} events)")
        for fc in result["file_changes"]:
            ts = fc["timestamp"][:19] if fc["timestamp"] else ""
            files_short = [os.path.basename(f) for f in fc["files"]]
            print(f"  [{ts}] {', '.join(files_short)}")
        print()
        print("  ALL CHANGED FILES:")
        for f in sorted(result["file_change_set"]):
            print(f"    {f}")
        print()

    # --- LAST 3 ASSISTANT TEXTS ---
    if result["assistant_texts"]:
        print("=" * 60)
        print(f"LAST ASSISTANT OUTPUTS (3 of {len(result['assistant_texts'])})")
        for at in result["assistant_texts"][-3:]:
            ts = at["timestamp"][:19] if at["timestamp"] else ""
            print(f"  [{ts}] {at['text'][:500]}")
            print()

    # --- QUEUE OPERATIONS ---
    if result["queue_ops"]:
        print("=" * 60)
        print(f"QUEUED OPERATIONS ({len(result['queue_ops'])})")
        for qo in result["queue_ops"]:
            print(f"  - {qo['text'][:200]}")
        print()

    # --- SYSTEM EVENTS ---
    if result["system_events"]:
        api_errors = [e for e in result["system_events"] if e["subtype"] == "api_error"]
        if api_errors:
            print("=" * 60)
            print(f"API ERRORS ({len(api_errors)})")
            for e in api_errors[:3]:
                print(f"  [{e['level']}] {e['content'][:150]}")
            print()

    # --- WORK INFERENCE ---
    print("=" * 60)
    print("WORK INFERENCE (no task_complete — inferred from traces)")
    if result["file_change_set"]:
        print("  Files modified:")
        for f in sorted(result["file_change_set"]):
            print(f"    {f}")
    if result["tool_use_counts"]:
        top_tools = result["tool_use_counts"].most_common(3)
        print(f"  Top tools: {', '.join(f'{t}({c})' for t, c in top_tools)}")
    if result["assistant_texts"]:
        print(f"  Last agent output preview: {result['assistant_texts'][-1]['text'][:200]}")
    print()

    # --- DECISION HINT ---
    print("=" * 60)
    print("DECISION HINT")
    if result["file_change_set"]:
        print("  有文件变更记录 → 可以从文件变更链逆推工作摘要")
    elif result["assistant_texts"]:
        print("  无文件变更但有 assistant 输出 → 从文本输出推断工作")
    else:
        print("  信息极少 → 需要深入 tool_use 调用记录")
    print()


def print_summary_only(result):
    """只输出工作摘要（用于快速交接）。"""
    print(f"Session: {result['session_title'] or '(untitled)'}")
    print(f"Branch: {result['session_info'].get('gitBranch', 'N/A')}")
    print(f"CWD: {result['session_info'].get('cwd', 'N/A')}")
    print()

    if result["file_change_set"]:
        print("Files changed:")
        for f in sorted(result["file_change_set"]):
            print(f"  {f}")
        print()

    if result["tool_use_counts"]:
        print("Tool usage:")
        for tool, count in result["tool_use_counts"].most_common():
            print(f"  {tool}: {count}")
        print()

    if result["assistant_texts"]:
        print("Last output:")
        print(result["assistant_texts"][-1]["text"][:500])


def main():
    args = sys.argv[1:]

    if not args:
        print("Usage:")
        print("  python claude_session_extract.py <session.jsonl>")
        print("  python claude_session_extract.py --session <session-id> [--claude-home <path>]")
        print("  python claude_session_extract.py --summary <session.jsonl>")
        sys.exit(1)

    mode = "full"
    filepath = None
    claude_home = None

    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
            filepath = find_session(session_id, claude_home)
            if not filepath:
                print(f"ERROR: Cannot find session file for ID {session_id}")
                print("  Searched: ~/.claude/projects/**/<session-id>.jsonl")
                sys.exit(1)
            print(f"Found: {filepath}")
            print()
        elif args[i] == "--claude-home" and i + 1 < len(args):
            claude_home = args[i + 1]
            i += 2
        elif args[i] == "--summary" and i + 1 < len(args):
            mode = "summary"
            filepath = args[i + 1]
            i += 2
        else:
            filepath = args[i]
            i += 1

    if not filepath:
        print("ERROR: No input file specified")
        sys.exit(1)

    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    if size_mb > 10:
        print(f"NOTE: File is {size_mb:.1f}MB, streaming line-by-line")
        print()

    result = extract(filepath, mode)

    if mode == "full":
        print_full(result)
    elif mode == "summary":
        print_summary_only(result)


if __name__ == "__main__":
    main()
