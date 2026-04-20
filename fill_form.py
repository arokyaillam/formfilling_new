import asyncio
import json
import random
import re
import sys
from playwright.async_api import async_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


# Sample data generators
SAMPLE_DATA = {
    "ratings_scale_10": [7, 8, 9, 8, 9, 10],
    "ratings_scale_5": [4, 4, 5, 3, 4, 5],
    "grid_ratings": ["Good", "Excellent", "Fair", "Poor"],
}


def parse_grid_options(options):
    """
    Parse grid options from aria-labels like:
    'Poor, response for Relevance of Session Topics...'
    Returns dict: {row_name: [rating_options]}
    """
    rows = {}
    for opt in options:
        label = opt.get('label', '')
        # Match pattern: "Rating, response for Row Name"
        match = re.match(r'^([^,]+),\s*response for\s*(.+)$', label)
        if match:
            rating = match.group(1)
            row_name = match.group(2).strip()
            if row_name not in rows:
                rows[row_name] = []
            rows[row_name].append({'rating': rating, 'full_label': label})
    return rows


def generate_fill_data(fields):
    """Generate sample fill data for all fields."""
    fill_data = []

    for field in fields:
        field_info = {
            "index": field["index"],
            "question": field.get("question", field.get("label", "")),
            "type": field["type"],
            "required": field.get("required", False),
        }

        if field["type"] == "grid":
            # Handle grid questions - select one rating per row using the grid structure
            if field.get("grid") and field.get("options"):
                rows = field["grid"]["rows"]
                columns = field["grid"]["columns"]
                selections = []

                for row in rows:
                    # Pick a random column (rating) for each row
                    selected_col = random.choice(columns)
                    # Build the full aria-label that matches the radio button
                    full_label = f"{selected_col}, response for {row}"
                    selections.append({
                        "row": row,
                        "selected_rating": selected_col,
                        "full_label": full_label
                    })

                field_info["value"] = selections
                field_info["display"] = f"Grid: {len(selections)} rows rated ({', '.join([s['selected_rating'] for s in selections])})"

            elif field.get("options"):
                # Fallback: parse options to get rows
                rows = parse_grid_options(field["options"])
                selections = []
                for row_name, ratings in rows.items():
                    if ratings:
                        selected = random.choice(ratings)
                        selections.append({
                            "row": row_name,
                            "selected_rating": selected['rating'],
                            "full_label": selected['full_label']
                        })
                field_info["value"] = selections
                field_info["display"] = f"Grid: {len(selections)} rows rated"

        elif field["type"] == "scale":
            # For scale, pick a random option
            if field.get("options"):
                value = random.choice(field["options"])
                field_info["value"] = value
                field_info["display"] = f"Selected: {value['label']}"

        elif field["type"] == "radio":
            if field.get("options"):
                value = random.choice(field["options"])
                field_info["value"] = value
                field_info["display"] = f"Selected: {value['label']}"

        elif field["type"] == "checkbox":
            if field.get("options"):
                num_select = min(3, len(field["options"]))
                selected = random.sample(field["options"], num_select)
                field_info["value"] = selected
                field_info["display"] = f"Selected: {', '.join([s['label'] for s in selected])}"

        elif field["type"] in ["text", "textarea"]:
            value = "Sample response"
            field_info["value"] = value
            field_info["display"] = value

        fill_data.append(field_info)

    return fill_data


