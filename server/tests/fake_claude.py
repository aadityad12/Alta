"""A scripted stand-in for anthropic.AsyncAnthropic, returning real SDK message objects.

Each script entry is a BetaMessage, an exception to raise, or a callable(kwargs) -> either of those.
Every request's kwargs are recorded, with `messages` snapshotted at call time.
"""

import asyncio
import copy
import itertools

from anthropic.types.beta import BetaMessage

_ids = itertools.count(1)


def msg(*blocks, stop=None, cache_read=0, cache_write=0):
    content = []
    for b in blocks:
        if isinstance(b, str):
            content.append({"type": "text", "text": b})
        else:
            name, args = b
            content.append({"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": args})
    if stop is None:
        stop = "tool_use" if any(c["type"] == "tool_use" for c in content) else "end_turn"
    return BetaMessage.model_validate({
        "id": f"msg_{next(_ids)}", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, *content],
        "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 50, "output_tokens": 20,
                  "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write},
    })


def tool(name, **args):
    return (name, args)


class _Stream:
    def __init__(self, client, kwargs):
        self.client, self.kwargs = client, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        self.client.requests.append({**self.kwargs, "messages": copy.deepcopy(self.kwargs["messages"])})
        if not self.client.script:
            raise AssertionError("fake Claude ran out of scripted replies")
        item = self.client.script.pop(0)
        if callable(item) and not isinstance(item, BaseException):
            item = item(self.kwargs)
        if asyncio.iscoroutine(item):
            item = await item
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClaude:
    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.beta = self
        self.messages = self

    def stream(self, **kwargs):
        return _Stream(self, kwargs)
