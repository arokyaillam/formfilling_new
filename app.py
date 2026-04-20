import streamlit as st
import asyncio
import json
import pandas as pd
import random
import re
import sys
import platform

# Fix for Windows asyncio subprocess issue
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright
from browser_use import Agent, Browser
from browser_use.llm.ollama.chat import ChatOllama
from browser_use.llm.ollama.serializer import OllamaMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.llm.exceptions import ModelProviderError

# Page config
st.set_page_config(
    page_title="Auto Form Filler",
    page_icon="📝",
    layout="wide"
)

st.title("📝 Auto Form Filler")
st.markdown("Extract form fields and auto-fill with sample or Excel data")

# Session state
if 'form_data' not in st.session_state:
    st.session_state.form_data = None
if 'fill_data' not in st.session_state:
    st.session_state.fill_data = None


class CleanJSONChatOllama(ChatOllama):
    """Custom ChatOllama that strips markdown code blocks."""

    async def ainvoke(self, messages, output_format=None, **kwargs):
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
                elif completion.startswith('```'):
                    completion = re.sub(r'^```\s*', '', completion, flags=re.MULTILINE)
                    completion = re.sub(r'\s*```$', '', completion, flags=re.MULTILINE)
                completion = output_format.model_validate_json(completion)
                return ChatInvokeCompletion(completion=completion, usage=None)
        except Exception as e:
            raise ModelProviderError(message=str(e), model=self.name) from e


