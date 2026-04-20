import asyncio
import json
import re
from playwright.async_api import async_playwright


async def extract_google_form_fields(page):
    """Extract fields from Google Forms specifically."""
    fields = await page.evaluate('''() => {
        const fields = [];
        let fieldIndex = 0;

        // Get all question containers
        const questionContainers = document.querySelectorAll('[role="listitem"]');

        questionContainers.forEach((container) => {
            // Skip non-question items (headers, sections, images)
            const hasInput = container.querySelector('input, textarea, [role="radio"], [role="checkbox"]');
            if (!hasInput) return;

            const field = {
                index: fieldIndex++,
                question: null,
                type: null,
                required: false,
                options: []
            };

            // Get question text
            const questionSelectors = [
                '[data-item-id] .freebirdFormviewerComponentsQuestionBaseTitle',
                '[data-item-id] span[role="heading"]',
                '.freebirdFormviewerComponentsQuestionBaseTitle',
                '[role="heading"]',
                '.freebirdFormviewerViewItemsItemItemTitle'
            ];

            for (const selector of questionSelectors) {
                const el = container.querySelector(selector);
                if (el && el.textContent.trim()) {
                    field.question = el.textContent.trim();
                    break;
                }
            }

            // Check if required
            const requiredIndicator = container.querySelector(
                '.freebirdFormviewerComponentsQuestionBaseRequiredAsterisk, [aria-label*="required"]'
            );
            field.required = requiredIndicator !== null;

            // Check for grid/matrix question first (Google Forms specific)
            const allRadiosInContainer = container.querySelectorAll('[role="radio"]');

            // Detect grid by checking if radios have "response for" pattern in aria-label
            const hasGridPattern = Array.from(allRadiosInContainer).some(r => {
                const label = r.getAttribute('aria-label') || '';
                return label.includes('response for');
            });

            if (hasGridPattern && allRadiosInContainer.length >= 4) {
                // This is a grid/matrix question
                field.type = 'grid';

                // Parse all radio options to extract rows and columns
                const rows = new Set();
                const columns = new Set();
                const allOptions = [];

                allRadiosInContainer.forEach(radio => {
                    const label = radio.getAttribute('aria-label');
                    if (label) {
                        allOptions.push({
                            value: label,
                            label: label
                        });

                        // Parse "Rating, response for Row Name"
                        const match = label.match(/^([^,]+),\\s*response for\\s*(.+)$/);
                        if (match) {
                            columns.add(match[1].trim());
                            rows.add(match[2].trim());
                        }
                    }
                });

                field.grid = {
                    columns: Array.from(columns),
                    rows: Array.from(rows)
                };

                field.options = allOptions;

            } else {
                // Regular question types
                const radioGroup = container.querySelectorAll('[role="radio"]');
                const checkboxes = container.querySelectorAll('[role="checkbox"]');
                const textInput = container.querySelector('input[type="text"], textarea');
                const scaleRadios = container.querySelector('[role="radiogroup"]');

                if (checkboxes.length > 0) {
                    field.type = 'checkbox';
                    field.options = Array.from(checkboxes).map(cb => ({
                        value: cb.getAttribute('aria-label'),
                        label: cb.getAttribute('aria-label')
                    }));

                } else if (radioGroup.length > 0 && radioGroup.length <= 10) {
                    // Check if it's a scale (numeric values)
                    const hasNumbers = Array.from(radioGroup).some(r => {
                        const label = r.getAttribute('aria-label') || '';
                        return /^\\d+$/.test(label);
                    });

                    if (hasNumbers) {
                        field.type = 'scale';
                    } else {
                        field.type = 'radio';
                    }

                    field.options = Array.from(radioGroup).map(r => ({
                        value: r.getAttribute('aria-label'),
                        label: r.getAttribute('aria-label')
                    }));

                } else if (textInput) {
                    if (textInput.tagName === 'TEXTAREA') {
                        field.type = 'textarea';
                    } else {
                        field.type = 'text';
                    }
                    field.placeholder = textInput.placeholder || null;

                } else if (scaleRadios) {
                    field.type = 'scale';
                    const options = scaleRadios.querySelectorAll('[role="radio"]');
                    field.options = Array.from(options).map(opt => ({
                        value: opt.getAttribute('aria-label'),
                        label: opt.getAttribute('aria-label')
                    }));
                }
            }

            if (field.question && field.type) {
                fields.push(field);
            }
        });

        return fields;
    }''')

    return fields


async def extract_generic_form_fields(page):
    """Extract fields from regular HTML forms."""
    fields = await page.evaluate('''() => {
        const fields = [];
        const inputs = document.querySelectorAll('input:not([type="hidden"]), select, textarea');

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

            // Find label
            let label = null;
            if (input.id) {
                const labelEl = document.querySelector(`label[for="${input.id}"]`);
                if (labelEl) label = labelEl.textContent.trim();
            }
            if (!label) {
                const parentLabel = input.closest('label');
                if (parentLabel) {
                    label = parentLabel.textContent.trim();
                }
            }
            if (!label) {
                label = input.getAttribute('aria-label');
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

    return fields


async def main():
    form_url = input("Enter the form URL: ").strip()
    if not form_url:
        print("Error: No URL provided")
        return

    if not form_url.startswith(('http://', 'https://')):
        form_url = 'https://' + form_url

    print(f"\nNavigating to: {form_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            await page.goto(form_url, wait_until='networkidle')
            await asyncio.sleep(3)  # Wait for JS to load

            # Scroll to bottom to ensure all dynamic content loads
            print("Scrolling to load all form elements...")
            await page.evaluate('''() => {
                window.scrollTo(0, document.body.scrollHeight);
            }''')
            await asyncio.sleep(2)

            print("Extracting form fields...")

            # Check if it's a Google Form
            is_google_form = await page.evaluate('''() => {
                return window.location.hostname.includes('docs.google.com') ||
                       document.querySelector('.freebirdFormviewerViewFormContent') !== null;
            }''')

            if is_google_form:
                print("Detected Google Form")
                fields = await extract_google_form_fields(page)
            else:
                print("Detected generic form")
                fields = await extract_generic_form_fields(page)

            # Build result
            result = {
                "url": form_url,
                "form_type": "google_form" if is_google_form else "generic",
                "total_fields": len(fields),
                "fields": fields
            }

            # Save to JSON
            output_file = "form_fields.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(f"\n[SAVED] {output_file}")
            print(f"   Total fields: {len(fields)}")

            # Print preview
            print("\n=== FIELD PREVIEW ===")
            for field in fields[:10]:
                if is_google_form:
                    q = field.get('question', f"Field {field['index']}")
                    t = field.get('type', 'unknown')
                    if (field.get('grid')):
                        rows = len(field['grid']['rows'])
                        cols = len(field['grid']['columns'])
                        print(f"  [{field['index']}] {q[:50]}... (GRID: {rows} rows x {cols} cols)")
                    else:
                        print(f"  [{field['index']}] {q[:50]}... ({t})")
                else:
                    label = field.get('label') or field.get('placeholder') or field.get('name') or f"Field {field['index']}"
                    t = field.get('type') or field.get('tag')
                    print(f"  [{field['index']}] {label[:50]} ({t})")

            if len(fields) > 10:
                print(f"  ... and {len(fields) - 10} more")

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
