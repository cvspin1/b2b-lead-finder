import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from google import genai
from google.genai import types
import pypdf
from PIL import Image
from fpdf import FPDF
import io
import json
import re

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="CVSpin & B2B Lead Finder España 🇪🇸",
    page_icon="💼",
    layout="wide"
)

st.title("CVSpin & B2B Lead Finder España 🇪🇸")
st.caption("Two tools in one: build an ATS-optimized Spanish CV, or find matching companies and outreach templates in Spain.")

# =========================================================
# SHARED: API KEY & CLIENT (used by both tools)
# =========================================================
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("Error loading the API key. Make sure GEMINI_API_KEY is set in Streamlit Secrets.")
    st.stop()

# =========================================================
# SHARED HELPERS
# =========================================================

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
# and 2.5-flash previously). Shared by both tools below.
# config is optional and only used when JSON-mode output is
# needed (the Lead Finder tool).
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

# =========================================================
# CV GENERATOR (CVSpin) — helpers & prompt
# =========================================================

def clean_text_for_pdf(text):
    text = text.replace('**', '').replace('##', '').replace('#', '')
    text = text.replace('?', '-').replace('"', '').replace('•', '-')
    return text.strip()

def _render_cv_pdf(text_content, scale=1.0):
    """
    Renders the CV at a given spacing scale. scale=1.0 uses the original
    compact spacing (used to measure how tall the content naturally is).
    A scale > 1.0 stretches line heights and section gaps proportionally
    so the same content fills more vertical space, without touching any
    of the text itself.
    """
    pdf = FPDF()
    pdf.add_page()

    # Perfect margins to guarantee 1 full A4 page without crashing
    pdf.set_margins(12, 10, 12)
    pdf.set_auto_page_break(auto=False)

    # Base spacing values (same as the original design), scaled uniformly.
    line_h_header = 4.5 * scale
    line_h_bullet = 4.0 * scale
    line_h_normal = 4.2 * scale

    gap_section_before = 2.2 * scale
    gap_section_after = 0.5 * scale
    gap_bullet_after = 0.3 * scale
    gap_normal_after = 0.4 * scale
    gap_blank_line = 1.5 * scale

    lines = text_content.split('\n')
    for line in lines:
        clean_line = clean_text_for_pdf(line)
        if not clean_line:
            pdf.ln(gap_blank_line)
            continue

        try:
            safe_text = clean_line.encode('latin-1', 'replace').decode('latin-1')
        except Exception:
            safe_text = clean_line

        # Section Titles / Headers
        if line.strip().startswith('#') or (clean_line.isupper() and len(clean_line) < 40):
            pdf.ln(gap_section_before)
            pdf.set_font("Arial", 'B', size=10)
            pdf.multi_cell(0, line_h_header, safe_text)
            pdf.ln(gap_section_after)
        # Bullet points
        elif clean_line.startswith('*') or clean_line.startswith('-'):
            pdf.set_font("Arial", size=8.5)
            pdf.multi_cell(0, line_h_bullet, "  " + safe_text)
            pdf.ln(gap_bullet_after)
        # Main text / Subheaders
        else:
            pdf.set_font("Arial", size=9)
            pdf.multi_cell(0, line_h_normal, safe_text)
            pdf.ln(gap_normal_after)

    return pdf

def generate_pdf_one_page(text_content):
    """
    Two-pass render: first measure how tall the content is at the original
    compact spacing, then compute a scale factor that stretches spacing
    (line height + section/paragraph gaps) so the content naturally fills
    the whole A4 page instead of leaving blank space at the bottom.
    The text content itself is never modified.
    """
    measurement_pdf = _render_cv_pdf(text_content, scale=1.0)
    content_height = measurement_pdf.get_y() - measurement_pdf.t_margin
    usable_page_height = measurement_pdf.h - measurement_pdf.t_margin - measurement_pdf.b_margin

    if content_height > 0:
        scale = usable_page_height / content_height
    else:
        scale = 1.0

    scale = max(1.0, min(scale, 1.8))

    final_pdf = _render_cv_pdf(text_content, scale=scale)
    return bytes(final_pdf.output())

