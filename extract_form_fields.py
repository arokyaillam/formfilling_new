import asyncio
import json
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
                response = await self.get_client().chat(
                    model=self.model,
                    messages=ollama_messages,
                    options=self.ollama_options,
                )
                return ChatInvokeCompletion(completion=response.message.content or '', usage=None)
            else:
                schema = output_format.model_json_schema()
                response = await self.get_client().chat(
                    model=self.model,
                    messages=ollama_messages,
                    format=schema,
                    options=self.ollama_options,
                )
                completion = response.message.content or ''
                if completion.startswith('```json'):
                    completion = re.sub(r'^```json\s*', '', completion, flags=re.MULTILINE)
                    completion = re.sub(r'\s*```$', '', completion, flags=re.MULTILINE)
                    print(f"[CleanJSON] Stripped ```json markdown from response")
                elif completion.startswith('```'):
                    completion = re.sub(r'^```\s*', '', completion, flags=re.MULTILINE)
                    completion = re.sub(r'\s*```$', '', completion, flags=re.MULTILINE)
                    print(f"[CleanJSON] Stripped ``` markdown from response")
                completion = output_format.model_validate_json(completion)
                return ChatInvokeCompletion(completion=completion, usage=None)
        except Exception as e:
            raise ModelProviderError(message=str(e), model=self.name) from e


async def main():
    # Get form URL from user
    form_url = input("Enter the form URL: ").strip()
    if not form_url:
        print("Error: No URL provided")
        return

    if not form_url.startswith(('http://', 'https://')):
        form_url = 'https://' + form_url
        print(f"Added https:// prefix: {form_url}")

    print(f"\nNavigating to: {form_url}")

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
    browser = Browser(headless=False)

    try:
        # Create agent to navigate to the page
        task = f"""
        Navigate to {form_url}
        Wait for the page to fully load
        Extract all form field information including:
        - Input fields (text, email, password, checkbox, radio, etc.)
        - Select dropdowns
        - Textareas
        - Labels for each field
        - Required status
        - Placeholder text
        Return the information as a detailed list
        """

        agent = Agent(
            task=task,
            llm=llm,
            browser=browser
        )

        print("Loading page and extracting form fields...")
        result = await agent.run()

        # Get the page content via JavaScript evaluation
        # We need to access the browser's current page
        from browser_use.browser.browser import BrowserSession

        # Get browser session and page
        session_manager = browser.session_manager
        session = await session_manager.get_session()

        if session and session.current_page:
            page = session.current_page

            # Execute JavaScript to extract form fields
            fields = await page.evaluate('''() => {
                const fields = [];
                const inputs = document.querySelectorAll('input, select, textarea');

                inputs.forEach((input, index) => {
                    const field = {
                        index: index,
                        tag: input.tagName.toLowerCase(),
                        type: input.type || null,
                        name: input.name || null,
                        id: input.id || null,
                        placeholder: input.placeholder || null,
                        required: input.required || false,
                        class: input.className || null
                    };

                    // Find associated label
                    let label = null;
                    if (input.id) {
                        const labelEl = document.querySelector(`label[for="${input.id}"]`);
                        if (labelEl) label = labelEl.textContent.trim();
                    }
                    if (!label) {
                        const parentLabel = input.closest('label');
                        if (parentLabel) {
                            const text = parentLabel.textContent.trim();
                            if (text) label = text;
                        }
                    }
                    if (!label) {
                        label = input.getAttribute('aria-label');
                    }
                    if (!label) {
                        const labelledBy = input.getAttribute('aria-labelledby');
                        if (labelledBy) {
                            const labelEl = document.getElementById(labelledBy);
                            if (labelEl) label = labelEl.textContent.trim();
                        }
                    }
                    if (!label) {
                        const prev = input.previousElementSibling;
                        if (prev && prev.tagName === 'LABEL') {
                            label = prev.textContent.trim();
                        }
                    }

                    field.label = label;

                    if (input.tagName === 'SELECT') {
                        field.options = Array.from(input.options).map(opt => ({
                            value: opt.value,
                            text: opt.text
                        }));
                    }

                    fields.push(field);
                });

                return fields;
            }''')

            # Build result
            output = {
                "url": form_url,
                "total_fields": len(fields),
                "fields": fields
            }

            # Save to JSON file
            output_file = "form_fields.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            print(f"\n✅ Form fields saved to: {output_file}")

            # Print preview
            print("\n=== FIELD PREVIEW ===")
            for field in fields[:10]:
                label = field.get('label') or field.get('placeholder') or field.get('name') or f"Field {field['index']}"
                field_type = field.get('type') or field.get('tag')
                print(f"  [{field['index']}] {label} ({field_type})")

            if len(fields) > 10:
                print(f"  ... and {len(fields) - 10} more")
        else:
            print("Could not access page for form extraction")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
