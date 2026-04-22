import asyncio
import os
import re
from browser_use import Agent, Browser
from browser_use.llm.ollama.chat import ChatOllama
from browser_use.llm.ollama.serializer import OllamaMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.llm.exceptions import ModelProviderError


class CleanJSONChatOllama(ChatOllama):
    """Custom ChatOllama that strips markdown code blocks from responses."""

    async def ainvoke(self, messages, output_format=None, **kwargs):
        """Override ainvoke to clean markdown from responses before validation."""
        ollama_messages = OllamaMessageSerializer.serialize_messages(messages)

        try:
            if output_format is None:
                # Simple text completion - no JSON to validate
                response = await self.get_client().chat(
                    model=self.model,
                    messages=ollama_messages,
                    options=self.ollama_options,
                )
                return ChatInvokeCompletion(completion=response.message.content or '', usage=None)
            else:
                # Structured output - need to clean markdown before JSON validation
                schema = output_format.model_json_schema()

                response = await self.get_client().chat(
                    model=self.model,
                    messages=ollama_messages,
                    format=schema,
                    options=self.ollama_options,
                )

                completion = response.message.content or ''

                # Strip markdown code blocks if present (THE FIX!)
                if completion.startswith('```json'):
                    completion = re.sub(r'^```json\s*', '', completion, flags=re.MULTILINE)
                    completion = re.sub(r'\s*```$', '', completion, flags=re.MULTILINE)
                    print(f"[CleanJSON] Stripped ```json markdown from response")
                elif completion.startswith('```'):
                    completion = re.sub(r'^```\s*', '', completion, flags=re.MULTILINE)
                    completion = re.sub(r'\s*```$', '', completion, flags=re.MULTILINE)
                    print(f"[CleanJSON] Stripped ``` markdown from response")

                # Now validate the cleaned JSON
                completion = output_format.model_validate_json(completion)

                return ChatInvokeCompletion(completion=completion, usage=None)

        except Exception as e:
            raise ModelProviderError(message=str(e), model=self.name) from e


async def main():
    # Ollama Cloud config (set env vars before creating ChatOllama)
    os.environ["OLLAMA_HOST"] = os.getenv("OLLAMA_HOST", "https://ollama.com")
    api_key = os.getenv("OLLAMA_API_KEY")
    if api_key:
        os.environ["OLLAMA_API_KEY"] = api_key

    # LLM
    llm = CleanJSONChatOllama(
        model="gemma4:31b",
        ollama_options={"num_ctx": 16000}
    )

    # Browser
    browser = Browser(headless=False)  # UI visible

    # Task (IMPORTANT: keep simple)
    task = """
    Go to https://google.com
    Tell me the title of the page
    """

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser
    )

    result = await agent.run()

    print("\n=== RESULT ===")
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(result)

    # Browser auto-closes on context exit, no explicit close needed


if __name__ == "__main__":
    asyncio.run(main())