STRICT_SPANISH_ATS_PROMPT = """
YOU ARE AN EXPERT SPANISH RECRUITER AND ATS SPECIALIST.
YOUR GOAL IS TO PRODUCE A PERFECT 100% ATS-COMPLIANT CV FOR THE SPANISH JOB MARKET (MODELO ESPAÑOL).

CRITICAL FORMATTING RULES:
- START DIRECTLY WITH THE CV CONTENT. NO INTRODUCTORY TEXT, NO GREETINGS, NO EXPLANATIONS.
- THE CONTENT MUST FIT ABSOLUTELY ON ONE SINGLE A4 PAGE.
- Keep descriptions and bullet points concise so the page is fully utilized without overflowing.

SPANISH CV STRUCTURE (Modelo Español):
1. ENCABEZADO: Full Name, Target Role, City/Country, Phone, LinkedIn.
2. PERFIL PROFESIONAL: Ultra-concise high-impact summary.
3. EXPERIENCIA PROFESIONAL: Position | Company | Dates | City.
4. EDUCACIÓN: Degree | Institution.
5. COMPETENCIAS E IDIOMAS: Hard/Soft Skills, Languages (Nativo, C1, B2).
"""

# =========================================================
# B2B LEAD FINDER — constants
# =========================================================

COMPANY_PLACEHOLDER = {
    "Spanish": "[Nombre de la Empresa]",
    "English": "[Company Name]",
    "French": "[Nom de l'Entreprise]",
}

MAX_COMPANIES = 200  # Target the MAX button jumps to. The number input itself has no upper limit.

# =========================================================
# TABS: one app, two tools
# =========================================================
tab_cv, tab_leads = st.tabs(["📝 CVSpin — Generador de CV", "🔍 B2B Lead Finder"])