async def extract_form_fields(url):
    """Extract form fields using Playwright."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until='networkidle')
            await asyncio.sleep(3)

            # Scroll to load all elements
            await page.evaluate('() => { window.scrollTo(0, document.body.scrollHeight); }')
            await asyncio.sleep(2)

            # Check if Google Form
            is_google_form = await page.evaluate('''() => {
                return window.location.hostname.includes('docs.google.com') ||
                       document.querySelector('.freebirdFormviewerViewFormContent') !== null;
            }''')

            if is_google_form:
                fields = await page.evaluate('''() => {
                    const fields = [];
                    let fieldIndex = 0;
                    const questionContainers = document.querySelectorAll('[role="listitem"]');

                    questionContainers.forEach((container) => {
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

                        // Detect field type
                        const allRadiosInContainer = container.querySelectorAll('[role="radio"]');
                        const hasGridPattern = Array.from(allRadiosInContainer).some(r => {
                            const label = r.getAttribute('aria-label') || '';
                            return label.includes('response for');
                        });

                        if (hasGridPattern && allRadiosInContainer.length >= 4) {
                            field.type = 'grid';
                            const rows = new Set();
                            const columns = new Set();
                            const allOptions = [];

                            allRadiosInContainer.forEach(radio => {
                                const label = radio.getAttribute('aria-label');
                                if (label) {
                                    allOptions.push({ value: label, label: label });
                                    const match = label.match(/^([^,]+),\\s*response for\\s*(.+)$/);
                                    if (match) {
                                        columns.add(match[1].trim());
                                        rows.add(match[2].trim());
                                    }
                                }
                            });

                            field.grid = { columns: Array.from(columns), rows: Array.from(rows) };
                            field.options = allOptions;

                        } else {
                            const radioGroup = container.querySelectorAll('[role="radio"]');
                            const checkboxes = container.querySelectorAll('[role="checkbox"]');
                            const textInput = container.querySelector('input[type="text"], textarea');

                            if (checkboxes.length > 0) {
                                field.type = 'checkbox';
                                field.options = Array.from(checkboxes).map(cb => ({
                                    value: cb.getAttribute('aria-label'),
                                    label: cb.getAttribute('aria-label')
                                }));
                            } else if (radioGroup.length > 0) {
                                const hasNumbers = Array.from(radioGroup).some(r => {
                                    const label = r.getAttribute('aria-label') || '';
                                    return /^\\d+$/.test(label);
                                });
                                field.type = hasNumbers ? 'scale' : 'radio';
                                field.options = Array.from(radioGroup).map(r => ({
                                    value: r.getAttribute('aria-label'),
                                    label: r.getAttribute('aria-label')
                                }));
                            } else if (textInput) {
                                field.type = textInput.tagName === 'TEXTAREA' ? 'textarea' : 'text';
                            }
                        }

                        if (field.question && field.type) {
                            fields.push(field);
                        }
                    });

                    return fields;
                }''')
            else:
                fields = await page.evaluate('''() => {
                    const fields = [];
                    const inputs = document.querySelectorAll('input:not([type="hidden"]), select, textarea');

                    inputs.forEach((input, index) => {
                        const field = {
                            index: index,
                            tag: input.tagName.toLowerCase(),
                            type: input.type || null,
                            name: input.name || null,
                            label: null,
                            required: input.required || false
                        };

                        let label = null;
                        if (input.id) {
                            const labelEl = document.querySelector(`label[for="${input.id}"]`);
                            if (labelEl) label = labelEl.textContent.trim();
                        }
                        if (!label) {
                            const parentLabel = input.closest('label');
                            if (parentLabel) label = parentLabel.textContent.trim();
                        }
                        if (!label) label = input.getAttribute('aria-label');

                        field.label = label;
                        fields.push(field);
                    });

                    return fields;
                }''')

            return {
                "url": url,
                "form_type": "google_form" if is_google_form else "generic",
                "total_fields": len(fields),
                "fields": fields
            }

        finally:
            await browser.close()


def generate_fill_data_from_excel_row(df, row_num, mappings, form_fields):
    """Generate fill data for a specific Excel row."""
    fill_data = []

    for field in form_fields:
        field_info = {
            "index": field["index"],
            "question": field.get("question", field.get("label", "")),
            "type": field["type"],
            "value": None,
            "display": ""
        }

        if field["index"] in mappings:
            excel_col = mappings[field["index"]]
            cell_value = df.iloc[row_num][excel_col]

            if field["type"] == "grid" and field.get("grid"):
                rows = field["grid"]["rows"]
                columns = field["grid"]["columns"]
                selections = []
                rating = str(cell_value).strip()
                matched_col = None
                for col in columns:
                    if col.lower() in rating.lower() or rating.lower() in col.lower():
                        matched_col = col
                        break
                if not matched_col:
                    matched_col = random.choice(columns)
                for row in rows:
                    full_label = f"{matched_col}, response for {row}"
                    selections.append({
                        "row": row,
                        "selected_rating": matched_col,
                        "full_label": full_label
                    })
                field_info["value"] = selections
                field_info["display"] = f"Grid: All rows rated '{matched_col}' (from Excel)"

            elif field["type"] == "checkbox" and field.get("options"):
                values = str(cell_value).split(',') if ',' in str(cell_value) else str(cell_value).split(';')
                selected = []
                for val in values:
                    val_clean = val.strip()
                    for opt in field["options"]:
                        if val_clean.lower() in opt["label"].lower():
                            selected.append(opt)
                            break
                field_info["value"] = selected if selected else [random.choice(field["options"])]
                field_info["display"] = f"From Excel: {cell_value}"

            elif field["type"] in ["scale", "radio"] and field.get("options"):
                cell_str = str(cell_value).strip()
                matched_option = None
                for opt in field["options"]:
                    if cell_str.lower() in opt["label"].lower() or opt["label"].lower() in cell_str.lower():
                        matched_option = opt
                        break
                if matched_option:
                    field_info["value"] = matched_option
                    field_info["display"] = f"From Excel: {cell_value}"
                else:
                    try:
                        num_val = int(float(cell_str))
                        for opt in field["options"]:
                            if opt["label"] == str(num_val):
                                field_info["value"] = opt
                                field_info["display"] = f"From Excel: {num_val}"
                                break
                    except:
                        field_info["value"] = random.choice(field["options"])
                        field_info["display"] = f"Random (no match for: {cell_value})"

            else:
                field_info["value"] = str(cell_value)
                field_info["display"] = str(cell_value)[:50]

        else:
            # No mapping - generate sample
            if field["type"] == "scale" and field.get("options"):
                field_info["value"] = random.choice(field["options"])
                field_info["display"] = field_info["value"]["label"]
            elif field["type"] == "radio" and field.get("options"):
                field_info["value"] = random.choice(field["options"])
                field_info["display"] = field_info["value"]["label"]
            elif field["type"] == "checkbox" and field.get("options"):
                num_select = min(3, len(field["options"]))
                field_info["value"] = random.sample(field["options"], num_select)
                field_info["display"] = "Random selection"
            elif field["type"] in ["text", "textarea"]:
                field_info["value"] = "Sample text"
                field_info["display"] = "Sample text"

        fill_data.append(field_info)

    return fill_data


def display_fill_preview(fill_data, form_fields, mappings, row_num):
    """Display preview of fill data."""
    st.success(f"Fill data generated from Excel row {row_num}!")

    preview_data = []
    for field in fill_data:
        preview_data.append({
            "Field #": field['index'],
            "Question": field['question'][:40] + "..." if len(field['question']) > 40 else field['question'],
            "Type": field['type'],
            "Source": "Excel" if field['index'] in mappings else "Auto",
            "Value": field.get('display', str(field.get('value', '')))[:40]
        })

    st.dataframe(pd.DataFrame(preview_data), use_container_width=True)

    st.subheader("📊 Mapping Summary")
    st.write(f"- **Total fields**: {len(form_fields)}")
    st.write(f"- **Mapped from Excel**: {len(mappings)}")
    st.write(f"- **Using row**: {row_num}")


def generate_sample_data(fields):
    """Generate sample fill data."""
    fill_data = []

    for field in fields:
        field_info = {
            "index": field["index"],
            "question": field.get("question", field.get("label", "")),
            "type": field["type"],
            "value": None
        }

        if field["type"] == "grid" and field.get("grid"):
            rows = field["grid"]["rows"]
            columns = field["grid"]["columns"]
            selections = []
            for row in rows:
                selected_col = random.choice(columns)
                full_label = f"{selected_col}, response for {row}"
                selections.append({
                    "row": row,
                    "selected_rating": selected_col,
                    "full_label": full_label
                })
            field_info["value"] = selections
            field_info["display"] = f"Grid: {len(selections)} rows rated"

        elif field["type"] == "scale":
            if field.get("options"):
                value = random.choice(field["options"])
                field_info["value"] = value
                field_info["display"] = value["label"]

        elif field["type"] == "radio":
            if field.get("options"):
                value = random.choice(field["options"])
                field_info["value"] = value
                field_info["display"] = value["label"]

        elif field["type"] == "checkbox":
            if field.get("options"):
                num_select = min(3, len(field["options"]))
                selected = random.sample(field["options"], num_select)
                field_info["value"] = selected
                field_info["display"] = ", ".join([s["label"] for s in selected])

        elif field["type"] in ["text", "textarea"]:
            field_info["value"] = "Sample response"
            field_info["display"] = "Sample response"

        fill_data.append(field_info)

    return fill_data


async def fill_single_form(page, fill_data, submit=False):
    """Fill a single form submission on the current page."""
    results = []

    for field in fill_data:
        field_type = field["type"]
        value = field.get("value")

        try:
            if field_type == "grid" and isinstance(value, list):
                for row_selection in value:
                    if isinstance(row_selection, dict) and row_selection.get("full_label"):
                        radio = page.locator(f'[role="radio"][aria-label="{row_selection["full_label"]}"]').first
                        if await radio.is_visible():
                            await radio.click()
                            results.append(f"✓ {row_selection['row']}: {row_selection['selected_rating']}")
                            await asyncio.sleep(0.3)

            elif field_type == "scale" and isinstance(value, dict):
                radio = page.locator(f'[role="radio"][aria-label="{value["label"]}"]').first
                if await radio.is_visible():
                    await radio.click()
                    results.append(f"✓ Scale: {value['label']}")

            elif field_type == "radio" and isinstance(value, dict):
                radio = page.locator(f'[role="radio"][aria-label="{value["label"]}"]').first
                if await radio.is_visible():
                    await radio.click()
                    results.append(f"✓ Radio: {value['label']}")

            elif field_type == "checkbox" and isinstance(value, list):
                for opt in value:
                    if isinstance(opt, dict):
                        checkbox = page.locator(f'[role="checkbox"][aria-label="{opt["label"]}"]').first
                        if await checkbox.is_visible():
                            await checkbox.click()
                            results.append(f"✓ Checkbox: {opt['label']}")
                            await asyncio.sleep(0.3)

            elif field_type in ["text", "textarea"]:
                question = field.get("question", "")
                input_field = page.locator(f'text={question}').locator("..").locator('input, textarea').first
                if await input_field.is_visible():
                    await input_field.fill(str(value))
                    results.append(f"✓ Text: {value}")

            await asyncio.sleep(0.5)

        except Exception as e:
            results.append(f"⚠ Error: {str(e)[:50]}")

    # Submit if requested
    if submit:
        try:
            submit_btn = page.locator('div[role="button"][data-testid="submit-button"]').first
            if not await submit_btn.is_visible():
                submit_btn = page.get_by_role("button", name="Submit").first

            if await submit_btn.is_visible():
                await submit_btn.click()
                results.append("✓ Form submitted!")
                await asyncio.sleep(3)
            else:
                results.append("⚠ Submit button not found")
        except Exception as e:
            results.append(f"⚠ Submit error: {str(e)[:50]}")

    return results


async def fill_form_with_data(url, fill_data, submit=False):
    """Fill form with data using Playwright (single submission)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until='networkidle')
            await asyncio.sleep(2)

            results = await fill_single_form(page, fill_data, submit)

            # Keep browser open briefly
            await asyncio.sleep(5)

        finally:
            await browser.close()

    return results


