"""A scripted stand-in for anthropic.AsyncAnthropic, returning real SDK message objects.

Each script entry is a BetaMessage, an exception to raise, or a callable(kwargs) -> either of those.
Every request's kwargs are recorded, with `messages` snapshotted at call time.
"""

import asyncio
import copy
import itertools
from types import SimpleNamespace

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
        self._item = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _next(self):
        if self._item is None:
            self.client.requests.append({**self.kwargs, "messages": copy.deepcopy(self.kwargs["messages"])})
            if not self.client.script:
                raise AssertionError("fake Claude ran out of scripted replies")
            item = self.client.script.pop(0)
            if callable(item) and not isinstance(item, BaseException):
                item = item(self.kwargs)
            if asyncio.iscoroutine(item):
                item = await item
            self._item = item
        if isinstance(self._item, BaseException):
            raise self._item
        return self._item

    async def __aiter__(self):
        """The events the agent looks at: content_block_start per block, and text deltas a few words at a time."""
        message = await self._next()
        for block in message.content:
            yield SimpleNamespace(type="content_block_start", content_block=block)
            if block.type == "text":
                words = block.text.split(" ")
                for i in range(0, len(words), 3):
                    await asyncio.sleep(0)
                    yield SimpleNamespace(type="text", text=" ".join(words[i:i + 3]) + (" " if i + 3 < len(words) else ""))

    async def get_final_message(self):
        return await self._next()


class FakeClaude:
    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.beta = self
        self.messages = self

    def stream(self, **kwargs):
        return _Stream(self, kwargs)
