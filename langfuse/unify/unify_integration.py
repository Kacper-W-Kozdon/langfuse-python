"""
If you use the unifyai Python package, you can use the Langfuse drop-in replacement to get full logging by changing only the import.

```diff
- from unify import Unify
+ from langfuse.unify import Unify
```

Langfuse automatically tracks:

- All prompts/completions with support for streaming, async and functions
- Latencies
- API Errors
- Model usage (tokens) and cost (USD)

The integration is fully interoperable with the `observe()` decorator and the low-level tracing SDK.

See docs for more details: https://langfuse.com/docs/integrations/openai
"""

import sys
import importlib.util
from wrapt import wrap_function_wrapper
from langfuse.utils.langfuse_singleton import LangfuseSingleton
from langfuse.client import Langfuse
from typing import Optional, List, Dict, Generator, AsyncGenerator
from unify.exceptions import status_error_map
from langfuse.openai import (
    OpenAILangfuse,
    auth_check,
    _filter_image_data,
)

if importlib.util.find_spec("openai") is not None:
    print("CHECK IMPORT")
    del sys.modules["openai"]
    openai = __import__("openai")
    sys.modules["openai"] = openai
try:
    import unify
except ImportError:
    raise ModuleNotFoundError(
        "Please install unify to use this feature: 'pip install unifyai'"
    )

from unify import Unify, AsyncUnify, ChatBot

auth_check = auth_check
_filter_image_data = _filter_image_data


def _unify_wrapper(func):
    # print(func.__name__)

    def swapper(replacer, initialize):
        # print(f"REPLACER: {str(replacer)}")
        print(f"INI: {str(initialize)}")

        # @functools.wraps(replacer)
        def wrapper(
            wrapped,
            instance,
            args,
            kwargs,
        ):
            # print(f"RAW ARGS: {args}")
            args = (args[0], replacer)
            # print(args)
            # print(f"WRAPPED: {wrapped}")

            return func(replacer, initialize, wrapped, args, kwargs)

        # print(f"WRAPPER: {str(wrapper)}")
        return wrapper

    # print(f"SWAPPER: {str(swapper)}")
    return swapper


@_unify_wrapper
def _replacement_wrap(
    replacer,
    initialize,
    wrapped,
    args,
    kwargs,
):
    # print(f"INIT WRAPPED: {wrapped}")
    print(f"ARG: {str(args[0].method)}")
    print("_WRAP IN UNIFY")
    return wrapped(*args)


@_unify_wrapper
def _replacement_wrap_async(
    replacer,
    initialize,
    wrapped,
    args,
    kwargs,
):
    return wrapped(*args)


class UnifyLangfuse(OpenAILangfuse):
    _langfuse: Optional[Langfuse] = None

    def initialize_unify(self):
        self._langfuse = LangfuseSingleton().get(
            public_key=unify.langfuse_public_key,
            secret_key=unify.langfuse_secret_key,
            host=unify.langfuse_host,
            debug=unify.langfuse_debug,
            enabled=unify.langfuse_enabled,
            sdk_integration="unify",
        )
        print(f"UnifyLangfuse.initialize, {unify.langfuse_enabled}")
        return self._langfuse

    def unify_tracing(self):
        setattr(unify, "langfuse_public_key", None)
        setattr(unify, "langfuse_secret_key", None)
        setattr(unify, "langfuse_host", None)
        setattr(unify, "langfuse_debug", None)
        setattr(unify, "langfuse_enabled", True)
        setattr(unify, "flush_langfuse", self.flush)

    def reregister_tracing(self):
        print("Register")

        wrap_function_wrapper(
            "langfuse.openai",
            "_wrap",
            _replacement_wrap(self.initialize_unify, self.initialize),
        )

        wrap_function_wrapper(
            "langfuse.openai",
            "_wrap_async",
            _replacement_wrap_async(self.initialize_unify, self.initialize),
        )

        setattr(unify, "langfuse_public_key", None)
        setattr(unify, "langfuse_secret_key", None)
        setattr(unify, "langfuse_host", None)
        setattr(unify, "langfuse_debug", None)
        setattr(unify, "langfuse_enabled", True)
        setattr(unify, "flush_langfuse", self.flush)