async def batch_fill_forms(url, fill_data_list, submit=False, delay_between=3, progress_callback=None):
    """Fill multiple forms in one browser session - keeps browser open and refreshes between submissions."""
    all_results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            for idx, fill_data in enumerate(fill_data_list):
                # Update progress
                if progress_callback:
                    progress_callback(idx + 1, len(fill_data_list))

                # Navigate to form (first time) or refresh (subsequent times)
                if idx == 0:
                    await page.goto(url, wait_until='networkidle')
                else:
                    # Refresh the page for next submission
                    await page.reload(wait_until='networkidle')

                await asyncio.sleep(2)

                # Fill this form
                results = await fill_single_form(page, fill_data, submit)
                all_results.append({
                    "submission": idx + 1,
                    "results": results
                })

                # Wait before next submission (if not the last one)
                if idx < len(fill_data_list) - 1:
                    await asyncio.sleep(delay_between)

            # Keep browser open briefly at the end
            await asyncio.sleep(3)

        finally:
            await browser.close()

    return all_results


# Sidebar
st.sidebar.header("Settings")
ollama_model = st.sidebar.text_input("Ollama Model", "gemma4:31b-cloud")

# Main content
tab1, tab2, tab3 = st.tabs(["1. Extract Form", "2. Preview Data", "3. Fill Form"])

