import os
import time
import json
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# --- CONFIGURATION ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "./credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Job_Machine")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Column indices (1-based) for each sheet
RAW_STATUS_COL = 4      # Raw_Search: "Parsed Status"
CLEANED_STATUS_COL = 6  # Cleaned: "Filter Status"

# Default profile — overridden at runtime via Streamlit or standalone usage
DEFAULT_PROFILE = {
    "persona": "An early-career professional with a background in business, technology, or marketing.",
    "ideal_roles": "Business analyst, strategy associate, operations associate, or marketing associate.",
    "hard_constraints": (
        "1. Role must require fewer than 3 years of experience.\n"
        "2. Must not be an internship.\n"
        "3. Must not be a pure finance, insurance, or accounting role."
    ),
}


class SheetsManager:
    def __init__(self, credentials_info=None, gemini_key=None, profile=None):
        """
        Args:
            credentials_info (dict | None): Service account JSON as a dict.
                If None, falls back to CREDENTIALS_PATH from env.
            gemini_key (str | None): Gemini API key.
                If None, falls back to GEMINI_API_KEY from env.
            profile (dict | None): Keys — persona, ideal_roles, hard_constraints.
                If None, uses DEFAULT_PROFILE.
        """
        self.profile = profile or DEFAULT_PROFILE

        try:
            if credentials_info:
                creds = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
            else:
                creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)

            self.client = gspread.authorize(creds)
            self.spreadsheet = self._get_or_create_spreadsheet()

            self.raw_search_sheet = self._get_or_create_worksheet(
                "Raw_Search",
                headers=["Keyword", "Job URL", "Raw Text", "Parsed Status"],
            )
            self.cleaned_sheet = self._get_or_create_worksheet(
                "Cleaned",
                headers=["Company Name", "Job Title", "Job Description", "Job Requirement", "Job URL", "Filter Status"],
            )
            self.shortlist_sheet = self._get_or_create_worksheet(
                "Shortlisted",
                headers=["Job Title", "Company", "Job URL", "Job Description", "Job Requirement", "Status"],
            )

            key = gemini_key or GEMINI_API_KEY
            if key:
                self.ai_client = genai.Client(api_key=key)
            else:
                print("Warning: No Gemini API key provided. AI processing will fail.")
                self.ai_client = None

        except FileNotFoundError:
            print(f"Error: credentials file not found at '{CREDENTIALS_PATH}'.")
            self.client = None

    # ------------------------------------------------------------------
    # SHEET HELPERS
    # ------------------------------------------------------------------

    def _get_or_create_spreadsheet(self):
        try:
            return self.client.open(SPREADSHEET_NAME)
        except gspread.SpreadsheetNotFound:
            spreadsheet = self.client.create(SPREADSHEET_NAME)
            print(f"Created new spreadsheet: {spreadsheet.url}")
            return spreadsheet

    def _get_or_create_worksheet(self, title, headers):
        try:
            return self.spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
            ws.append_row(headers)
            print(f"Created tab: {title}")
            return ws

    def append_raw_search(self, keyword, job_url, raw_text):
        if not self.client:
            return
        self.raw_search_sheet.append_row([keyword, job_url, raw_text, "Pending"])
        print(f"  Logged: {job_url}")

    # ------------------------------------------------------------------
    # AI HELPER
    # ------------------------------------------------------------------

    def _call_gemini(self, prompt, model="gemini-flash-lite-latest"):
        """Call Gemini with infinite retry on quota exhaustion."""
        while True:
            try:
                response = self.ai_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                return json.loads(response.text)
            except Exception as e:
                msg = str(e).lower()
                if any(k in msg for k in ("429", "exhausted", "quota")):
                    print("Quota exhausted — waiting 60s before retry...")
                    time.sleep(60)
                else:
                    print(f"Unexpected Gemini error: {e}")
                    return {}

    @staticmethod
    def _to_str(value):
        """Coerce any JSON value to a plain string for Sheets."""
        if isinstance(value, list):
            return "\n• ".join(str(v) for v in value)
        if isinstance(value, dict):
            return json.dumps(value)
        if value is None:
            return "N/A"
        return str(value)

    # ------------------------------------------------------------------
    # PIPELINE STEPS
    # ------------------------------------------------------------------

    def deduplicate_raw_search(self):
        print("\n--- DEDUPLICATING RAW SEARCH ---")
        all_values = self.raw_search_sheet.get_all_values()
        if len(all_values) <= 1:
            print("Sheet empty or headers-only. Skipping.")
            return

        headers, rows = all_values[0], all_values[1:]
        seen, unique, dupes = set(), [], 0

        for row in rows:
            url = row[1] if len(row) > 1 else ""
            if url and url in seen:
                dupes += 1
            else:
                unique.append(row)
                if url:
                    seen.add(url)

        if dupes:
            self.raw_search_sheet.clear()
            self.raw_search_sheet.append_row(headers)
            if unique:
                self.raw_search_sheet.append_rows(unique)
            print(f"Removed {dupes} duplicate(s).")
        else:
            print("No duplicates found.")

    def clean_raw_jobs(self):
        """Parse raw blurbs with Gemini and write structured rows to Cleaned tab."""
        print("\n--- STEP 1: CLEANING RAW JOBS ---")
        rows = self.raw_search_sheet.get_all_records()
        pending = [(i + 2, r) for i, r in enumerate(rows) if r.get("Parsed Status") != "Done"]

        if not pending:
            print("Nothing pending. Moving on.")
            return

        print(f"{len(pending)} job(s) to clean...")
        for sheet_idx, row in pending:
            raw_text = row.get("Raw Text", "")
            job_url = row.get("Job URL", "")
            print(f"  Cleaning row {sheet_idx}: {job_url}")

            if not raw_text:
                self.raw_search_sheet.update_cell(sheet_idx, RAW_STATUS_COL, "Done")
                continue

            prompt = f"""
Extract the following fields from the raw job description below.
Return ONLY a valid JSON object with keys: "Company_Name", "Job_Title", "Job_Description", "Job_Requirement".
All values must be plain strings (no arrays or nested objects).

Raw Text:
{raw_text}
"""
            data = self._call_gemini(prompt)
            if data:
                self.cleaned_sheet.insert_row([
                    self._to_str(data.get("Company_Name")),
                    self._to_str(data.get("Job_Title")),
                    self._to_str(data.get("Job_Description")),
                    self._to_str(data.get("Job_Requirement")),
                    job_url,
                    "Pending",
                ], index=2)
                self.raw_search_sheet.update_cell(sheet_idx, RAW_STATUS_COL, "Done")
                time.sleep(4)

    def filter_cleaned_jobs(self):
        """Evaluate each cleaned job against the user's profile and shortlist matches."""
        print("\n--- STEP 2: FILTERING CLEANED JOBS ---")
        rows = self.cleaned_sheet.get_all_records()
        pending = [(i + 2, r) for i, r in enumerate(rows) if r.get("Filter Status") != "Done"]

        if not pending:
            print("Nothing pending. Pipeline complete.")
            return

        print(f"{len(pending)} job(s) to evaluate...")
        for sheet_idx, row in pending:
            title = row.get("Job Title", "N/A")
            company = row.get("Company Name", "N/A")
            print(f"  Evaluating: {title} at {company}")

            prompt = f"""
Evaluate the job below against this candidate profile and criteria.

CANDIDATE PERSONA:
{self.profile['persona']}

IDEAL ROLES:
{self.profile['ideal_roles']}

HARD CONSTRAINTS:
{self.profile['hard_constraints']}

AMBIGUITY RULE: If the role is ambiguous but sounds like a strong fit, err on passing it (fits_criteria: true).

Job Details:
Title: {title}
Company: {company}
Description: {row.get("Job Description", "")}
Requirements: {row.get("Job Requirement", "")}

Return ONLY a valid JSON object with one key: "fits_criteria" (boolean true or false).
"""
            data = self._call_gemini(prompt)
            if data:
                if data.get("fits_criteria") is True:
                    print(f"  ✅ Match: {title} at {company}")
                    self.shortlist_sheet.insert_row([
                        self._to_str(row.get("Job Title")),
                        self._to_str(row.get("Company Name")),
                        row.get("Job URL", ""),
                        self._to_str(row.get("Job Description")),
                        self._to_str(row.get("Job Requirement")),
                        "",
                    ], index=2)
                else:
                    print(f"  ❌ Rejected: {title} at {company}")

                self.cleaned_sheet.update_cell(sheet_idx, CLEANED_STATUS_COL, "Done")
                time.sleep(4)


# Uncomment to run sheets_manager.py standalone (AI processing only, no scraping):
# if __name__ == "__main__":
#     profile = {
#         "persona": "Your background and strengths here.",
#         "ideal_roles": "Roles you are targeting.",
#         "hard_constraints": "Your hard filters (experience level, exclusions, etc.).",
#     }
#     manager = SheetsManager(profile=profile)
#     if manager.client and manager.ai_client:
#         manager.deduplicate_raw_search()
#         manager.clean_raw_jobs()
#         manager.filter_cleaned_jobs()