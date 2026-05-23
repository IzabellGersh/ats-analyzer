#!/usr/bin/env python3
"""
ATS Resume Analyzer v3 — Adaptive Scoring
------------------------------------------
Two-pass analysis:
  Pass 1: Claude reads the JD and classifies what type of role it is,
          then generates role-specific matching criteria with weights.
  Pass 2: Claude scores the resume against those weighted criteria.

This avoids over-penalizing transferable skills for pattern-heavy roles
(e.g. fintech data integrity) while still being strict about hard tool
requirements for infrastructure/DevOps/cloud roles.

Usage:
  python ats_analyzer_v3.py --url "https://jobs.greenhouse.io/company/role"
  python ats_analyzer_v3.py --url "https://..." --output report.json
"""

import argparse
import configparser
import os
import sys
import re
import time
import textwrap
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path

import io
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

CONFIG_FILE = Path(__file__).parent / "config.ini"

def load_config(path=None):
    p = Path(path) if path else CONFIG_FILE
    if not p.exists():
        print(f"[ERROR] config.ini not found at: {p}")
        sys.exit(1)
    cfg = configparser.ConfigParser()
    cfg.read(p)
    return cfg

def get_cfg(cfg, section, key, fallback=None):
    try:
        return cfg.get(section, key).strip()
    except (configparser.NoSectionError, configparser.NoOptionError):
        if fallback is not None:
            return fallback
        print(f"[ERROR] Missing [{section}] {key} in config.ini")
        sys.exit(1)

SELENIUM_DOMAINS = [
    "linkedin.com", "indeed.com", "glassdoor.com", "tesla.com",
    "apple.com/careers", "amazon.jobs", "google.com/careers",
    "careers.google.com", "microsoft.com/careers", "meta.com/careers",
    "nvidia.com/careers", "uber.com/careers", "airbnb.com/careers",
    "stripe.com/jobs", "coinbase.com/careers", "spacex.com/careers",
]
LINKEDIN_DOMAINS = ["linkedin.com"]

def needs_selenium(url):
    return any(d in url.lower() for d in SELENIUM_DOMAINS)

def needs_linkedin_login(url):
    return any(d in url.lower() for d in LINKEDIN_DOMAINS)

def scrape_direct(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] HTTP fetch failed: {e}")
        sys.exit(1)
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()
    main_content = (
        soup.find("main") or soup.find("article")
        or soup.find(attrs={"id": re.compile(r"job|description|content", re.I)})
        or soup.find(attrs={"class": re.compile(r"job|description|content|posting", re.I)})
    )
    text = (main_content or soup.body or soup).get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)[:6000]

def get_chrome_profile_path():
    import platform
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return str(home / "Library/Application Support/Google/Chrome")
    elif system == "Windows":
        return str(home / "AppData/Local/Google/Chrome/User Data")
    else:
        return str(home / ".config/google-chrome")

def get_driver(headless=False, use_profile=True, chrome_profile=None):
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        print("[ERROR] Run:  pip install selenium webdriver-manager")
        sys.exit(1)
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-notifications")
    if use_profile and not headless:
        import shutil, tempfile
        profile_path = chrome_profile or get_chrome_profile_path()
        if Path(profile_path).exists():
            tmp_profile = tempfile.mkdtemp(prefix="ats_chrome_")
            tmp_default = Path(tmp_profile) / "Default"
            src_default = Path(profile_path) / "Default"
            if src_default.exists():
                shutil.copytree(str(src_default), str(tmp_default), dirs_exist_ok=True)
            for f in Path(profile_path).glob("*"):
                if f.is_file():
                    shutil.copy2(str(f), tmp_profile)
            opts.add_argument(f"--user-data-dir={tmp_profile}")
            opts.add_argument("--profile-directory=Default")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def human_type(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(0.05)

def linkedin_login(driver, email, password, timeout=20):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)
    email_selectors = [(By.ID, "username"), (By.NAME, "session_key"), (By.CSS_SELECTOR, "input[type='email']")]
    email_field = None
    for by, sel in email_selectors:
        try:
            email_field = WebDriverWait(driver, 5).until(EC.presence_of_element_located((by, sel)))
            break
        except Exception:
            continue
    if not email_field:
        driver.quit(); sys.exit(1)
    driver.execute_script("arguments[0].click();", email_field)
    human_type(email_field, email)
    pass_field = None
    for by, sel in [(By.ID, "password"), (By.CSS_SELECTOR, "input[type='password']")]:
        try:
            pass_field = driver.find_element(by, sel); break
        except Exception:
            continue
    if not pass_field:
        driver.quit(); sys.exit(1)
    driver.execute_script("arguments[0].click();", pass_field)
    human_type(pass_field, password)
    time.sleep(0.8)
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        driver.execute_script("arguments[0].click();", btn)
    except Exception:
        from selenium.webdriver.common.keys import Keys
        pass_field.send_keys(Keys.RETURN)
    time.sleep(5)