with tab1:
    st.header("Step 1: Extract Form Fields")

    form_url = st.text_input(
        "Form URL",
        placeholder="https://docs.google.com/forms/d/e/.../viewform",
        help="Enter the URL of the form to extract"
    )

    if st.button("🔍 Extract Fields", type="primary", use_container_width=True):
        if not form_url:
            st.error("Please enter a form URL")
        else:
            with st.spinner("Extracting form fields..."):
                try:
                    form_data = asyncio.run(extract_form_fields(form_url))
                    st.session_state.form_data = form_data

                    st.success(f"Extracted {form_data['total_fields']} fields!")

                    # Display fields
                    for field in form_data['fields']:
                        with st.expander(f"Field {field['index']}: {field.get('question', field.get('label', 'Unknown'))[:60]}..."):
                            st.json(field)

                except Exception as e:
                    st.error(f"Extraction failed: {str(e)}")
                    st.exception(e)

with tab2:
    st.header("Step 2: Prepare Fill Data")

    if st.session_state.form_data is None:
        st.info("Please extract a form first in Step 1")
    else:
        st.write(f"Form: {st.session_state.form_data['url']}")
        st.write(f"Total fields: {st.session_state.form_data['total_fields']}")

        data_source = st.radio(
            "Data Source",
            ["Generate Sample Data", "Upload Excel File"],
            horizontal=True
        )

        if data_source == "Generate Sample Data":
            if st.button("🎲 Generate Sample Data", use_container_width=True):
                fill_data = generate_sample_data(st.session_state.form_data['fields'])
                st.session_state.fill_data = fill_data

                st.success("Sample data generated!")

                # Preview in table
                preview_data = []
                for field in fill_data:
                    preview_data.append({
                        "Field #": field['index'],
                        "Question": field['question'][:50] + "..." if len(field['question']) > 50 else field['question'],
                        "Type": field['type'],
                        "Value": field.get('display', field.get('value', ''))[:50]
                    })

                st.dataframe(pd.DataFrame(preview_data), use_container_width=True)

        else:
            uploaded_file = st.file_uploader("Upload Excel file", type=['xlsx', 'xls', 'csv'])

            if uploaded_file:
                try:
                    if uploaded_file.name.endswith('.csv'):
                        df = pd.read_csv(uploaded_file)
                    else:
                        df = pd.read_excel(uploaded_file)

                    st.success(f"Loaded {len(df)} rows from Excel")
                    st.dataframe(df.head(), use_container_width=True)

                    # Column Mapping Section
                    st.subheader("📋 Map Columns to Form Fields")

                    # Store Excel data in session state
                    st.session_state.excel_data = df

                    # Create mapping interface
                    st.markdown("Match Excel columns to form fields:")

                    mappings = {}
                    form_fields = st.session_state.form_data['fields']

                    # For each form field, let user select matching Excel column
                    for field in form_fields:
                        field_label = field.get('question', field.get('label', f'Field {field["index"]}'))
                        field_type = field['type']

                        col1, col2 = st.columns([3, 1])
                        with col1:
                            selected_col = st.selectbox(
                                f"{field_label[:50]}... ({field_type})",
                                options=["-- Skip --"] + list(df.columns),
                                key=f"map_{field['index']}"
                            )
                        with col2:
                            st.caption(f"Type: {field_type}")

                        if selected_col != "-- Skip --":
                            mappings[field['index']] = selected_col

                    # Select row mode
                    st.subheader("🎯 Select Data Rows")
                    row_mode = st.radio(
                        "Fill Mode",
                        ["Single Row", "Multiple Rows (Batch)"],
                        horizontal=True
                    )

                    if row_mode == "Single Row":
                        row_number = st.number_input(
                            "Which row to use for filling?",
                            min_value=0,
                            max_value=len(df)-1,
                            value=0,
                            step=1
                        )
                        st.session_state.row_range = (row_number, row_number)
                    else:
                        col1, col2 = st.columns(2)
                        with col1:
                            start_row = st.number_input("Start row", min_value=0, max_value=len(df)-1, value=0)
                        with col2:
                            end_row = st.number_input("End row", min_value=start_row, max_value=len(df)-1, value=min(len(df)-1, start_row+2))
                        st.session_state.row_range = (start_row, end_row)
                        st.info(f"Will fill {end_row - start_row + 1} submissions (rows {start_row} to {end_row})")

                    if st.button("✅ Generate Fill Data from Excel", type="primary", use_container_width=True):
                        # Store mappings for later use
                        st.session_state.excel_mappings = mappings
                        st.session_state.fill_mode = row_mode

                        # Generate for single row preview
                        if row_mode == "Single Row":
                            fill_data = generate_fill_data_from_excel_row(df, row_number, mappings, form_fields)
                            st.session_state.fill_data = fill_data
                            st.session_state.preview_row = row_number
                            display_fill_preview(fill_data, form_fields, mappings, row_number)
                        else:
                            # Show preview for first row
                            fill_data = generate_fill_data_from_excel_row(df, start_row, mappings, form_fields)
                            st.session_state.fill_data = fill_data
                            st.session_state.preview_row = start_row
                            display_fill_preview(fill_data, form_fields, mappings, start_row)
                            st.success(f"Ready to fill {end_row - start_row + 1} rows (preview shows row {start_row})")

                except Exception as e:
                    st.error(f"Failed to load Excel: {str(e)}")
                    st.exception(e)

