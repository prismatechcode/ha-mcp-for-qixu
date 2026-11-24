"""Turn a Chinese utterance into hub tool calls (rule fast-path + Bailian LLM)."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("qixu_hub.voice")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LLM_CONFIGS = (
    ROOT / "hub" / "config.json",
    Path(r"d:\workspace\ha-voice-assistant\config.json"),
)


def load_llm_config() -> dict[str, Any]:
    for path in DEFAULT_LLM_CONFIGS:
        if path.is_file():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            return {
                "api_key": (cfg.get("deepseek_api_key") or cfg.get("llm_api_key") or "").strip(),
                "base_url": (
                    cfg.get("deepseek_base_url")
                    or cfg.get("llm_base_url")
                    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
                ).rstrip("/"),
                "model": cfg.get("deepseek_model") or cfg.get("llm_model") or "qwen-plus",
            }
    return {"api_key": "", "base_url": "", "model": ""}


def _tool_text(result: dict[str, Any]) -> str:
    content = (result or {}).get("content") or []
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
        elif isinstance(item, str):
            parts.append(item)
    return "\n".join(p for p in parts if p).strip()


def _parse_jsonish(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def rule_plan(text: str) -> dict[str, Any] | None:
    """Fast path for common office phrases → HassTurnOn/Off + name."""
    t = (text or "").strip()
    if not t:
        return None
    action = None
    if any(k in t for k in ("打开", "开启", "开一下", "开灯")):
        action = "HassTurnOn"
    elif any(k in t for k in ("关闭", "关掉", "关一下", "关灯")):
        action = "HassTurnOff"
    if not action:
        return None

    name = None
    if "办公室灯" in t or ("办公" in t and "灯" in t and "空调" not in t):
        name = "办公室灯"
    elif "会议室灯" in t or ("会议" in t and "灯" in t):
        name = "会议室灯"
    elif "经理室灯" in t or ("经理" in t and "灯" in t):
        name = "经理室灯"
    elif "办公室空调" in t or ("空调" in t and ("打开" in t or "关闭" in t or "开" in t or "关" in t)):
        # Prefer script aliases exposed as tools
        if action == "HassTurnOn":
            return {
                "engine": "rule",
                "calls": [{"name": "da_kai_ban_gong_shi_kong_tiao", "arguments": {}}],
                "speech_hint": "好的，已打开办公室空调",
            }
        return {
            "engine": "rule",
            "calls": [{"name": "guan_bi_ban_gong_shi_kong_tiao", "arguments": {}}],
            "speech_hint": "好的，已关闭办公室空调",
        }
    if not name:
        return None
    verb = "打开" if action == "HassTurnOn" else "关闭"
    return {
        "engine": "rule",
        "calls": [{"name": action, "arguments": {"name": name}}],
        "speech_hint": f"好的，已{verb}{name}",
    }


def llm_plan(text: str, tools: list[dict[str, Any]], llm: dict[str, Any]) -> dict[str, Any]:
    if not llm.get("api_key"):
        raise RuntimeError("未配置大模型 API Key（hub/config.json 或 ha-voice-assistant/config.json）")

    tool_lines = []
    for tool in tools:
        name = tool.get("name")
        if not name or name == "QixuConfirmAction":
            continue
        desc = (tool.get("description") or "").replace("\n", " ")[:180]
        schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
        tool_lines.append(f"- {name}: {desc}\n  args={json.dumps(schema, ensure_ascii=False)}")

    system = (
        "你是栖序智能家居调度器。根据用户中文指令，从工具列表中选择要调用的工具。"
        "只输出一个 JSON 对象，不要其它文字。格式："
        '{"calls":[{"name":"工具名","arguments":{}}],"speech_reply":"给用户的一句中文确认"}。'
        "规则：name 必须来自列表；能用一个工具就不要用多个；"
        "开灯/关灯用 HassTurnOn/HassTurnOff，arguments.name 填设备中文名（如办公室灯）；"
        "空调优先用 da_kai_ban_gong_shi_kong_tiao / guan_bi_ban_gong_shi_kong_tiao；"
        "无法匹配时 calls 为空，speech_reply 说明原因。"
    )
    user = f"用户说：{text}\n\n可用工具：\n" + "\n".join(tool_lines[:40])
    body = {
        "model": llm["model"],
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        f"{llm['base_url']}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {llm['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    content = (
        (((payload.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    )
    obj = _parse_jsonish(content) or {}
    calls = obj.get("calls") if isinstance(obj.get("calls"), list) else []
    cleaned = []
    names = {t.get("name") for t in tools}
    for c in calls:
        if not isinstance(c, dict):
            continue
        n = (c.get("name") or "").strip()
        if n in names and n != "QixuConfirmAction":
            cleaned.append({"name": n, "arguments": c.get("arguments") or {}})
    return {
        "engine": "llm",
        "calls": cleaned,
        "speech_hint": (obj.get("speech_reply") or "").strip(),
        "raw": content[:500],
    }


async def run_voice_turn(link, text: str) -> dict[str, Any]:
    """Execute one voice turn against a connected HomeLink."""
    text = (text or "").strip()
    if not text:
        return {
            "ok": False,
            "transcript": "",
            "reply": "我没有听清，请再说一次。",
            "executed": False,
            "actions": [],
            "engine": "none",
        }

    if not link.tools:
        await link.refresh_tools()

    plan = rule_plan(text)
    if plan is None:
        try:
            plan = llm_plan(text, link.tools, load_llm_config())
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("LLM plan failed")
            return {
                "ok": False,
                "transcript": text,
                "reply": f"语义分析失败：{err}",
                "executed": False,
                "actions": [],
                "engine": "error",
            }

    actions: list[dict[str, Any]] = []
    replies: list[str] = []
    executed = False
    needs_confirm = None

    for call in plan.get("calls") or []:
        result = await link.call(call["name"], call.get("arguments") or {})
        raw = _tool_text(result)
        parsed = _parse_jsonish(raw)
        actions.append(
            {
                "name": call["name"],
                "arguments": call.get("arguments") or {},
                "result": parsed if parsed is not None else raw,
            }
        )
        if isinstance(parsed, dict) and parsed.get("requires_confirmation"):
            needs_confirm = parsed
            replies.append(parsed.get("speech") or "需要确认后才能执行。")
            break
        if result.get("isError"):
            replies.append(raw or "执行失败。")
        else:
            executed = True
            if isinstance(parsed, dict):
                replies.append(
                    parsed.get("speech")
                    or parsed.get("speech_reply")
                    or plan.get("speech_hint")
                    or "好的。"
                )
            else:
                replies.append(plan.get("speech_hint") or "好的。")

    if not (plan.get("calls") or []):
        reply = plan.get("speech_hint") or "我没听懂要控制哪个设备。"
        return {
            "ok": False,
            "transcript": text,
            "reply": reply,
            "executed": False,
            "actions": [],
            "engine": plan.get("engine"),
        }

    reply = " ".join(r for r in replies if r).strip() or plan.get("speech_hint") or "好的。"
    return {
        "ok": executed or needs_confirm is not None,
        "transcript": text,
        "reply": reply,
        "executed": executed,
        "actions": actions,
        "engine": plan.get("engine"),
        "requires_confirmation": bool(needs_confirm),
        "confirm_id": (needs_confirm or {}).get("confirm_id"),
    }
