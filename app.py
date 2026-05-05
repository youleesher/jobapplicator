import os
import json
import tempfile
import streamlit as st
from pypdf import PdfReader

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Job Machine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@700;800&family=DM+Sans:wght@300;400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background-color: #0a0a0a;
    color: #e8e4dc;
}
section[data-testid="stSidebar"] {
    background-color: #111111;
    border-right: 1px solid #222;
}
section[data-testid="stSidebar"] * { color: #e8e4dc !important; }
.stApp { background-color: #0a0a0a; }
h1 { font-family: 'Syne', sans-serif; font-weight: 800; font-size: 2.4rem !important; letter-spacing: -1px; color: #f0ebe0 !important; }
h2 { font-family: 'Syne', sans-serif; font-weight: 700; font-size: 1.3rem !important; color: #c8c0b0 !important; margin-top: 2rem !important; }
h3 { font-family: 'Syne', sans-serif; font-size: 1rem !important; color: #a09888 !important; }
.tag {
    display: inline-block;
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #c8a96e;
    border: 1px solid #c8a96e44;
    padding: 2px 10px;
    border-radius: 2px;
    margin-bottom: 8px;
}
.stButton > button {
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    background: #c8a96e;
    color: #0a0a0a;
    border: none;
    border-radius: 2px;
    padding: 0.5rem 1.4rem;
    font-weight: 500;
    transition: all 0.2s;
}
.stButton > button:hover { background: #dfc08a; transform: translateY(-1px); }
[data-testid="stFileUploader"] { border: 1px dashed #333 !important; border-radius: 4px; padding: 0.5rem; }
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    background: #141414 !important;
    border: 1px solid #2a2a2a !important;
    color: #e8e4dc !important;
    border-radius: 3px !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.8rem !important;
}
[data-testid="metric-container"] {
    background: #141414;
    border: 1px solid #222;
    border-radius: 4px;
    padding: 1rem 1.2rem;
}
[data-testid="metric-container"] label { color: #666 !important; font-family: 'DM Mono', monospace; font-size: 0.7rem; letter-spacing: 1px; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { color: #c8a96e !important; font-family: 'Syne', sans-serif; font-size: 1.8rem; }
.job-card {
    background: #111;
    border: 1px solid #222;
    border-radius: 4px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.job-card:hover { border-color: #333; }
.job-card-title { font-family: 'Syne', sans-serif; font-weight: 700; font-size: 1rem; color: #f0ebe0; margin-bottom: 2px; }
.job-card-company { font-family: 'DM Mono', monospace; font-size: 0.75rem; color: #c8a96e; letter-spacing: 1px; margin-bottom: 8px; }
.job-card-url { font-family: 'DM Mono', monospace; font-size: 0.7rem; color: #555; }
hr { border-color: #1e1e1e !important; margin: 2rem 0 !important; }
.stTabs [data-baseweb="tab-list"] { background: transparent; border-bottom: 1px solid #222; gap: 0; }
.stTabs [data-baseweb="tab"] {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #555;
    padding: 0.6rem 1.4rem;
    border-bottom: 2px solid transparent;
}
.stTabs [aria-selected="true"] { color: #c8a96e !important; border-bottom-color: #c8a96e !important; background: transparent !important; }
.streamlit-expanderHeader {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.75rem !important;
    letter-spacing: 1px !important;
    color: #888 !important;
    background: #111 !important;
    border: 1px solid #222 !important;
    border-radius: 3px !important;
}
</style>
""", unsafe_allow_html=True)


# ── Session state defaults ──────────────────────────────────────────────────────
def init_state():
    defaults = {
        "gemini_key": "",
        "credentials_json": None,
        "cv_text": "",
        "sheets_manager": None,
        "tailor": None,
        "setup_complete": False,
        # Personal info
        "personal_name": "",
        "personal_phone": "",
        "personal_email": "",
        "personal_linkedin": "",
        "personal_education": "",
        "personal_skills": "",
        # Profile / filtering criteria
        "profile_persona": "An early-career professional with a background in business, technology, or marketing.",
        "profile_ideal_roles": "Business analyst, strategy associate, operations associate, or marketing associate.",
        "profile_constraints": (
            "1. Role must require fewer than 3 years of experience.\n"
            "2. Must not be an internship.\n"
            "3. Must not be a pure finance, insurance, or accounting role."
        ),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ── Helpers ─────────────────────────────────────────────────────────────────────
def extract_pdf_text(uploaded_file):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name
    reader = PdfReader(tmp_path)
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    os.unlink(tmp_path)
    return text.strip()


def get_or_create_ws(spreadsheet, title, headers):
    import gspread
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers)
        return ws


def build_sheets_manager(credentials_dict, gemini_key, profile):
    from sheets_manager import SheetsManager
    return SheetsManager(
        credentials_info=credentials_dict,
        gemini_key=gemini_key,
        profile=profile,
    )


def build_tailor(cv_text, credentials_dict, gemini_key, personal_info, shortlist_sheet):
    from tailor import Tailor
    return Tailor(
        cv_text=cv_text,
        gemini_key=gemini_key,
        personal_info=personal_info,
        shortlist_sheet=shortlist_sheet,
    )


def get_profile_from_session():
    return {
        "persona": st.session_state.profile_persona,
        "ideal_roles": st.session_state.profile_ideal_roles,
        "hard_constraints": st.session_state.profile_constraints,
    }


def get_personal_info_from_session():
    return {
        "name": st.session_state.personal_name,
        "phone": st.session_state.personal_phone,
        "email": st.session_state.personal_email,
        "linkedin": st.session_state.personal_linkedin,
        "education": st.session_state.personal_education,
        "skills": st.session_state.personal_skills,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — Credentials + CV upload
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="tag">Setup</div>', unsafe_allow_html=True)
    st.markdown("# Job Machine")
    st.markdown("<p style='color:#555;font-size:0.8rem;font-family:DM Mono,monospace;'>Automated job processing + CV tailoring</p>", unsafe_allow_html=True)
    st.markdown("---")

    gemini_key = st.text_input("Gemini API Key", type="password", placeholder="AIza...", value=st.session_state.gemini_key)
    creds_file = st.file_uploader("Google Service Account JSON", type=["json"])
    cv_file = st.file_uploader("Master CV (PDF)", type=["pdf"])

    st.markdown("---")
    st.markdown("<p style='font-family:DM Mono,monospace;font-size:0.72rem;color:#888;letter-spacing:1px;'>PERSONAL INFO</p>", unsafe_allow_html=True)

    st.session_state.personal_name      = st.text_input("Full Name",       value=st.session_state.personal_name)
    st.session_state.personal_phone     = st.text_input("Phone",           value=st.session_state.personal_phone, placeholder="+65 9000 0000")
    st.session_state.personal_email     = st.text_input("Email",           value=st.session_state.personal_email)
    st.session_state.personal_linkedin  = st.text_input("LinkedIn URL",    value=st.session_state.personal_linkedin, placeholder="linkedin.com/in/yourprofile")
    st.session_state.personal_education = st.text_area("Education",        value=st.session_state.personal_education, placeholder="Degree, University, Year", height=80)
    st.session_state.personal_skills    = st.text_area("Technical Skills", value=st.session_state.personal_skills, placeholder="SQL, Python, GCP...", height=80)

    st.markdown("---")

    if st.button("⚡  Initialise Session"):
        errors = []
        if not gemini_key:           errors.append("Gemini API key is required.")
        if not creds_file:           errors.append("Service account JSON is required.")
        if not cv_file:              errors.append("Master CV PDF is required.")
        if not st.session_state.personal_name: errors.append("Full name is required.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            with st.spinner("Setting up your session..."):
                try:
                    credentials_dict = json.loads(creds_file.read().decode("utf-8"))
                    cv_text = extract_pdf_text(cv_file)

                    if not cv_text:
                        st.error("Could not extract text from your CV PDF. Is it a scanned image?")
                    else:
                        profile = get_profile_from_session()
                        sm = build_sheets_manager(credentials_dict, gemini_key, profile)
                        tailor = build_tailor(
                            cv_text, credentials_dict, gemini_key,
                            get_personal_info_from_session(),
                            sm.shortlist_sheet,
                        )
                        st.session_state.gemini_key = gemini_key
                        st.session_state.credentials_json = credentials_dict
                        st.session_state.cv_text = cv_text
                        st.session_state.sheets_manager = sm
                        st.session_state.tailor = tailor
                        st.session_state.setup_complete = True
                        st.success(f"Ready. Extracted {len(cv_text):,} chars from CV.")
                except Exception as ex:
                    st.error(f"Setup failed: {ex}")

    if st.session_state.setup_complete:
        st.markdown("""
        <div style='margin-top:1rem;padding:0.8rem 1rem;background:#0d1f0d;border:1px solid #1a4d1a;border-radius:3px;'>
            <span style='font-family:DM Mono,monospace;font-size:0.7rem;color:#6fcf6f;letter-spacing:1px;'>● SESSION ACTIVE</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("<p style='font-family:DM Mono,monospace;font-size:0.65rem;color:#333;line-height:1.8;'>Your credentials live only in this<br>browser session and are never stored.</p>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="tag">Job Machine</div>', unsafe_allow_html=True)
st.markdown("# Automated Job Pipeline")

if not st.session_state.setup_complete:
    st.markdown("""
    <div style='margin-top:3rem;text-align:center;padding:4rem 2rem;border:1px dashed #222;border-radius:4px;'>
        <p style='font-family:Syne,sans-serif;font-size:1.4rem;color:#333;margin-bottom:0.5rem;'>No active session</p>
        <p style='font-family:DM Mono,monospace;font-size:0.75rem;color:#444;'>Complete setup in the sidebar to begin</p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

sm = st.session_state.sheets_manager
tailor = st.session_state.tailor

tab_profile, tab_process, tab_shortlist, tab_tailor = st.tabs([
    "00 · Profile",
    "01 · Process Jobs",
    "02 · Shortlist",
    "03 · Tailor CVs",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 0 — Profile (filtering criteria)
# ══════════════════════════════════════════════════════════════════════════════
with tab_profile:
    st.markdown("## Your Candidate Profile")
    st.markdown("<p style='color:#666;font-size:0.85rem;'>This profile is used by Gemini to filter jobs in the pipeline. Edit and save to apply changes to future processing runs.</p>", unsafe_allow_html=True)

    st.markdown("---")

    new_persona = st.text_area(
        "Candidate Persona",
        value=st.session_state.profile_persona,
        height=120,
        help="Describe your background, strengths, and what makes you stand out.",
    )
    new_roles = st.text_area(
        "Ideal Roles",
        value=st.session_state.profile_ideal_roles,
        height=100,
        help="List the types of roles you are targeting.",
    )
    new_constraints = st.text_area(
        "Hard Constraints",
        value=st.session_state.profile_constraints,
        height=120,
        help="Roles that fail any of these constraints will be rejected automatically.",
    )

    st.markdown("---")

    if st.button("💾  Save Profile"):
        st.session_state.profile_persona = new_persona
        st.session_state.profile_ideal_roles = new_roles
        st.session_state.profile_constraints = new_constraints

        # Rebuild sheets_manager with updated profile so it takes effect immediately
        updated_profile = {
            "persona": new_persona,
            "ideal_roles": new_roles,
            "hard_constraints": new_constraints,
        }
        st.session_state.sheets_manager = build_sheets_manager(
            st.session_state.credentials_json,
            st.session_state.gemini_key,
            updated_profile,
        )
        sm = st.session_state.sheets_manager
        st.success("Profile saved. Future filtering runs will use these criteria.")

    st.markdown("---")
    st.markdown("<p style='font-family:DM Mono,monospace;font-size:0.7rem;color:#555;'>TIP: The more specific your persona and constraints, the fewer false positives you'll get in the Shortlist.</p>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Process Jobs
# ══════════════════════════════════════════════════════════════════════════════
with tab_process:
    st.markdown("## Process Raw Jobs")
    st.markdown("<p style='color:#666;font-size:0.85rem;'>Reads your Raw_Search sheet, cleans blurbs with Gemini, filters against your profile, and populates the Shortlisted tab.</p>", unsafe_allow_html=True)

    try:
        raw_records = sm.raw_search_sheet.get_all_records()
        cleaned_records = sm.cleaned_sheet.get_all_records()
        shortlist_records = sm.shortlist_sheet.get_all_records()
        pending_raw = sum(1 for r in raw_records if r.get("Parsed Status") != "Done")
        pending_clean = sum(1 for r in cleaned_records if r.get("Filter Status") != "Done")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Raw Jobs", len(raw_records))
        c2.metric("Pending Clean", pending_raw)
        c3.metric("Pending Filter", pending_clean)
        c4.metric("Shortlisted", len(shortlist_records))
    except Exception as e:
        st.warning(f"Could not load sheet stats: {e}")
        pending_raw, pending_clean = 1, 1

    st.markdown("---")
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        if st.button("🔍  Deduplicate Raw Sheet"):
            with st.spinner("Scanning for duplicates..."):
                sm.deduplicate_raw_search()
            st.success("Deduplication complete.")
            st.rerun()

    with col_b:
        if st.button("✨  Clean Raw Jobs"):
            if pending_raw == 0:
                st.info("Nothing pending in Raw_Search.")
            else:
                with st.spinner(f"Cleaning {pending_raw} job(s)..."):
                    sm.clean_raw_jobs()
                st.success("Cleaning complete.")
                st.rerun()

    with col_c:
        if st.button("🎯  Filter Cleaned Jobs"):
            if pending_clean == 0:
                st.info("Nothing pending in Cleaned.")
            else:
                with st.spinner(f"Evaluating {pending_clean} job(s)..."):
                    sm.filter_cleaned_jobs()
                st.success("Filtering complete.")
                st.rerun()

    st.markdown("---")
    if st.button("⚡  Run Full Pipeline"):
        with st.spinner("Running full pipeline — this may take a while..."):
            sm.deduplicate_raw_search()
            sm.clean_raw_jobs()
            sm.filter_cleaned_jobs()
        st.success("Pipeline complete! Head to the Shortlist tab.")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Shortlist
# ══════════════════════════════════════════════════════════════════════════════
with tab_shortlist:
    st.markdown("## Shortlisted Jobs")
    st.markdown("<p style='color:#666;font-size:0.85rem;'>Mark jobs as Proceed to queue them for CV tailoring. Changes save directly to your Google Sheet.</p>", unsafe_allow_html=True)

    if st.button("↻  Refresh"):
        st.rerun()

    try:
        records = sm.shortlist_sheet.get_all_records()
    except Exception as e:
        st.error(f"Could not load shortlist: {e}")
        records = []

    if not records:
        st.markdown("""
        <div style='text-align:center;padding:3rem;border:1px dashed #222;border-radius:4px;margin-top:1rem;'>
            <p style='font-family:DM Mono,monospace;font-size:0.8rem;color:#444;'>No shortlisted jobs yet — run the pipeline first.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        proceed_count = sum(1 for r in records if str(r.get("Status", "")).lower() == "proceed")
        st.markdown(f"<p style='font-family:DM Mono,monospace;font-size:0.75rem;color:#c8a96e;'>{len(records)} jobs · {proceed_count} marked Proceed</p>", unsafe_allow_html=True)
        st.markdown("---")

        for idx, row in enumerate(records, start=2):
            title   = row.get("Job Title", "Unknown Role")
            company = row.get("Company", "Unknown Company")
            url     = row.get("Job URL", "")
            status  = str(row.get("Status", "")).strip()
            jd      = row.get("Job Description", "")
            req     = row.get("Job Requirement", "")
            is_proceed = status.lower() == "proceed"

            st.markdown(f"""
            <div class="job-card" style="border-color:{'#c8a96e44' if is_proceed else '#222'};">
                <div class="job-card-title">{title}</div>
                <div class="job-card-company">{company}</div>
                <div class="job-card-url">{url}</div>
            </div>
            """, unsafe_allow_html=True)

            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                with st.expander("View JD / Requirements"):
                    st.markdown(f"**Description**\n\n{jd}")
                    st.markdown(f"**Requirements**\n\n{req}")
                    if url:
                        st.markdown(f"[Open job posting ↗]({url})")
            with col2:
                if is_proceed:
                    if st.button("✓ Marked Proceed", key=f"unproceed_{idx}"):
                        sm.shortlist_sheet.update_cell(idx, 6, "")
                        st.rerun()
                else:
                    if st.button("Mark as Proceed →", key=f"proceed_{idx}"):
                        sm.shortlist_sheet.update_cell(idx, 6, "Proceed")
                        st.rerun()
            with col3:
                if status.lower() == "tailored pdf generated":
                    st.markdown("<span style='font-family:DM Mono,monospace;font-size:0.7rem;color:#6fcf6f;'>✓ CV Generated</span>", unsafe_allow_html=True)

            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Tailor CVs
# ══════════════════════════════════════════════════════════════════════════════
with tab_tailor:
    st.markdown("## Tailor CVs")
    st.markdown("<p style='color:#666;font-size:0.85rem;'>Generates a tailored PDF for every job marked Proceed. Download each PDF then use Simplify Copilot to auto-fill the application.</p>", unsafe_allow_html=True)

    # Rebuild tailor with latest personal info from session (in case user updated sidebar)
    tailor = build_tailor(
        st.session_state.cv_text,
        st.session_state.credentials_json,
        st.session_state.gemini_key,
        get_personal_info_from_session(),
        sm.shortlist_sheet,
    )

    try:
        records = sm.shortlist_sheet.get_all_records()
        proceed_jobs = [(i + 2, r) for i, r in enumerate(records) if str(r.get("Status", "")).strip().lower() == "proceed"]
    except Exception as e:
        st.error(f"Could not load shortlist: {e}")
        proceed_jobs = []

    if not proceed_jobs:
        st.markdown("""
        <div style='text-align:center;padding:3rem;border:1px dashed #222;border-radius:4px;margin-top:1rem;'>
            <p style='font-family:DM Mono,monospace;font-size:0.8rem;color:#444;'>No jobs marked Proceed yet — head to the Shortlist tab first.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"<p style='font-family:DM Mono,monospace;font-size:0.75rem;color:#c8a96e;'>{len(proceed_jobs)} job(s) queued</p>", unsafe_allow_html=True)
        st.markdown("---")

        for sheet_idx, row in proceed_jobs:
            title   = row.get("Job Title", "Unknown Role")
            company = row.get("Company", "Unknown Company")
            url     = row.get("Job URL", "")
            jd      = row.get("Job Description", "")
            req     = row.get("Job Requirement", "")

            st.markdown(f"""
            <div class="job-card">
                <div class="job-card-title">{title}</div>
                <div class="job-card-company">{company}</div>
                {f'<div class="job-card-url">{url}</div>' if url else ''}
            </div>
            """, unsafe_allow_html=True)

            col1, col2 = st.columns([1, 2])
            with col1:
                if st.button("Generate CV →", key=f"tailor_{sheet_idx}"):
                    with st.spinner(f"Tailoring CV for {company}..."):
                        tailored_json = tailor.craft_application(title, company, jd, req)
                    if isinstance(tailored_json, dict):
                        pdf_path = tailor.generate_pdf_resume(tailored_json, company, title)
                        if pdf_path and os.path.exists(pdf_path):
                            with open(pdf_path, "rb") as f:
                                st.session_state[f"pdf_{sheet_idx}"] = (f.read(), pdf_path)
                            sm.shortlist_sheet.update_cell(sheet_idx, 6, "Tailored PDF Generated")
                            st.success("CV generated!")
                            st.rerun()
                        else:
                            st.error("PDF generation failed.")
                    else:
                        st.error(f"Gemini error: {tailored_json}")

            with col2:
                pdf_data = st.session_state.get(f"pdf_{sheet_idx}")
                if pdf_data:
                    pdf_bytes, pdf_path = pdf_data
                    dl_col, link_col = st.columns(2)
                    with dl_col:
                        st.download_button(
                            label="⬇  Download PDF",
                            data=pdf_bytes,
                            file_name=os.path.basename(pdf_path),
                            mime="application/pdf",
                            key=f"dl_{sheet_idx}",
                        )
                    with link_col:
                        if url:
                            st.markdown(f"<div style='padding-top:0.5rem;'><a href='{url}' target='_blank' style='font-family:DM Mono,monospace;font-size:0.75rem;color:#c8a96e;text-decoration:none;'>Open job posting ↗</a></div>", unsafe_allow_html=True)

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        st.markdown("---")
        if st.button("⚡  Generate All CVs"):
            progress = st.progress(0)
            total = len(proceed_jobs)
            generated = 0
            for i, (sheet_idx, row) in enumerate(proceed_jobs):
                title   = row.get("Job Title", "Unknown Role")
                company = row.get("Company", "Unknown Company")
                with st.spinner(f"[{i+1}/{total}] Tailoring for {company}..."):
                    tailored_json = tailor.craft_application(title, company, row.get("Job Description",""), row.get("Job Requirement",""))
                    if isinstance(tailored_json, dict):
                        pdf_path = tailor.generate_pdf_resume(tailored_json, company, title)
                        if pdf_path and os.path.exists(pdf_path):
                            with open(pdf_path, "rb") as f:
                                st.session_state[f"pdf_{sheet_idx}"] = (f.read(), pdf_path)
                            sm.shortlist_sheet.update_cell(sheet_idx, 6, "Tailored PDF Generated")
                            generated += 1
                progress.progress((i + 1) / total)
            st.success(f"Generated {generated}/{total} CVs. Scroll up to download.")
            st.rerun()