def scroll_and_extract(driver, url, scroll_wait=3, timeout=20):
    from selenium.webdriver.common.by import By
    driver.get(url)
    time.sleep(2)
    for selector in ["button.jobs-description__footer-button", ".show-more-less-html__button--more"]:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, selector)
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(1)
            break
        except Exception:
            pass
    for _ in range(8):
        driver.execute_script("window.scrollBy(0, 500);")
        time.sleep(0.35)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(scroll_wait)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()
    jd_block = (
        soup.find(attrs={"class": re.compile(r"jobs-description|job-view-layout|description__text", re.I)})
        or soup.find("main") or soup.find("article")
    )
    text = (jd_block or soup.body or soup).get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)[:6000]

def scrape_with_selenium(url, cfg):
    headless = get_cfg(cfg, "linkedin", "headless", "false").lower() == "true"
    timeout = int(get_cfg(cfg, "browser", "page_load_timeout", "20"))
    scroll_wait = int(get_cfg(cfg, "browser", "scroll_wait", "3"))
    chrome_profile = get_cfg(cfg, "browser", "chrome_profile", "")
    use_profile = not headless
    driver = get_driver(headless=headless, use_profile=use_profile, chrome_profile=chrome_profile or None)
    try:
        if needs_linkedin_login(url):
            driver.get("https://www.linkedin.com/feed/")
            time.sleep(3)
            current = driver.current_url
            if not any(x in current for x in ["feed", "mynetwork", "jobs"]):
                email = get_cfg(cfg, "linkedin", "email")
                password = get_cfg(cfg, "linkedin", "password")
                linkedin_login(driver, email, password, timeout=timeout)
        text = scroll_and_extract(driver, url, scroll_wait=scroll_wait, timeout=timeout)
    finally:
        driver.quit()
    return text

