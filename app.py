import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from google import genai
from google.genai import types
import pypdf
from PIL import Image
import io
import json

# Page Config
st.set_page_config(
    page_title="B2B Spain Job & Lead Finder",
    page_icon="💼",
    layout="wide"
)

st.title("B2B Spain Job & Lead Finder")
st.caption("Find companies in Spain with active hiring needs and HR/recruiting contacts")

# Initialize Gemini Client using Streamlit Secrets
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error("Error loading the API key. Make sure GEMINI_API_KEY is set in Streamlit Secrets.")
    st.stop()

# Helper function to extract text from PDF
def extract_text_from_pdf(pdf_file):
    pdf_reader = pypdf.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"
    return text

# ---------------------------------------------------------
# Parses a Markdown table (the format we ask Gemini to return)
# into a pandas DataFrame, so it can be shown as a real table,
# downloaded as CSV, or copied as tab-separated values that
# paste cleanly into Excel / Google Sheets.
# ---------------------------------------------------------
def parse_markdown_table(md_text):
    lines = [l for l in md_text.split("\n") if l.strip().startswith("|")]
    if len(lines) < 2:
        return None

    def split_row(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = split_row(lines[0])
    rows = []
    for line in lines[1:]:
        cells = split_row(line)
        # Skip the "|---|---|---|" separator row
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) == len(header):
            rows.append(cells)

    if not rows:
        return None
    return pd.DataFrame(rows, columns=header)

# ---------------------------------------------------------
# Renders a one-click "Copy table" button using a small HTML/JS
# component. Copies tab-separated values so pasting into Excel
# or Google Sheets lands each field in its own column.
# ---------------------------------------------------------
def render_copy_table_button(df, key):
    tsv_text = df.to_csv(sep="\t", index=False)
    button_id = f"copyBtn_{key}"
    html_code = f"""
    <script>
    function copyTable_{key}() {{
        const text = {json.dumps(tsv_text)};
        navigator.clipboard.writeText(text).then(function() {{
            var btn = document.getElementById('{button_id}');
            btn.innerText = '✅ Copied!';
            setTimeout(function() {{ btn.innerText = '📋 Copy table'; }}, 2000);
        }});
    }}
    </script>
    <button id="{button_id}" onclick="copyTable_{key}()"
        style="padding:8px 16px;background-color:#FF4B4B;color:white;
        border:none;border-radius:6px;cursor:pointer;font-size:14px;">
        📋 Copy table
    </button>
    """
    components.html(html_code, height=50)

# ---------------------------------------------------------
# Model calling helper: tries a preferred model first, then
# automatically falls back through a list of alternatives if
# Google retires/renames a model (as happened with 1.5-flash
# and 2.5-flash). This avoids hardcoding a single model name
# that can 404 without warning.
# ---------------------------------------------------------
CANDIDATE_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

def call_gemini_auto(client, contents):
    discovered_models = []
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            # Model names from the API may be prefixed like "models/gemini-3.6-flash"
            short_name = name.split("/")[-1] if name else ""
            if short_name:
                discovered_models.append(short_name)
    except Exception:
        pass

    # Try our known-good candidates first (in order of preference),
    # keeping only ones the API actually reports as available if we
    # managed to discover any; otherwise just try them all directly.
    if discovered_models:
        ordered_models = [m for m in CANDIDATE_MODELS if m in discovered_models]
        ordered_models += [m for m in discovered_models if m not in ordered_models]
    else:
        ordered_models = CANDIDATE_MODELS

    last_err = None
    for model_name in ordered_models:
        try:
            return client.models.generate_content(
                model=model_name,
                contents=contents
            )
        except Exception as e:
            last_err = e
            continue

    raise last_err if last_err else RuntimeError("No Gemini model available.")

# Search Mode
search_mode = st.radio(
    "Select your search method:",
    ["1. Analyze CV (PDF / Image)", "2. By Sector / Domain"]
)

cv_text = ""
image_bytes = None
sector_input = ""
uploaded_file = None

if "1. Analyze CV" in search_mode:
    uploaded_file = st.file_uploader("Upload your CV (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])
    if uploaded_file:
        if uploaded_file.type == "application/pdf":
            cv_text = extract_text_from_pdf(uploaded_file)
        else:
            image_bytes = uploaded_file.read()
else:
    sector_input = st.text_input("Enter the professional Sector or Domain (e.g. Digital Marketing, Hospitality, Software)")

city_input = st.text_input("City / Province in Spain (Optional)", placeholder="e.g. Madrid, Barcelona, Valencia")

# No fixed ceiling: you choose how many. Very high numbers may get cut short
# by the model's own output-length limit rather than this app's code.
num_companies = st.number_input(
    "Number of companies",
    min_value=5,
    value=30,
    step=5,
    help="Enter any number. Extremely high values may be truncated by the model's response length limit."
)

if st.button("Search Matching Companies ✨"):
    if "1. Analyze CV" in search_mode and not uploaded_file:
        st.warning("Please upload a CV file to continue.")
        st.stop()
    elif "2. By Sector" in search_mode and not sector_input:
        st.warning("Please enter a professional sector or domain.")
        st.stop()

    with st.spinner("Searching for companies and generating contact information..."):
        prompt = f"""
        Act as an expert in B2B Lead Generation and Recruitment in Spain.

        Generate as many real, distinct companies as possible — up to a maximum of
        {num_companies} — that are located or active in Spain {f'in the {city_input} area' if city_input else ''}
        and that have active hiring needs or are a strong match for the profile provided below.
        Prioritize genuine, well-known or verifiable companies over generic filler entries.
        Do not repeat the same company twice, and do not stop early if you can find more
        qualifying companies — aim to reach the requested count.

        Profile / Requirements:
        {cv_text if cv_text else sector_input}

        For each company, return strictly the following structured fields:
        1. Company name
        2. Sector / Industry
        3. City / Location in Spain
        4. Why it's a good fit (why they would need this profile)
        5. Contact email for Recruiting / HR (or a standard estimated format, e.g. hr@company.es)
        6. Phone number or link to job openings

        Write the entire response in English.
        Format the response as a clear, well-structured Markdown table.
        """

        try:
            contents = [prompt]
            if image_bytes:
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type=uploaded_file.type))

            response = call_gemini_auto(client, contents)

            st.success("Search completed successfully!")
            st.markdown(response.text)

            # Click-to-copy: parse the Markdown table Gemini returned into a
            # real table, then offer a one-click "Copy table" button (copies
            # tab-separated values so it pastes cleanly into Excel/Sheets)
            # plus a CSV download as a backup option.
            df = parse_markdown_table(response.text)
            st.markdown("---")
            if df is not None:
                col1, col2 = st.columns([1, 1])
                with col1:
                    render_copy_table_button(df, key="leads")
                with col2:
                    st.download_button(
                        "⬇️ Download as CSV",
                        data=df.to_csv(index=False).encode("utf-8"),
                        file_name="spain_leads.csv",
                        mime="text/csv"
                    )
            else:
                # Fallback if the response wasn't a clean Markdown table
                with st.expander("📋 Copy raw results"):
                    st.code(response.text, language=None)

        except Exception as e:
            st.error(f"Error: {str(e)}")
