"""LLM 适配层：DeepSeek V4 Pro（OpenAI 兼容接口）。

设计要点：
- Key 从环境变量 DEEPSEEK_API_KEY 读取（也支持本目录 .env 文件），绝不硬编码
- DeepSeek 的 json_object 模式要求 prompt 中包含 "json" 字样（prompts.py 已保证）
- 返回统一结构 {"data", "elapsed", "usage"}，上层（analyzer.py）不感知供应商细节
"""
import json
import os
import time

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # python-dotenv 未安装时只读系统环境变量

from openai import OpenAI

BASE_URL = "https://api.deepseek.com"
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
MAX_TOKENS = 8192
TEMPERATURE = 0.0

# 官方闲时价（$/1M tokens，2026-09 检索 api-docs.deepseek.com），仅用于成本估算展示
PRICE_INPUT = 0.66
PRICE_CACHE_HIT = 0.022
PRICE_OUTPUT = 1.98


def is_valid_key(key: str | None) -> bool:
    """Key 能否用于真实请求：非空、纯 ASCII（HTTP 头硬要求）、sk- 开头。

    只拦「确定发不出去」的值（如 .env 里的占位符 sk-你的key），不放行之外的格式一律不过度校验。
    """
    return bool(key) and key.isascii() and key.startswith("sk-")


class DeepSeekClient:
    """DeepSeek V4 Pro 客户端封装。"""

    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "未找到环境变量 DEEPSEEK_API_KEY。\n"
                "PowerShell 设置：$env:DEEPSEEK_API_KEY='sk-...'\n"
                "或在本目录创建 .env 文件：DEEPSEEK_API_KEY=sk-..."
            )
        if not is_valid_key(api_key):
            raise RuntimeError(
                "DEEPSEEK_API_KEY 无效（可能仍是 .env 里的占位符 sk-你的key）。\n"
                "请在 .env 中填入真实 Key 后重启程序。"
            )
        self._client = OpenAI(api_key=api_key, base_url=BASE_URL)
        self.model = MODEL

    def complete(self, system: str, user: str) -> dict:
        """一次非流式调用。返回 {"data": dict, "elapsed": float, "usage": dict}。

        失败时抛异常（由 analyzer._run_module 捕获后重试/降级）。
        """
        start = time.time()
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        elapsed = time.time() - start

        raw = (resp.choices[0].message.content or "{}").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"模型返回的不是合法 JSON：{e}（原始返回前 200 字：{raw[:200]}）"
            )
        return {
            "data": data,
            "elapsed": elapsed,
            "usage": self._usage(resp),
        }

    @staticmethod
    def _usage(resp) -> dict:
        """从响应对象提取 token 用量（兼容 dict / 对象两种 usage 形态）。"""
        u = getattr(resp, "usage", None) or {}

        def _g(name, default=0):
            if isinstance(u, dict):
                return u.get(name, default)
            return getattr(u, name, default)

        return {
            "input_tokens": _g("prompt_tokens"),
            "cache_hit_tokens": _g("prompt_cache_hit_tokens"),
            "output_tokens": _g("completion_tokens"),
        }

    def complete_with_tools(self, system: str, messages: list, tools: list) -> dict:
        """一次带工具定义的调用（默认输出格式，不强制 json_object，供 agent 循环使用）。

        messages：对话消息列表（user/assistant/tool 角色的 dict；assistant 含
        tool_calls 时格式为 {"id","type":"function","function":{"name","arguments"}}）。
        返回 {"message": {"content","tool_calls"}, "elapsed", "usage"}；
        tool_calls 为 [{"id","name","arguments"}]（arguments 为 JSON 字符串），无调用时为空列表。
        """
        start = time.time()
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "system", "content": system}] + list(messages),
            tools=tools,
        )
        elapsed = time.time() - start
        msg = resp.choices[0].message
        tool_calls = []
        for t in (msg.tool_calls or []):
            tool_calls.append({
                "id": t.id,
                "name": t.function.name,
                "arguments": t.function.arguments,
            })
        return {
            "message": {"content": (msg.content or "").strip(), "tool_calls": tool_calls},
            "elapsed": elapsed,
            "usage": self._usage(resp),
        }

    @staticmethod
    def estimate_cost(usage: dict) -> float:
        """按官方闲时价粗估累计成本（美元），仅展示用。"""
        miss = usage.get("input_tokens", 0) - usage.get("cache_hit_tokens", 0)
        cost = (
            miss * PRICE_INPUT
            + usage.get("cache_hit_tokens", 0) * PRICE_CACHE_HIT
            + usage.get("output_tokens", 0) * PRICE_OUTPUT
        ) / 1_000_000
        return cost


def get_client() -> DeepSeekClient:
    """工厂函数：上层只依赖此入口，未来切换供应商只改本文件。"""
    return DeepSeekClient()