def load_resume(path):
    if not os.path.exists(path):
        print(f"[ERROR] Resume not found: {path}")
        sys.exit(1)
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        try:
            import pdfplumber
        except ImportError:
            print("[ERROR] Run:  pip install pdfplumber")
            sys.exit(1)
        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return text
    if ext == "docx":
        try:
            from docx import Document
        except ImportError:
            print("[ERROR] Run:  pip install python-docx")
            sys.exit(1)
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
# PASS 1 — Role classification prompt
# Reads the JD and produces a structured rubric before scoring
# ─────────────────────────────────────────────────────────────
CLASSIFY_PROMPT = """
You are an expert job description analyst. Read the job description below and produce a
scoring rubric that will be used to evaluate a candidate's resume.

Your job is to identify and categorize every requirement in the JD into one of three tiers:

TIER 1 — HARD REQUIREMENTS (weight: high)
  Specific named tools, platforms, languages, frameworks, or certifications that are
  explicitly required. A candidate missing these is a weak match regardless of other skills.
  Examples: "Python", "GCP", "Docker", "Terraform", "Kafka", "ISO 26262", "NetSuite"
  Rules for this tier:
    - Only include things the JD explicitly names or strongly implies as required
    - Do NOT include vague phrases like "strong engineering skills"
    - Mark each as required=true or required=false based on JD language ("must have" vs "nice to have")

TIER 2 — TRANSFERABLE SKILLS (weight: medium)
  Engineering patterns, methodologies, or domain concepts that can be demonstrated
  through equivalent work in a different domain or tech stack.
  Examples: "data integrity", "distributed systems", "fault tolerance", "observability",
            "API design", "system design", "end-to-end ownership", "auditability"
  Rules for this tier:
    - These CAN be matched to synonyms, equivalent patterns, or demonstrated behaviors
    - A candidate who built idempotent pipelines satisfies "data integrity"
    - A candidate who built real-time telemetry satisfies "observability"

TIER 3 — DOMAIN / CONTEXT (weight: low-medium)
  Industry background, domain knowledge, or contextual experience the JD mentions.
  Examples: "fintech experience", "accounting systems", "defense", "automotive", "healthcare"
  Rules for this tier:
    - Domain gaps are penalized less than hard tool gaps
    - Strong transferable skills can partially compensate for domain mismatch
    - Only penalize heavily if the JD explicitly says the domain is required

Also identify the ROLE TYPE from this list:
  - backend_systems (distributed systems, APIs, data pipelines, microservices)
  - cloud_infra (GCP/AWS/Azure, Terraform, Kubernetes, DevOps)
  - data_engineering (Spark, Kafka, Airflow, warehouses, ETL)
  - embedded_systems (C/C++, RTOS, ECU, firmware)
  - ml_ai (ML frameworks, model training, research)
  - frontend (React, UI, web)
  - fullstack
  - other

=== JOB DESCRIPTION ===
{job_description}

Respond ONLY with a valid JSON object (no markdown, no extra text):
{{
  "role_type": "<one of the role types above>",
  "role_summary": "<1 sentence describing what this role actually does>",
  "tier1_hard_requirements": [
    {{"item": "<tool/language/platform>", "required": true|false, "context": "<why it matters for this role>"}}
  ],
  "tier2_transferable_skills": [
    {{"item": "<pattern/methodology/concept>", "context": "<what counts as evidence of this>"}}
  ],
  "tier3_domain_context": [
    {{"item": "<domain/industry/context>", "required": true|false, "context": "<how important is this>"}}
  ],
  "scoring_notes": "<1-2 sentences on what should matter most when scoring this specific role>"
}}
"""


# ─────────────────────────────────────────────────────────────
# PASS 2 — Adaptive scoring prompt
# Uses the rubric from Pass 1 to score the resume accurately
# ─────────────────────────────────────────────────────────────
SCORE_PROMPT = """
You are a calibrated ATS scoring engine. You have been given:
1. A structured scoring rubric derived from a job description
2. A candidate's resume

Score the resume against the rubric using the rules below.

=== SCORING RUBRIC ===
{rubric}

=== CANDIDATE RESUME ===
{resume}

=== SCORING RULES ===

TIER 1 — HARD REQUIREMENTS (each worth 15-20 points total across all items):
  - If required=true and PRESENT in resume: full credit
  - If required=true and ABSENT from resume: significant penalty
  - If required=false (nice to have) and PRESENT: small bonus
  - If required=false and ABSENT: small or no penalty
  - Match by exact name or universally accepted abbreviation ONLY
  - "Linux" does NOT satisfy "GCP". "pipelines" does NOT satisfy "Kafka".

TIER 2 — TRANSFERABLE SKILLS (each worth 5-10 points total across all items):
  - Match by meaning, demonstrated behavior, or clear equivalent
  - Quote the exact phrase from the resume that satisfies each item
  - If the resume clearly demonstrates the concept with different wording: MATCHED
  - If there is no evidence at all: MISSING

TIER 3 — DOMAIN CONTEXT (worth 10-15 points total):
  - If required=true and missing: moderate penalty (not a dealbreaker if Tier 1+2 are strong)
  - If required=false and missing: small penalty
  - Strong Tier 1+2 match can compensate for Tier 3 domain mismatch

SCORE CALIBRATION — use this scale:
  85-100%  Excellent: 90%+ of required items met directly, strong domain fit
  70-84%   Good: most requirements met, 1-2 minor gaps
  55-69%   Partial: core engineering fits but important gaps (tools or domain)
  35-54%   Weak: transferable foundation but significant hard-skill or domain gaps
  0-34%    Poor: different domain, different stack, most requirements missing

IMPORTANT: Be honest and accurate. Do not inflate. Do not over-penalize.
The score should reflect how likely a real recruiter would shortlist this candidate.

Respond ONLY with a valid JSON object (no markdown, no extra text):
{{
  "ats_score": <integer 0-100>,
  "score_rationale": "<2-3 honest sentences explaining the score, naming key matches AND key gaps>",
  "tier1_results": [
    {{"item": "<requirement>", "status": "matched|missing|partial", "found_as": "<exact quote or empty>", "required": true|false}}
  ],
  "tier2_results": [
    {{"item": "<skill>", "status": "matched|missing|partial", "found_as": "<exact quote or empty>"}}
  ],
  "tier3_results": [
    {{"item": "<domain>", "status": "matched|missing|partial", "note": "<explanation>"}}
  ],
  "skill_gaps": [
    {{"gap": "<specific gap>", "severity": "high|medium|low", "suggestion": "<actionable fix>"}}
  ],
  "strengths": ["<genuine strength with evidence>"],
  "overall_recommendation": "<honest 2-3 sentence summary: fit assessment and what the candidate should do>"
}}
"""