with tab3:
    st.header("Step 3: Fill Form")

    if st.session_state.fill_data is None:
        st.info("Please prepare fill data in Step 2")
    else:
        # Check if multi-row mode
        if st.session_state.get('fill_mode') == "Multiple Rows (Batch)" and st.session_state.get('excel_data') is not None:
            start_row, end_row = st.session_state.get('row_range', (0, 0))
            total_rows = end_row - start_row + 1

            st.write(f"**Batch Mode**: Ready to fill {total_rows} submissions")
            st.write(f"Rows {start_row} to {end_row} from Excel")

            col1, col2, col3 = st.columns(3)
            with col1:
                submit_after_fill = st.checkbox("Submit after each fill", value=True)
            with col2:
                delay_between = st.number_input("Delay (seconds)", min_value=1, max_value=10, value=3)
            with col3:
                close_after = st.checkbox("Close after completion", value=False)

            if st.button("🚀 Start Batch Fill", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                log_container = st.container()

                try:
                    df = st.session_state.excel_data
                    mappings = st.session_state.excel_mappings
                    form_fields = st.session_state.form_data['fields']
                    url = st.session_state.form_data['url']

                    # Generate all fill data first
                    status_text.text("Preparing data for all submissions...")
                    fill_data_list = []
                    for row_num in range(start_row, end_row + 1):
                        row_data = generate_fill_data_from_excel_row(df, row_num, mappings, form_fields)
                        fill_data_list.append(row_data)

                    # Progress callback function
                    def update_progress(current, total):
                        progress = int((current / total) * 100)
                        progress_bar.progress(progress)
                        status_text.text(f"Filling submission {current} of {total}...")

                    # Fill all forms in one browser session
                    import functools
                    all_results = asyncio.run(batch_fill_forms(
                        url,
                        fill_data_list,
                        submit=submit_after_fill,
                        delay_between=delay_between,
                        progress_callback=update_progress
                    ))

                    progress_bar.progress(100)
                    status_text.text(f"Complete! Filled {total_rows} submissions")

                    # Display results
                    with log_container:
                        for result_data in all_results:
                            st.markdown(f"---")
                            st.markdown(f"**Submission {result_data['submission']}:**")
                            for res in result_data['results']:
                                if res.startswith("✓"):
                                    st.success(res)
                                else:
                                    st.warning(res)

                        st.markdown("---")
                        st.success(f"🎉 Batch complete! {total_rows} forms filled successfully (browser stayed open)")

                except Exception as e:
                    st.error(f"Batch fill failed: {str(e)}")
                    st.exception(e)

        else:
            # Single row mode
            st.write(f"Ready to fill {len(st.session_state.fill_data)} fields")

            col1, col2 = st.columns(2)

            with col1:
                submit_after_fill = st.checkbox("Submit form after filling", value=True)

            with col2:
                use_headless = st.checkbox("Run in background (headless)", value=False)

            if st.button("🚀 Start Auto-Fill", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                log_container = st.container()

                try:
                    status_text.text("Opening browser...")
                    progress_bar.progress(10)

                    results = asyncio.run(fill_form_with_data(
                        st.session_state.form_data['url'],
                        st.session_state.fill_data,
                        submit_after_fill
                    ))

                    progress_bar.progress(100)
                    status_text.text("Complete!")

                    with log_container:
                        for result in results:
                            if result.startswith("✓"):
                                st.success(result)
                            else:
                                st.warning(result)

                except Exception as e:
                    st.error(f"Fill failed: {str(e)}")
                    st.exception(e)


# Footer
st.markdown("---")
st.markdown("Built with Streamlit + Playwright + Ollama")