async def fill_google_form(page, fields_data):
    """Fill a Google Form using Playwright."""

    for field in fields_data:
        field_type = field["type"]
        question = field["question"]
        value = field.get("value")

        print(f"\nFilling field {field['index']}: {question[:50]}...")
        print(f"  Type: {field_type}, Value: {field.get('display', value)}")

        try:
            if field_type == "grid":
                # Handle grid - click one radio per row
                if isinstance(value, list):
                    for row_selection in value:
                        if isinstance(row_selection, dict):
                            if row_selection.get("full_label"):
                                # Click by full aria-label
                                label = row_selection["full_label"]
                                radio = page.locator(f'[role="radio"][aria-label="{label}"]').first
                                if await radio.is_visible():
                                    await radio.click()
                                    print(f"  [OK] Clicked: {label[:60]}...")
                            elif row_selection.get("selected_rating"):
                                # Try to find radio by row and rating
                                row_name = row_selection.get("row", "")
                                rating = row_selection["selected_rating"]
                                # Build the full aria-label pattern
                                aria_pattern = f'{rating}, response for {row_name}'
                                radio = page.locator(f'[role="radio"][aria-label*="{row_name}"][aria-label*="{rating}"]').first
                                if await radio.is_visible():
                                    await radio.click()
                                    print(f"  [OK] Rated '{row_name[:40]}...' as {rating}")
                                else:
                                    # Try direct aria-label match
                                    radio = page.locator(f'[role="radio"][aria-label="{aria_pattern}"]').first
                                    if await radio.is_visible():
                                        await radio.click()
                                        print(f"  [OK] Rated '{row_name[:40]}...' as {rating}")
                            await asyncio.sleep(0.3)

            elif field_type == "scale":
                if isinstance(value, dict):
                    option_label = value.get("label", "")
                    radio = page.locator(f'[role="radio"][aria-label="{option_label}"]').first
                    if await radio.is_visible():
                        await radio.click()
                        print(f"  [OK] Clicked radio: {option_label}")

            elif field_type == "radio":
                if isinstance(value, dict):
                    option_label = value.get("label", "")
                    radio = page.locator(f'[role="radio"][aria-label="{option_label}"]').first
                    if await radio.is_visible():
                        await radio.click()
                        print(f"  [OK] Clicked radio: {option_label}")

            elif field_type == "checkbox":
                if isinstance(value, list):
                    for opt in value:
                        if isinstance(opt, dict):
                            option_label = opt.get("label", "")
                            checkbox = page.locator(f'[role="checkbox"][aria-label="{option_label}"]').first
                            if await checkbox.is_visible():
                                await checkbox.click()
                                print(f"  [OK] Clicked checkbox: {option_label}")
                                await asyncio.sleep(0.3)

            elif field_type == "text":
                question_container = page.locator(f'text={question}').locator("..")
                input_field = question_container.locator('input[type="text"]').first
                if await input_field.is_visible():
                    await input_field.fill(str(value))
                    print(f"  [OK] Filled text: {value}")

            elif field_type == "textarea":
                question_container = page.locator(f'text={question}').locator("..")
                textarea = question_container.locator('textarea').first
                if await textarea.is_visible():
                    await textarea.fill(str(value))
                    print(f"  [OK] Filled textarea: {value}")

            await asyncio.sleep(0.5)

        except Exception as e:
            print(f"  [WARN] Could not fill field: {e}")


async def main():
    # Load form fields
    try:
        with open("form_fields.json", "r", encoding="utf-8") as f:
            form_data = json.load(f)
    except FileNotFoundError:
        print("Error: form_fields.json not found. Run extract_form_fields.py first.")
        return

    url = form_data["url"]
    fields = form_data["fields"]
    form_type = form_data.get("form_type", "generic")

    print(f"Form URL: {url}")
    print(f"Form Type: {form_type}")
    print(f"Total Fields: {len(fields)}")
    print("\n" + "="*60)

    # Generate sample fill data
    print("\nGenerating sample fill data...")
    fill_data = generate_fill_data(fields)

    # Display what will be filled
    print("\n=== FILL PREVIEW ===")
    for field in fill_data:
        print(f"[{field['index']}] {field['question'][:40]}...")
        print(f"    -> {field.get('display', field.get('value'))}")

    # Confirm before filling
    print("\n" + "="*60)
    print("\nAuto-filling in 3 seconds... (Ctrl+C to cancel)")
    await asyncio.sleep(3)

    # Launch browser and fill
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            print(f"\nNavigating to: {url}")
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(2)

            if form_type == "google_form":
                await fill_google_form(page, fill_data)
            else:
                print("Generic form filling not yet implemented")

            print("\n" + "="*60)
            print("Form filling complete!")

            # Ask about submitting
            print("\nOptions:")
            print("  [1] Submit form automatically")
            print("  [2] Keep open for manual review")
            print("  [3] Cancel without submitting")

            # Auto-submit for now (change to input() for interactive)
            choice = "1"  # Default to auto-submit

            if choice == "1":
                print("\nSubmitting form...")
                try:
                    # Google Forms specific submit button selector
                    submit_btn = page.locator('div[role="button"][data-testid="submit-button"], .freebirdFormviewerViewNavigationSubmitButton, div[role="button"]:has(span:has-text("Submit"))').first

                    # Alternative: find by text content
                    if not await submit_btn.is_visible():
                        submit_btn = page.get_by_role("button", name="Submit").first

                    if await submit_btn.is_visible():
                        await submit_btn.click()
                        print("  [OK] Form submitted!")
                        await asyncio.sleep(5)  # Wait for submission

                        # Verify submission by checking for confirmation message
                        confirmation = await page.locator("text='Your response has been recorded'").is_visible()
                        if confirmation:
                            print("  [OK] Submission confirmed!")
                        else:
                            print("  [INFO] Form submitted (check browser for confirmation)")
                    else:
                        print("  [WARN] Submit button not visible")
                        await asyncio.sleep(30)

                except Exception as e:
                    print(f"  [ERROR] Submit failed: {e}")
                    await asyncio.sleep(30)

            elif choice == "2":
                print("\nBrowser open for manual review...")
                await asyncio.sleep(60)

            else:
                print("\nForm not submitted. Closing...")

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
