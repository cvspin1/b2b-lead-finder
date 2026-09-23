import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from google import genai
from google.genai import types
import pypdf
from PIL import Image
import io
import json
import re

# Page Config
st.set_page_config(
    page_title="B2B Spain Job & Lead Finder",
    page_icon="💼",
    layout="wide"
)

st.title("B2B Spain Job & Lead Finder")
st.caption("Find companies in Spain with active hiring needs, HR/recruiting contacts, and ready-to-send outreach templates")

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
# Model calling helper: tries a preferred model first, then
# automatically falls back through a list of alternatives if
# Google retires/renames a model (as happened with 1.5-flash
# and 2.5-flash previously). This avoids hardcoding a single
# model name that can 404 without warning.
# ---------------------------------------------------------
CANDIDATE_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

def call_gemini_auto(client, contents, config=None):
    discovered_models = []
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            short_name = name.split("/")[-1] if name else ""
            if short_name:
                discovered_models.append(short_name)
    except Exception:
        pass

    if discovered_models:
        ordered_models = [m for m in CANDIDATE_MODELS if m in discovered_models]
        ordered_models += [m for m in discovered_models if m not in ordered_models]
    else:
        ordered_models = CANDIDATE_MODELS

    last_err = None
    for model_name in ordered_models:
        try:
            kwargs = {"model": model_name, "contents": contents}
            if config is not None:
                kwargs["config"] = config
            return client.models.generate_content(**kwargs)
        except Exception as e:
            last_err = e
            continue

    raise last_err if last_err else RuntimeError("No Gemini model available.")

# ---------------------------------------------------------
# Robustly extracts a JSON array from the model's response text,
# stripping markdown code fences if present.
# ---------------------------------------------------------
def extract_json_array(text):
    if not text:
        raise ValueError("Gemini returned an empty response.")

    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    first = cleaned.find("[")
    last = cleaned.rfind("]")
    if first == -1 or last == -1:
        raise ValueError("Could not find a valid JSON array in the response.")

    return json.loads(cleaned[first:last + 1])

# ---------------------------------------------------------
# One-click "Copy table" button (HTML/JS component). Copies
# tab-separated values so it pastes cleanly into Excel/Sheets.
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

# Language-appropriate placeholder used to tell the model what to
# put in place of the company name inside the generic templates.
COMPANY_PLACEHOLDER = {
    "Spanish": "[Nombre de la Empresa]",
    "English": "[Company Name]",
    "French": "[Nom de l'Entreprise]",
}

MAX_COMPANIES = 50

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

job_role_input = st.text_input(
    "Target Job Role / Profile",
    placeholder="e.g., Digital Marketer, Full Stack Developer"
)

language_select = st.selectbox(
    "Message Language",
    ["Spanish", "English", "French"]
)

city_input = st.text_input("City / Province in Spain (Optional)", placeholder="e.g. Madrid, Barcelona, Valencia")

# Number of companies + MAX button
if "num_companies_input" not in st.session_state:
    st.session_state.num_companies_input = 30

col_num, col_max = st.columns([3, 1])
with col_num:
    st.number_input(
        "Number of companies",
        min_value=5,
        max_value=MAX_COMPANIES,
        step=5,
        key="num_companies_input"
    )
with col_max:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)

    def _set_max_companies():
        st.session_state.num_companies_input = MAX_COMPANIES

    st.button("MAX", on_click=_set_max_companies)

