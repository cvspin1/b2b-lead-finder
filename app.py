# =========================================================
# TAB 1: CVSpin — CV Generator
# =========================================================
with tab_cv:
    st.subheader("Generador Profesional de CV para el Mercado Español")

    cv_option = st.radio(
        "Seleccione la opción de entrada / اختر طريقة إدخال البيانات:",
        (
            "1. Ingresar datos manualmente (إدخال يدوياً)", 
            "2. Subir documento / foto del CV (PDF, PNG, JPG)",
            "3. Subir Screenshot de LinkedIn (منشور أو بروفايل LinkedIn 🔗)"
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
        # Option 3: LinkedIn Screenshot
        st.markdown("### 📸 Sube la captura de pantalla de tu perfil de LinkedIn")
        linkedin_screen = st.file_uploader(
            "Sube la imagen de tu perfil aquí (PNG, JPG, JPEG)",
            type=["png", "jpg", "jpeg"],
            key="linkedin_uploader"
        )
        job_target_linkedin = st.text_input("Puesto de Trabajo Objetivo en España (Opcional)", key="cv_job_target_lk")

        if linkedin_screen is not None:
            image = Image.open(linkedin_screen)
            st.image(image, caption="LinkedIn Profile Screenshot Preview", use_container_width=True)

            if st.button("Analizar LinkedIn y Generar CV Profesional ✨", key="linkedin_extract_btn"):
                with st.spinner("Analizando el perfil de LinkedIn y estructurándolo de A a Z para España..."):
                    try:
                        linkedin_prompt = f"""
{STRICT_SPANISH_ATS_PROMPT}

Target Job Title in Spain: {job_target_linkedin if job_target_linkedin else 'Extraer el rol óptimo basado en el perfil de LinkedIn'}

Analyze the provided screenshot of the LinkedIn profile from A to Z. Extract all relevant details (name, headline, experiences, education, skills) and synthesize them completely into the strict Spanish ATS CV format requested above.
"""
                        img_byte_arr = linkedin_screen.getvalue()
                        response = call_gemini_auto(
                            client,
                            [
                                linkedin_prompt,
                                types.Part.from_bytes(data=img_byte_arr, mime_type=linkedin_screen.type)
                            ]
                        )

                        pdf_bytes = generate_pdf_one_page(response.text)

                        st.success("¡CV generado y optimizado desde LinkedIn con éxito!")
                        st.markdown("---")
                        st.markdown(response.text)

                        st.download_button(
                            label="📥 Descargar CV en PDF (Normas España - 1 Página)",
                            data=pdf_bytes,
                            file_name="CV_Optimizado_LinkedIn_Espana.pdf",
                            mime="application/pdf",
                            key="cv_download_linkedin"
                        )
                    except Exception as e:
                        st.error(f"Ocurrió un error al procesar el pantallazo de LinkedIn: {e}")
