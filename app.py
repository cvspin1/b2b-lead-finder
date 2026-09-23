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
st.caption("Find companies in Spain with active hiring needs, HR/recruiting contacts, and ready-to-send outreach messages")

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
# model name that can 404 without warning. gemini-2.5-flash is
# kept in the list since that's the model requested, but it's
# no longer first choice since it has been deprecated before.
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

    with st.spinner("Searching for companies and generating outreach messages..."):
        prompt = f"""
        Act as an expert in B2B Lead Generation and Recruitment in Spain, and as a
        professional cold-outreach copywriter.

        Generate as many real, distinct companies as possible — up to a maximum of
        {num_companies} — that are located or active in Spain {f'in the {city_input} area' if city_input else ''}
        and that have active hiring needs or are a strong match for the profile provided below.
        Prioritize genuine, well-known or verifiable companies over generic filler entries.
        Do not repeat the same company twice, and do not stop early if you can find more
        qualifying companies — aim to reach the requested count.

        Candidate profile / requirements:
        {cv_text if cv_text else sector_input}

        Target job role / profile the candidate is applying as: {job_role_input}

        Return ONLY a JSON array (no extra text, no markdown fences). Each element
        must be an object with exactly these fields:
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
        - "motivational_message": a short, personalized, persuasive cold-outreach
          message (a few sentences, ready to send as an email or LinkedIn message).
          It must be written in {language_select}, written from the first-person
          perspective of a candidate applying as a "{job_role_input}", and tailored
          specifically to that company (mention the company by name and why the
          candidate would be a strong fit there). Do not use placeholders like
          "[Your Name]" — write it as a ready-to-send draft.
        """

        try:
            contents = [prompt]
            if image_bytes:
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type=uploaded_file.type))

            config = types.GenerateContentConfig(response_mime_type="application/json")
            response = call_gemini_auto(client, contents, config=config)

            companies = extract_json_array(response.text)
            if not isinstance(companies, list) or not companies:
                raise ValueError("The model didn't return a valid list of companies.")

            st.success(f"Search completed successfully! Found {len(companies)} companies.")

            # Full data (used for CSV export) includes the motivational message.
            full_df = pd.DataFrame(companies)
            for col in ["company_name", "website", "email", "sector", "motivational_message"]:
                if col not in full_df.columns:
                    full_df[col] = ""
            full_df = full_df[["company_name", "website", "email", "sector", "motivational_message"]]

            # Summary table shown on screen omits the long message column.
            summary_df = full_df[["company_name", "sector", "website", "email"]].rename(columns={
                "company_name": "Company Name",
                "sector": "Sector / Industry",
                "website": "Website",
                "email": "Contact Email"
            })

            st.markdown("### Summary")
            st.dataframe(summary_df, use_container_width=True)

            col1, col2 = st.columns([1, 1])
            with col1:
                render_copy_table_button(summary_df, key="leads")
            with col2:
                st.download_button(
                    "⬇️ Download as CSV (includes messages)",
                    data=full_df.to_csv(index=False).encode("utf-8"),
                    file_name="spain_leads_with_messages.csv",
                    mime="text/csv"
                )

            st.markdown("### Outreach Messages")
            for idx, row in full_df.iterrows():
                header = row["company_name"] or f"Company {idx + 1}"
                with st.expander(f"✉️ {header}"):
                    st.markdown(f"**Sector:** {row['sector']}")
                    st.markdown(f"**Website:** {row['website']}")
                    st.markdown(f"**Email:** {row['email']}")
                    st.markdown("**Motivational Message / Cold Email:**")
                    st.text_area(
                        label="",
                        value=row["motivational_message"],
                        height=150,
                        key=f"msg_{idx}"
                    )

        except Exception as e:
            st.error(f"Error: {str(e)}")