def call_groq(prompt, model, api_key, max_tokens=1500):
    api_key = api_key.encode("ascii", errors="ignore").decode("ascii").strip()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=payload, timeout=45
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] Groq API call failed: {e}")
        sys.exit(1)
    return resp.json()["choices"][0]["message"]["content"].strip()

def parse_json(raw):
    clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    clean = re.sub(r"\s*```$", "", clean)
    return json.loads(clean)

SEVERITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}
STATUS_ICON   = {"matched": "✅", "missing": "❌", "partial": "⚠️ "}

def clr(text, code):
    return f"\033[{code}m{text}\033[0m"

def score_bar(score, width=40):
    filled = int(score / 100 * width)
    bar = "#" * filled + "." * (width - filled)
    code = "32" if score >= 70 else ("33" if score >= 45 else "31")
    return clr(f"[{bar}]", code)

def print_results(rubric, result, job_url):
    W = 72
    score = result.get("ats_score", 0)
    print()
    print(clr("=" * W, "1"))
    print(clr("  ATS RESUME ANALYZER v3 — ADAPTIVE SCORING", "1"))
    print(clr("=" * W, "1"))
    print(f"  Job URL   : {job_url}")
    print(f"  Role type : {rubric.get('role_type', 'unknown')}")
    print(f"  Role      : {rubric.get('role_summary', '')}")
    print()
    print(clr("  ATS MATCH SCORE", "1"))
    print(f"  {score_bar(score)}  {clr(f'{score}%', '1')}")
    print()
    for line in textwrap.wrap(result.get("score_rationale", ""), width=W - 4):
        print(f"  {line}")
    print()

    # Tier 1
    t1 = result.get("tier1_results", [])
    if t1:
        print(clr("  TIER 1 — HARD REQUIREMENTS", "1"))
        for item in t1:
            icon = STATUS_ICON.get(item.get("status", "missing"), "❓")
            req  = "[required]" if item.get("required") else "[nice-to-have]"
            print(f"  {icon} {item.get('item', '')}  {clr(req, '2')}")
            if item.get("found_as"):
                print(f"       → {item['found_as']}")
        print()

    # Tier 2
    t2 = result.get("tier2_results", [])
    if t2:
        print(clr("  TIER 2 — TRANSFERABLE SKILLS", "1"))
        for item in t2:
            icon = STATUS_ICON.get(item.get("status", "missing"), "❓")
            print(f"  {icon} {item.get('item', '')}")
            if item.get("found_as"):
                print(f"       → {item['found_as']}")
        print()

    # Tier 3
    t3 = result.get("tier3_results", [])
    if t3:
        print(clr("  TIER 3 — DOMAIN FIT", "1"))
        for item in t3:
            icon = STATUS_ICON.get(item.get("status", "missing"), "❓")
            print(f"  {icon} {item.get('item', '')}")
            if item.get("note"):
                print(f"       → {item['note']}")
        print()

    # Gaps
    gaps = result.get("skill_gaps", [])
    if gaps:
        print(clr("  GAPS TO ADDRESS", "1"))
        for g in gaps:
            sev  = g.get("severity", "medium")
            icon = SEVERITY_ICON.get(sev, "⚪")
            print(f"  {icon} {clr(g['gap'], '1')}  [{sev.upper()}]")
            if g.get("suggestion"):
                for line in textwrap.wrap(f"     → {g['suggestion']}", width=W - 2):
                    print(f"  {line}")
        print()

    # Strengths
    strengths = result.get("strengths", [])
    if strengths:
        print(clr("  STRENGTHS", "32"))
        for s in strengths:
            print(f"  • {s}")
        print()

    # Recommendation
    rec = result.get("overall_recommendation", "")
    if rec:
        print(clr("  RECOMMENDATION", "1"))
        for line in textwrap.wrap(rec, width=W - 4):
            print(f"  {line}")
        print()

    print(clr("=" * W, "1"))
    print()