# =========================================================
# TAB 1: CVSpin — CV Generator
# =========================================================
with tab_cv:
    st.subheader("Generador Profesional de CV para el Mercado Español")

    cv_option = st.radio(
        "Seleccione la opción de entrada / اختار طريقة إدخال البيانات:",
        (
            "1. Ingresar datos manualmente (إدخال يدوياً)",
            "2. Subir documento / foto del CV (PDF, PNG, JPG)",
            "3. Subir captura de LinkedIn (Screenshot)",
        ),
        key="cv_option"
    )

    if "1. Ingresar datos" in cv_option:
        with st.form("cv_form_manual"):
            full_name = st.text_input("Nombre Completo", key="cv_full_name")
            job_title = st.text_input("Puesto de Trabajo Objetivo en España", key="cv_job_title")
            experience = st.text_area("Experiencia Laboral (Empresas, Fechas, Funciones)", key="cv_experience")
            education = st.text_area("Formación Académica y Certificaciones", key="cv_education")
            skills = st.text_input("Habilidades, Idiomas y Carné de Conducir", key="cv_skills")

            submitted = st.form_submit_button("Generar CV Profesional ✨")

        if submitted:
            if not full_name or not job_title:
                st.warning("Por favor, complete los campos obligatorios.")
            else:
                with st.spinner("Procesando y optimizando el CV según las normas de España..."):
                    try:
                        prompt_input = f"""
{STRICT_SPANISH_ATS_PROMPT}

USER INPUT DATA:
- Nombre: {full_name}
- Puesto Objetivo: {job_title}
- Experiencia: {experience}
- Educación: {education}
- Habilidades e Idiomas: {skills}
"""
                        response = call_gemini_auto(client, prompt_input)
                        pdf_bytes = generate_pdf_one_page(response.text)

                        st.success("¡CV 100% Optimizado para España generado con éxito!")
                        st.markdown("---")
                        st.markdown(response.text)

                        st.download_button(
                            label="📥 Descargar CV en PDF (Normas España - 1 Página)",
                            data=pdf_bytes,
                            file_name=f"CV_{full_name.replace(' ', '_')}_Espana.pdf",
                            mime="application/pdf",
                            key="cv_download_manual"
                        )
                    except Exception as e:
                        st.error(f"Ocurrió un error: {e}")

    elif "2. Subir documento" in cv_option:
        cv_uploaded_file = st.file_uploader(
            "Suba un archivo PDF o una imagen del CV (PDF, PNG, JPG, JPEG)",
            type=["pdf", "png", "jpg", "jpeg"],
            key="cv_uploader"
        )
        job_target_file = st.text_input("Puesto de Trabajo Objetivo en España (Opcional)", key="cv_job_target")

        if cv_uploaded_file is not None:
            if st.button("Extraer datos y Generar CV Optimizado ✨", key="cv_extract_btn"):
                with st.spinner("Analizando el archivo y aplicando el estándar de España..."):
                    try:
                        prompt_base = f"""
{STRICT_SPANISH_ATS_PROMPT}

Target Job Title in Spain: {job_target_file if job_target_file else 'Mismo puesto detectado o perfil profesional óptimo'}
"""

                        if cv_uploaded_file.type == "application/pdf":
                            pdf_text = extract_text_from_pdf(cv_uploaded_file)
                            full_prompt = f"{prompt_base}\n\nDocument Content:\n{pdf_text}"
                            response = call_gemini_auto(client, full_prompt)
                        else:
                            image = Image.open(cv_uploaded_file)
                            response = call_gemini_auto(client, [image, prompt_base])

                        pdf_bytes = generate_pdf_one_page(response.text)

                        st.success("¡CV 100% Optimizado para España generado con éxito!")
                        st.markdown("---")
                        st.markdown(response.text)

                        st.download_button(
                            label="📥 Descargar CV en PDF (Normas España - 1 Página)",
                            data=pdf_bytes,
                            file_name="CV_Optimizado_Espana.pdf",
                            mime="application/pdf",
                            key="cv_download_upload"
                        )
                    except Exception as e:
                        st.error(f"Ocurrió un error al procesar el archivo: {e}")

    else:
        # "3. Subir captura de LinkedIn (Screenshot)"
        linkedin_uploaded_file = st.file_uploader(
            "Suba una o varias capturas de pantalla del perfil de LinkedIn (PNG, JPG, JPEG)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="cv_linkedin_uploader"
        )
        job_target_linkedin = st.text_input(
            "Puesto de Trabajo Objetivo en España (Opcional)",
            key="cv_job_target_linkedin"
        )

        if linkedin_uploaded_file:
            if st.button("Extraer perfil de LinkedIn y Generar CV Optimizado ✨", key="cv_linkedin_extract_btn"):
                with st.spinner("Analizando la(s) captura(s) de LinkedIn y aplicando el estándar de España..."):
                    try:
                        linkedin_prompt = f"""
{STRICT_SPANISH_ATS_PROMPT}

Target Job Title in Spain: {job_target_linkedin if job_target_linkedin else 'Extraer el rol óptimo basado en el perfil de LinkedIn'}

Analyze the provided screenshot of the LinkedIn profile from A to Z. Extract all relevant details (name, headline, experiences, education, skills) and synthesize them completely into the strict Spanish ATS CV format requested above.
"""
                        # Support one or several screenshots (e.g. profile + "show more"
                        # experience/education sections) in a single request.
                        contents = [linkedin_prompt]
                        for f in linkedin_uploaded_file:
                            image = Image.open(f)
                            contents.append(image)

                        response = call_gemini_auto(client, contents)
                        pdf_bytes = generate_pdf_one_page(response.text)

                        st.success("¡CV 100% Optimizado para España generado con éxito!")
                        st.markdown("---")
                        st.markdown(response.text)

                        st.download_button(
                            label="📥 Descargar CV en PDF (Normas España - 1 Página)",
                            data=pdf_bytes,
                            file_name="CV_Optimizado_Espana_LinkedIn.pdf",
                            mime="application/pdf",
                            key="cv_download_linkedin"
                        )
                    except Exception as e:
                        st.error(f"Ocurrió un error al procesar la(s) captura(s): {e}")

