import os
import json
import tempfile
from jinja2 import Template
from xhtml2pdf import pisa
from pypdf import PdfReader
from google import genai
from google.genai import types


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
            personal_info (dict): Keys — name, phone, email, linkedin, education.
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
    # PDF: Generate tailored resume
    # ------------------------------------------------------------------

    def generate_pdf_resume(self, tailored_content, company, job_title="Role"):
        if isinstance(tailored_content, str):
            print("Cannot generate PDF: received an error string instead of JSON.")
            return None

        p = self.personal_info
        summary = tailored_content.get("tailored_summary", "No summary generated.")
        experiences = tailored_content.get("rephrased_experiences", [])

        html_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @page { margin: 2cm; }
        body {
            font-family: Helvetica, Arial, sans-serif;
            color: #000000;
            font-size: 10pt;
            line-height: 1.3;
        }
        a { color: #0000EE; text-decoration: none; }
        .header { text-align: center; margin-bottom: 15px; }
        .header h1 {
            font-size: 20pt; margin: 0;
            text-transform: uppercase; letter-spacing: 1px;
        }
        .header p { font-size: 10pt; margin: 2px 0 0 0; }
        h2 {
            font-size: 12pt; text-transform: uppercase;
            border-bottom: 1px solid #000;
            margin-top: 15px; margin-bottom: 5px; padding-bottom: 2px;
        }
        .entry-header {
            font-weight: bold; font-size: 11pt;
            margin-top: 8px; margin-bottom: 2px;
        }
        p { margin: 0 0 8px 0; text-align: justify; }
        ul { margin: 0 0 10px 20px; padding: 0; }
        li { margin-bottom: 4px; text-align: justify; }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{ name }}</h1>
        <p>
            Phone: {{ phone }} |
            Email: <a href="mailto:{{ email }}">{{ email }}</a> |
            LinkedIn: <a href="https://{{ linkedin }}">{{ linkedin }}</a>
        </p>
    </div>

    <h2>Summary</h2>
    <p>{{ summary }}</p>

    <h2>Education</h2>
    <p>{{ education }}</p>

    <h2>Relevant Experience</h2>
    {% for exp in experiences %}
        <div class="entry-header">{{ exp.role_company }}</div>
        <ul>
            {% for bullet in exp.optimized_bullets %}
                <li>{{ bullet }}</li>
            {% endfor %}
        </ul>
    {% endfor %}

    {% if skills %}
    <h2>Technical Skills</h2>
    <p>{{ skills }}</p>
    {% endif %}
</body>
</html>
"""

        rendered_html = Template(html_template).render(
            name=p.get("name", ""),
            phone=p.get("phone", ""),
            email=p.get("email", ""),
            linkedin=p.get("linkedin", ""),
            education=p.get("education", ""),
            skills=p.get("skills", ""),
            summary=summary,
            experiences=experiences,
        )

        def sanitize(s):
            return "".join(c for c in s if c.isalnum() or c in " -").replace(" ", "_").strip("_") or "Unknown"

        output_dir = tempfile.mkdtemp()
        filename = os.path.join(output_dir, f"{sanitize(company)}_{sanitize(job_title)}_Resume.pdf")

        try:
            with open(filename, "w+b") as f:
                status = pisa.CreatePDF(rendered_html, dest=f)
            if not status.err:
                print(f"PDF generated: {filename}")
                return filename
            else:
                print("xhtml2pdf rendering failed.")
                return None
        except Exception as e:
            print(f"PDF write error: {e}")
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