def save_report(rubric, result, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"rubric": rubric, "result": result}, f, indent=2)
    print(f"  [FILE]  JSON report saved -> {path}")

def main():
    parser = argparse.ArgumentParser(description="ATS Resume Analyzer v3 — Adaptive Scoring")
    parser.add_argument("--url",     required=True,              help="Job posting URL")
    parser.add_argument("--output",  default=None,               help="Save JSON report to this file")
    parser.add_argument("--headless",action="store_true",        help="Run browser invisibly")
    parser.add_argument("--config",  default=str(CONFIG_FILE),   help="Path to config.ini")
    args = parser.parse_args()

    cfg         = load_config(args.config)
    resume_path = get_cfg(cfg, "resume", "path")
    api_key     = get_cfg(cfg, "groq", "api_key")
    model       = get_cfg(cfg, "groq", "model", fallback="llama-3.3-70b-versatile")

    if args.headless:
        if not cfg.has_section("linkedin"):
            cfg.add_section("linkedin")
        cfg.set("linkedin", "headless", "true")

    # Fetch JD
    if needs_selenium(args.url):
        print(f"\n  [WEB] Browser automation required for: {args.url}")
        job_text = scrape_with_selenium(args.url, cfg)
    else:
        print(f"\n  [FETCH] Fetching job description from: {args.url}")
        job_text = scrape_direct(args.url)
        if len(job_text.strip()) < 300:
            print(f"  [WARN] Retrying with browser automation...")
            job_text = scrape_with_selenium(args.url, cfg)

    if len(job_text.strip()) < 100:
        print("[ERROR] Could not extract job description.")
        sys.exit(1)

    print(f"  [OK] Captured {len(job_text)} characters of job content.")

    # Load resume
    print(f"\n  [FILE] Loading resume: {resume_path}")
    resume_text = load_resume(resume_path)
    print(f"  [OK]  Loaded {len(resume_text)} characters from resume.")

    # Pass 1 — classify and build rubric
    print(f"\n  [AI] Pass 1/2 — Classifying role and building scoring rubric...")
    classify_prompt = CLASSIFY_PROMPT.format(job_description=job_text[:4000])
    raw_rubric = call_groq(classify_prompt, model=model, api_key=api_key, max_tokens=1200)
    try:
        rubric = parse_json(raw_rubric)
    except json.JSONDecodeError:
        print(f"[WARNING] Could not parse rubric JSON:\n{raw_rubric}")
        sys.exit(1)

    print(f"  [OK] Role type: {rubric.get('role_type')} — {rubric.get('role_summary', '')}")

    # Pass 2 — score resume against rubric
    print(f"\n  [AI] Pass 2/2 — Scoring resume against rubric...")
    score_prompt = SCORE_PROMPT.format(
        rubric=json.dumps(rubric, indent=2),
        resume=resume_text[:3000]
    )
    raw_result = call_groq(score_prompt, model=model, api_key=api_key, max_tokens=1800)
    try:
        result = parse_json(raw_result)
    except json.JSONDecodeError:
        print(f"[WARNING] Could not parse scoring JSON:\n{raw_result}")
        sys.exit(1)

    print_results(rubric, result, args.url)

    if args.output:
        save_report(rubric, result, args.output)

if __name__ == "__main__":
    main()