# =========================================================
# TAB 2: B2B Lead Finder
# =========================================================
with tab_leads:
    st.subheader("Buscador de empresas en España con ofertas activas y contactos de selección/RRHH")

    search_mode = st.radio(
        "Select your search method:",
        ["1. Analyze CV (PDF / Image)", "2. By Sector / Domain"],
        key="leads_search_mode"
    )

    leads_cv_text = ""
    leads_image_bytes = None
    sector_input = ""
    leads_uploaded_file = None

    if "1. Analyze CV" in search_mode:
        leads_uploaded_file = st.file_uploader("Upload your CV (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"], key="leads_uploader")
        if leads_uploaded_file:
            if leads_uploaded_file.type == "application/pdf":
                leads_cv_text = extract_text_from_pdf(leads_uploaded_file)
            else:
                leads_image_bytes = leads_uploaded_file.read()
    else:
        sector_input = st.text_input("Enter the professional Sector or Domain (e.g. Digital Marketing, Hospitality, Software)", key="leads_sector")

    job_role_input = st.text_input(
        "Target Job Role / Profile",
        placeholder="e.g., Digital Marketer, Full Stack Developer",
        key="leads_job_role"
    )

    language_select = st.selectbox(
        "Message Language",
        ["Spanish", "English", "French"],
        key="leads_language"
    )

    city_input = st.text_input("City / Province in Spain (Optional)", placeholder="e.g. Madrid, Barcelona, Valencia", key="leads_city")

    if "num_companies_input" not in st.session_state:
        st.session_state.num_companies_input = 30

    col_num, col_max = st.columns([3, 1])
    with col_num:
        st.number_input(
            "Number of companies",
            min_value=5,
            step=5,
            key="num_companies_input"
        )
    with col_max:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)

        def _set_max_companies():
            st.session_state.num_companies_input = MAX_COMPANIES

        st.button("MAX", on_click=_set_max_companies, key="leads_max_btn")

    if st.button("Search Matching Companies ✨", key="leads_search_btn"):
        if "1. Analyze CV" in search_mode and not leads_uploaded_file:
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

        # -----------------------------------------------
        # Step 1: generate the company contact list (no
        # per-company message — templates are generated
        # separately below).
        # -----------------------------------------------
        with st.spinner("Searching for companies..."):
            companies_prompt = f"""
            Act as an expert in B2B Lead Generation and Recruitment in Spain.

            Generate and return the ABSOLUTE MAXIMUM number of real, distinct,
            active companies in Spain for the given sector/profile. Maximize the
            output length and list as many valid entries as possible — treat
            {num_companies} as the ceiling you are aiming for, not a quota you can
            stop at early. Keep generating entries until you either reach
            {num_companies} companies or you run out of genuine, verifiable
            companies in Spain matching this profile — whichever comes first.
            Do not artificially shorten the list. Never repeat the same company
            twice.

            Companies must be located or active in Spain {f'in the {city_input} area' if city_input else ''}
            and have active hiring needs or be a strong match for the profile below.

            Candidate profile / requirements:
            {leads_cv_text if leads_cv_text else sector_input}

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
                if leads_image_bytes:
                    contents.append(types.Part.from_bytes(data=leads_image_bytes, mime_type=leads_uploaded_file.type))

                companies_response = call_gemini_auto(client, contents, config=json_config)
                companies = extract_json_array(companies_response.text)
                if not isinstance(companies, list) or not companies:
                    raise ValueError("The model didn't return a valid list of companies.")
            except Exception as e:
                st.error(f"Error generating the company list: {str(e)}")
                st.stop()

        # -----------------------------------------------
        # Step 2: generate 3-5 general-purpose outreach
        # templates, reusable across any company above.
        # -----------------------------------------------
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

        # -----------------------------------------------
        # Company list: summary table + copy button + CSV
        # -----------------------------------------------
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
                mime="text/csv",
                key="leads_csv_download"
            )

        # -----------------------------------------------
        # Outreach templates section (global, reusable)
        # -----------------------------------------------
        if templates:
            st.markdown("---")
            st.markdown("### 📨 Outreach Email Templates")
            st.caption(
                f"Pick any template below, replace \"{placeholder}\" with the target company's name, "
                "and send it to any company on your list."
            )
            tab_labels = [t.get("title", f"Template {i + 1}") for i, t in enumerate(templates)]
            template_tabs = st.tabs(tab_labels)
            for i, (t_tab, t) in enumerate(zip(template_tabs, templates)):
                with t_tab:
                    st.text_area(
                        label="",
                        value=t.get("message", ""),
                        height=220,
                        key=f"template_{i}"
                    )