if st.button("Search Matching Companies ✨"):
    if "1. Analyze CV" in search_mode and not uploaded_file:
        st.warning("Please upload a CV file to continue.")
        st.stop()
    elif "2. By Sector" in search_mode and not sector_input:
        st.warning("Please enter a professional sector or domain.")
        st.stop()
    elif not job_role_input:
        st.warning("Please enter the target job role / profile.")
        st.stop()

    num_companies = st.session_state.num_companies_input
    json_config = types.GenerateContentConfig(response_mime_type="application/json")

    # -------------------------------------------------------
    # Step 1: generate the company contact list (no per-company
    # message — templates are generated separately below).
    # -------------------------------------------------------
    with st.spinner("Searching for companies..."):
        companies_prompt = f"""
        Act as an expert in B2B Lead Generation and Recruitment in Spain.

        Your task is to generate as close to {num_companies} DISTINCT, real, and
        highly verifiable companies as you possibly can — {num_companies} is a
        target you must try hard to reach, not a soft suggestion. Only return
        fewer than {num_companies} if you have genuinely exhausted every real,
        verifiable company in Spain matching this profile — do not stop early
        just because a smaller list feels "safe" or "complete enough". Maximize
        yield. Never repeat the same company twice.

        Companies must be located or active in Spain {f'in the {city_input} area' if city_input else ''}
        and have active hiring needs or be a strong match for the profile below.

        Candidate profile / requirements:
        {cv_text if cv_text else sector_input}

        Target job role / profile the candidate is applying as: {job_role_input}

        Return ONLY a JSON array (no extra text, no markdown fences). Each
        element must be an object with exactly these fields:
        - "company_name": the company's name
        - "website": the company's website URL (best available guess if unknown)
        - "email": a direct HR/Recruitment contact email. Strongly prioritize
          authentic, domain-specific addresses tied to the company's own domain
          (e.g., rrhh@company.es, talent@company.es, careers@company.com,
          hr@company.com) over generic personal email providers (gmail.com,
          hotmail.com, yahoo.com, outlook.com, etc.) — those should only ever
          appear if that is genuinely the company's known contact method.
          If no exact real address can be confirmed, fall back to the most
          likely standard format for that company's own domain (e.g.
          rrhh@[companydomain] or careers@[companydomain]) rather than a
          personal email account.
        - "sector": the company's sector / industry
        """

        try:
            contents = [companies_prompt]
            if image_bytes:
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type=uploaded_file.type))

            companies_response = call_gemini_auto(client, contents, config=json_config)
            companies = extract_json_array(companies_response.text)
            if not isinstance(companies, list) or not companies:
                raise ValueError("The model didn't return a valid list of companies.")
        except Exception as e:
            st.error(f"Error generating the company list: {str(e)}")
            st.stop()

    # -------------------------------------------------------
    # Step 2: generate 3-5 general-purpose outreach templates,
    # reusable across any company on the list above.
    # -------------------------------------------------------
    with st.spinner("Generating outreach email templates..."):
        placeholder = COMPANY_PLACEHOLDER.get(language_select, "[Company Name]")
        templates_prompt = f"""
        Act as an expert cold-outreach copywriter specialized in job-search
        and recruitment outreach.

        Write 3 to 5 distinct, highly persuasive, ready-to-send outreach email
        templates in {language_select}, written in the first person from the
        perspective of a candidate applying as a "{job_role_input}".

        These templates must be GENERIC enough to reuse for ANY company on a
        list of leads — do not reference any specific real company. Instead,
        use the placeholder "{placeholder}" everywhere the company name would
        normally go.

        Vary the tone/angle across the templates (for example: direct and
        confident, warm and personable, achievement-focused, concise and
        urgent, curiosity-driven) so the user can pick whichever fits best.

        Return ONLY a JSON array (no extra text, no markdown fences) of 3 to 5
        objects, each with exactly these fields:
        - "title": a short label describing the template's tone/angle
        - "message": the full ready-to-send email text, written in {language_select},
          using "{placeholder}" as the company-name placeholder. Do not use any
          other bracketed placeholders like "[Your Name]" — write it as a
          finished, ready-to-send draft aside from the company-name placeholder.
        """

        try:
            templates_response = call_gemini_auto(client, [templates_prompt], config=json_config)
            templates = extract_json_array(templates_response.text)
            if not isinstance(templates, list) or not templates:
                raise ValueError("The model didn't return valid outreach templates.")
        except Exception as e:
            st.warning(f"Company list generated, but outreach templates could not be created: {str(e)}")
            templates = []

    st.success(f"Search completed successfully! Found {len(companies)} companies.")

    # -------------------------------------------------------
    # Outreach templates section (global, reusable for any company)
    # -------------------------------------------------------
    if templates:
        st.markdown("### 📨 Outreach Email Templates")
        st.caption(
            f"Pick any template below, replace \"{placeholder}\" with the target company's name, "
            "and send it to any company on your list."
        )
        tab_labels = [t.get("title", f"Template {i + 1}") for i, t in enumerate(templates)]
        tabs = st.tabs(tab_labels)
        for i, (tab, t) in enumerate(zip(tabs, templates)):
            with tab:
                st.text_area(
                    label="",
                    value=t.get("message", ""),
                    height=220,
                    key=f"template_{i}"
                )

    # -------------------------------------------------------
    # Company list: summary table + copy button + CSV download
    # -------------------------------------------------------
    full_df = pd.DataFrame(companies)
    for col in ["company_name", "website", "email", "sector"]:
        if col not in full_df.columns:
            full_df[col] = ""
    full_df = full_df[["company_name", "website", "email", "sector"]]

    summary_df = full_df.rename(columns={
        "company_name": "Company Name",
        "sector": "Sector / Industry",
        "website": "Website",
        "email": "Contact Email"
    })[["Company Name", "Sector / Industry", "Website", "Contact Email"]]

    st.markdown("### Summary")
    st.dataframe(summary_df, use_container_width=True)

    col1, col2 = st.columns([1, 1])
    with col1:
        render_copy_table_button(summary_df, key="leads")
    with col2:
        st.download_button(
            "⬇️ Download as CSV",
            data=full_df.to_csv(index=False).encode("utf-8"),
            file_name="spain_leads.csv",
            mime="text/csv"
        )
