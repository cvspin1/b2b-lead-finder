import streamlit as st
from google import genai
from google.genai import types
from PIL import Image
import pypdf
import json
import re
import pandas as pd
import io

st.set_page_config(
    page_title="Spain Job & Company Matcher 🇪🇸",
    page_icon="💼",
    layout="wide"
)

st.markdown("""

""", unsafe_allow_html=True)

st.title("B2B Spain Job & Lead Finder 🇪🇸")
st.caption("Buscador de empresas en España con ofertas activas y contactos de selección/RRHH")

api_key = st.secrets.get("GEMINI_API_KEY")

def call_gemini(contents):
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in Streamlit Secrets.")

    client = genai.Client(api_key=api_key)
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    last_error = None

    config = types.GenerateContentConfig(
        response_mime_type="application/json"
    )

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"API Error: {last_error}")

def extract_json(text):
    if not text:
        raise ValueError("Response is empty.")
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1:
        first_arr = text.find("[")
        last_arr = text.rfind("]")
        if first_arr != -1 and last_arr != -1:
            return json.loads(text[first_arr:last_arr + 1])
        raise ValueError("Could not find valid JSON in response.")
    return json.loads(text[first:last + 1])

COMPANY_JOB_MATCHER_PROMPT = """
YOU ARE AN EXPERT RECRUITER AND HEADHUNTER IN THE SPANISH JOB MARKET.

Your task is to analyze the candidate's CV or specified domain/sector, and find/list real companies in Spain that actively hire, recruit, or look for profiles in this specific industry.

Return JSON adhering strictly to this structure:
{
  "companies": [
    {
      "company_name": "Nombre de la empresa en España",
      "sector": "Sector / Industria",
      "city_province": "Ciudad / Provincia",
      "open_positions": "Puestos de trabajo demandados en este sector",
      "hr_email": "email_de_contacto_o_rrhh@empresa.es",
      "phone": "+34 ...",
      "website_careers": "[https://www.empresa.es/empleo](https://www.empresa.es/empleo)"
    }
  ]
}

IMPORTANT RULES:
1. Identify real Spanish companies operating in Spain that frequently hire this profile.
2. Provide direct HR / Recruitment emails or general contact emails whenever available.
3. Include valid Spanish phone numbers (+34) and web direct links.
"""

input_mode = st.radio(
    "Seleccione el método de búsqueda:",
    ("1. Analizar CV (PDF / Imagen)", "2. Por Sector / Domaine")
)

if input_mode.startswith("1."):
    uploaded_file = st.file_uploader("Suba su CV (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])
    city_filter_1 = st.text_input("Ciudad / Provincia en España (Opcional)", placeholder="Ej: Madrid, Barcelona, Toda España")
    num_leads_1 = st.slider("Número de empresas", min_value=5, max_value=25, value=10, key="slider1")

    if uploaded_file is not None and st.button("Buscar Empresas Compatibles ✨", key="btn1"):
        if not api_key:
            st.error("Missing GEMINI_API_KEY.")
        else:
            with st.spinner("Buscando empresas en España..."):
                try:
                    loc = city_filter_1 if city_filter_1 else "Toda España"
                    prompt = f"{COMPANY_JOB_MATCHER_PROMPT}\n\nLOCATION PREFERENCE: {loc}\nNUMBER OF COMPANIES REQUIRED: {num_leads_1}\nAnalyze CV:"

                    if uploaded_file.type == "application/pdf":
                        pdf_bytes = uploaded_file.getvalue()
                        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                        raw_json = call_gemini([pdf_part, prompt])
                    else:
                        image = Image.open(uploaded_file)
                        raw_json = call_gemini([image, prompt])

                    parsed_data = extract_json(raw_json)
                    companies_list = parsed_data.get("companies", []) if isinstance(parsed_data, dict) else parsed_data

                    if companies_list:
                        st.success(f"Encontradas {len(companies_list)} empresas!")
                        df = pd.DataFrame(companies_list)
                        df.columns = ["Empresa", "Sector", "Ubicación", "Puestos Demandados", "Email RRHH/Contacto", "Teléfono", "Web / Empleo"]
                        st.dataframe(df, use_container_width=True)

                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False, sheet_name='Empresas_Espana')
                        excel_data = buffer.getvalue()

                        st.download_button(
                            label="📊 Descargar Excel (.xlsx)",
                            data=excel_data,
                            file_name="Empresas_Reclutamiento_Espana.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                except Exception as e:
                    st.error(f"Error: {e}")

else:
    domain_input = st.text_input("Sector / Domaine", placeholder="Ej: Hostelería, Desarrollo Web, Logística...")
    city_filter_2 = st.text_input("Ciudad / Provincia en España (Opcional)", placeholder="Ej: Madrid, Barcelona, Toda España")
    num_leads_2 = st.slider("Número de empresas", min_value=5, max_value=25, value=10, key="slider2")

    if st.button("Buscar Empresas en el Sector ✨", key="btn2"):
        if not domain_input:
            st.warning("Escriba un sector.")
        elif not api_key:
            st.error("Missing GEMINI_API_KEY.")
        else:
            with st.spinner("Buscando empresas..."):
                try:
                    loc = city_filter_2 if city_filter_2 else "Toda España"
                    prompt = f"{COMPANY_JOB_MATCHER_PROMPT}\n\nTARGET SECTOR: {domain_input}\nLOCATION: {loc}\nNUMBER OF COMPANIES REQUIRED: {num_leads_2}"

                    raw_json = call_gemini(prompt)
                    parsed_data = extract_json(raw_json)
                    companies_list = parsed_data.get("companies", []) if isinstance(parsed_data, dict) else parsed_data

                    if companies_list:
                        st.success(f"Encontradas {len(companies_list)} empresas!")
                        df = pd.DataFrame(companies_list)
                        df.columns = ["Empresa", "Sector", "Ubicación", "Puestos Demandados", "Email RRHH/Contacto", "Teléfono", "Web / Empleo"]
                        st.dataframe(df, use_container_width=True)

                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False, sheet_name='Empresas_Espana')
                        excel_data = buffer.getvalue()

                        st.download_button(
                            label="📊 Descargar Excel (.xlsx)",
                            data=excel_data,
                            file_name=f"Empresas_{domain_input.replace(' ', '_')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                except Exception as e:
                    st.error(f"Error: {e}")