# OpenAILangfuse.initialize = UnifyLangfuse.initialize
# modifier.register_tracing()
modifierUnify = UnifyLangfuse()
modifierUnify.reregister_tracing()
modifierUnify.register_tracing()


class Unify(Unify):
    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        super().__init__(endpoint, model, provider, api_key)

    def generate_completion(self, endpoint, messages, max_tokens, stream, **kwargs):
        chat_completion = self.client.chat.completions.create(
            model=endpoint,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            stream=stream,
            name="Unify-generation",
            metadata={
                "model": self.model,
                "provider": self.provider,
                "endpoint": self.endpoint,
            },
            **kwargs,
        )
        return chat_completion

    def _generate_stream(
        self,
        messages: List[Dict[str, str]],
        endpoint: str,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        try:
            chat_completion = self.generate_completion(
                endpoint, messages, max_tokens, True, **kwargs
            )

            for chunk in chat_completion:
                content = chunk.choices[0].delta.content  # type: ignore[union-attr]
                self.set_provider(chunk.model.split("@")[-1])  # type: ignore[union-attr]
                if content is not None:
                    yield content
        except openai.APIStatusError as e:
            raise status_error_map[e.status_code](e.message) from None

    def _generate_non_stream(
        self,
        messages: List[Dict[str, str]],
        endpoint: str,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        try:
            chat_completion = self.generate_completion(
                endpoint, messages, max_tokens, False, **kwargs
            )

            self.set_provider(
                chat_completion.model.split(  # type: ignore[union-attr]
                    "@",
                )[-1]
            )

            return chat_completion.choices[0].message.content.strip(" ")  # type: ignore # noqa: E501, WPS219
        except openai.APIStatusError as e:
            raise status_error_map[e.status_code](e.message) from None


class AsyncUnify(AsyncUnify):
    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        super().__init__(endpoint, model, provider, api_key)

    async def async_generate_completion(self, endpoint, messages, max_tokens, stream):
        chat_completion = await self.client.chat.completions.create(
            model=endpoint,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            stream=stream,
        )

        return chat_completion

    async def _generate_stream(
        self,
        messages: List[Dict[str, str]],
        endpoint: str,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        try:
            async_stream = self.async_generate_completion(
                endpoint,
                messages,  # type: ignore[arg-type]
                max_tokens,
                True,
            )
            async for chunk in async_stream:  # type: ignore[union-attr]
                self.set_provider(chunk.model.split("@")[-1])
                yield chunk.choices[0].delta.content or ""
        except openai.APIStatusError as e:
            raise status_error_map[e.status_code](e.message) from None

    async def _generate_non_stream(
        self,
        messages: List[Dict[str, str]],
        endpoint: str,
        max_tokens: Optional[int] = None,
    ) -> str:
        try:
            async_response = self.async_generate_completion(
                endpoint,
                messages,  # type: ignore[arg-type]
                max_tokens,
                True,
            )
            self.set_provider(async_response.model.split("@")[-1])  # type: ignore
            return async_response.choices[0].message.content.strip(" ")  # type: ignore # noqa: E501, WPS219
        except openai.APIStatusError as e:
            raise status_error_map[e.status_code](e.message) from None


class ChatBot(ChatBot):
    class ChatBot:  # noqa: WPS338
        """Agent class represents an LLM chat agent."""

        def __init__(
            self,
            endpoint: Optional[str] = None,
            model: Optional[str] = None,
            provider: Optional[str] = None,
            api_key: Optional[str] = None,
        ) -> None:
            super().__init__(endpoint, model, provider, api_key)
            self._client = Unify(
                api_key=api_key,
                endpoint=endpoint,
                model=model,
                provider=provider,
            )


unify.Unify = Unify
unify.AsyncUnify = AsyncUnify
unify.ChatBot = ChatBot
