import os
import json
import tempfile
from pypdf import PdfReader
from google import genai
from google.genai import types

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.platypus.flowables import KeepTogether


class Tailor:
    """
    Generic CV tailoring agent.
    All personal info and profile criteria are passed in at runtime —
    nothing is hardcoded here.
    """

    def __init__(self, cv_text, gemini_key, personal_info, shortlist_sheet):
        """
        Args:
            cv_text       (str):  Extracted text from the user's master CV PDF.
            gemini_key    (str):  Gemini API key.
            personal_info (dict): Keys — name, phone, email, linkedin, education, skills.
            shortlist_sheet:      gspread Worksheet object for the Shortlisted tab.
        """
        self.cv_text = cv_text
        self.client = genai.Client(api_key=gemini_key)
        self.personal_info = personal_info
        self.shortlist_sheet = shortlist_sheet

    # ------------------------------------------------------------------
    # AI: Craft tailored application content
    # ------------------------------------------------------------------

    def craft_application(self, title, company, jd, requirements):
        prompt = f"""
You are 'The Tailor', an expert career strategist.
The candidate has been approved to apply for this role.

Job Title: {title}
Company: {company}
Job Description: {jd}
Requirements: {requirements}

Candidate's Master CV:
{self.cv_text}

TASK:
Generate a tailored Professional Summary and rephrase the most relevant experiences
specifically for this JD. Content MUST be optimised for ATS systems.

CRITICAL CONSTRAINTS:
- Select MAXIMUM 3 of the most relevant experiences. Drop the rest.
- Include exact dates/duration from the Master CV in the 'role_company' field.
- Do not use superfluous or exaggerated language.
- Stay strictly within the boundaries of what the candidate's actual experience supports.
- Do NOT fabricate or embellish.
- Focus on themes relevant to the JD (e.g. early career, strategy, GTM, startups, cloud, AI).

Return ONLY a valid JSON object with this structure:
{{
    "tailored_summary": "<string>",
    "rephrased_experiences": [
        {{
            "role_company": "<Role, Company | Month Year - Month Year>",
            "optimized_bullets": [
                "<bullet 1>",
                "<bullet 2>"
            ]
        }}
    ]
}}
"""
        try:
            response = self.client.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"Tailor AI error: {e}")
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # PDF: Generate tailored resume using ReportLab (pure Python, no OS deps)
    # ------------------------------------------------------------------

    def generate_pdf_resume(self, tailored_content, company, job_title="Role"):
        if isinstance(tailored_content, str):
            print("Cannot generate PDF: received an error string instead of JSON.")
            return None

        p = self.personal_info
        summary = tailored_content.get("tailored_summary", "No summary generated.")
        experiences = tailored_content.get("rephrased_experiences", [])

        def sanitize(s):
            return "".join(c for c in s if c.isalnum() or c in " -").replace(" ", "_").strip("_") or "Unknown"

        output_dir = tempfile.mkdtemp()
        filename = os.path.join(output_dir, f"{sanitize(company)}_{sanitize(job_title)}_Resume.pdf")

        # ── Styles ──────────────────────────────────────────────────────
        base = getSampleStyleSheet()

        name_style = ParagraphStyle(
            "Name",
            parent=base["Normal"],
            fontSize=18,
            fontName="Helvetica-Bold",
            spaceAfter=2,
            alignment=1,  # centre
        )
        contact_style = ParagraphStyle(
            "Contact",
            parent=base["Normal"],
            fontSize=9,
            spaceAfter=12,
            alignment=1,
        )
        section_style = ParagraphStyle(
            "Section",
            parent=base["Normal"],
            fontSize=10,
            fontName="Helvetica-Bold",
            spaceBefore=10,
            spaceAfter=4,
            textTransform="uppercase",
        )
        body_style = ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=9,
            leading=13,
            spaceAfter=6,
        )
        role_style = ParagraphStyle(
            "Role",
            parent=base["Normal"],
            fontSize=9,
            fontName="Helvetica-Bold",
            spaceBefore=6,
            spaceAfter=2,
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            parent=base["Normal"],
            fontSize=9,
            leading=13,
            leftIndent=12,
            bulletIndent=0,
            spaceAfter=2,
        )

        # ── Build story ──────────────────────────────────────────────────
        story = []

        # Header
        story.append(Paragraph(p.get("name", "").upper(), name_style))
        contact_line = " | ".join(filter(None, [
            p.get("phone", ""),
            p.get("email", ""),
            p.get("linkedin", ""),
        ]))
        story.append(Paragraph(contact_line, contact_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))

        # Summary
        story.append(Paragraph("Summary", section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
        story.append(Spacer(1, 4))
        story.append(Paragraph(summary, body_style))

        # Education
        if p.get("education"):
            story.append(Paragraph("Education", section_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
            story.append(Spacer(1, 4))
            story.append(Paragraph(p["education"], body_style))

        # Relevant Experience
        story.append(Paragraph("Relevant Experience", section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
        story.append(Spacer(1, 4))

        for exp in experiences:
            role_block = [Paragraph(exp.get("role_company", ""), role_style)]
            for bullet in exp.get("optimized_bullets", []):
                role_block.append(Paragraph(f"• {bullet}", bullet_style))
            story.append(KeepTogether(role_block))

        # Technical Skills
        if p.get("skills"):
            story.append(Paragraph("Technical Skills", section_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
            story.append(Spacer(1, 4))
            story.append(Paragraph(p["skills"], body_style))

        # ── Render ───────────────────────────────────────────────────────
        try:
            doc = SimpleDocTemplate(
                filename,
                pagesize=A4,
                leftMargin=2*cm, rightMargin=2*cm,
                topMargin=2*cm, bottomMargin=2*cm,
            )
            doc.build(story)
            print(f"PDF generated: {filename}")
            return filename
        except Exception as e:
            print(f"PDF render error: {e}")
            return None

    # ------------------------------------------------------------------
    # Pipeline: Process all Proceed jobs from the shortlist
    # ------------------------------------------------------------------

    def process_approved_jobs(self):
        print("\n--- SCANNING FOR 'PROCEED' JOBS ---")
        try:
            records = self.shortlist_sheet.get_all_records()
        except Exception as e:
            print(f"Could not read shortlist: {e}")
            return

        found = False
        for idx, row in enumerate(records, start=2):
            if str(row.get("Status", "")).strip().lower() != "proceed":
                continue

            found = True
            title   = row.get("Job Title", "Unknown Role")
            company = row.get("Company", "Unknown Company")
            jd      = row.get("Job Description", "")
            req     = row.get("Job Requirement", "")

            print(f"Tailoring CV for {title} at {company}...")
            tailored = self.craft_application(title, company, jd, req)

            if isinstance(tailored, dict):
                pdf_path = self.generate_pdf_resume(tailored, company, title)
                if pdf_path:
                    self.shortlist_sheet.update_cell(idx, 6, "Tailored PDF Generated")
                    print(f"✅ Done: {company}")

        if not found:
            print("No jobs marked Proceed.")


# ------------------------------------------------------------------
# Helper: Extract text from a PDF file path
# ------------------------------------------------------------------

def extract_cv_text(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        print(f"Extracted {len(text):,} characters from {pdf_path}.")
        return text.strip()
    except FileNotFoundError:
        print(f"Error: '{pdf_path}' not found.")
        return ""
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return ""


# Uncomment to run tailor.py standalone:
# if __name__ == "__main__":
#     import gspread
#     from google.oauth2.service_account import Credentials
#
#     SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
#     creds = Credentials.from_service_account_file("./credentials.json", scopes=SCOPES)
#     sheet_client = gspread.authorize(creds)
#     shortlist_sheet = sheet_client.open("Job_Machine").worksheet("Shortlisted")
#
#     personal_info = {
#         "name": "Your Name",
#         "phone": "+00 00000000",
#         "email": "you@email.com",
#         "linkedin": "linkedin.com/in/yourprofile",
#         "education": "Your Degree, University, Year",
#         "skills": "Your key skills here",
#     }
#
#     cv_text = extract_cv_text("Master_CV.pdf")
#     if cv_text:
#         tailor = Tailor(cv_text, os.getenv("GEMINI_API_KEY"), personal_info, shortlist_sheet)
#         tailor.process_approved_jobs()
#     if cv_text:
#         tailor = Tailor(cv_text, os.getenv("GEMINI_API_KEY"), personal_info, shortlist_sheet)
#         tailor.process_approved_jobs()
