# ATS Resume Analyzer

An AI-powered command-line tool that scrapes a job posting URL, analyzes how well your resume matches it, and produces a detailed gap report — all scored adaptively based on the role type.

## Features

- **Two-pass AI analysis** — Pass 1 classifies the role and generates weighted, role-specific criteria; Pass 2 scores your resume against those criteria. This avoids penalizing transferable skills for pattern-heavy roles while staying strict about hard requirements for infrastructure/DevOps/cloud positions.
- **Smart job scraping** — Fetches job descriptions directly from any URL. Automatically switches to Selenium for sites that require JavaScript rendering (LinkedIn, Indeed, Glassdoor, major tech company career pages, etc.).
- **LinkedIn support** — Can log in using your existing Chrome profile to scrape gated LinkedIn job postings.
- **Groq LLM backend** — Uses the Groq API (default model: `llama-3.3-70b-versatile`) for fast, free-tier-friendly inference.
- **Detailed terminal output** — Color-coded scoring, severity icons, and a score bar for quick visual feedback.
- **JSON report export** — Optionally save the full analysis to a `.json` file for further processing.

## How It Works

```
Job Posting URL
      │
            ▼
             Scrape JD text (requests or Selenium)
                   │
                         ▼
                          Pass 1 — Classify role type + generate weighted criteria
                                │
                                      ▼
                                       Pass 2 — Score resume against weighted criteria
                                             │
                                                   ▼
                                                    Print color-coded gap report (+ optional JSON export)
                                                    ```

                                                    ## Requirements

                                                    - Python 3.8+
                                                    - A [Groq API key](https://console.groq.com/) (free tier available)
                                                    - Chrome browser (required only for Selenium-based scraping)

                                                    ## Installation

                                                    ```bash
                                                    git clone https://github.com/IzabellGersh/ats-analyzer.git
                                                    cd ats-analyzer
                                                    pip install requests beautifulsoup4 selenium webdriver-manager
                                                    ```

                                                    ## Configuration

                                                    Copy the example config and fill in your values:

                                                    ```bash
                                                    cp config_example.ini config.ini
                                                    ```

                                                    Edit `config.ini`:

                                                    ```ini
                                                    [resume]
                                                    path = /path/to/your/resume.pdf   # or .txt, .docx

                                                    [groq]
                                                    api_key = YOUR_GROQ_API_KEY
                                                    model = llama-3.3-70b-versatile

                                                    [linkedin]
                                                    headless = true   # set to false to open a visible browser window (recommended first time)
                                                    chrome_profile =  # optional: override Chrome profile path (auto-detected if blank)
                                                    ```

                                                    > **Note:** `config.ini` is gitignored. Never commit your API key.

                                                    ## Usage

                                                    Analyze a job posting from any URL:

                                                    ```bash
                                                    python ATS_analyzer.py --url "https://jobs.greenhouse.io/company/role"
                                                    ```

                                                    Save the report to a JSON file:

                                                    ```bash
                                                    python ATS_analyzer.py --url "https://..." --output report.json
                                                    ```

                                                    Use a custom config file path:

                                                    ```bash
                                                    python ATS_analyzer.py --url "https://..." --config /path/to/config.ini
                                                    ```

                                                    ## Supported Job Sites

                                                    Direct HTTP scraping works on most job boards. Selenium is automatically used for:

                                                    | Site | Method |
                                                    |------|--------|
                                                    | LinkedIn | Selenium + Chrome profile login |
                                                    | Indeed, Glassdoor | Selenium |
                                                    | Tesla, Apple, Amazon, Google, Microsoft, Meta, Nvidia, Uber, Airbnb, Stripe, Coinbase, SpaceX | Selenium |
                                                    | All other URLs | Direct HTTP (requests) |

                                                    ## Output

                                                    The terminal report includes:

                                                    - **Overall match score** with a visual score bar
                                                    - **Per-criterion breakdown** with pass/fail/partial status and severity icons
                                                    - **Gap highlights** — what's missing or needs strengthening
                                                    - **Role classification** — the role type detected from the JD

                                                    Example snippet:
                                                    ```
                                                    Role Type : Data Engineering / Fintech
                                                    Overall Score : 74 / 100  [███████░░░]

                                                      ✅  Python & SQL experience           (weight: high)
                                                        ✅  Data pipeline / ETL               (weight: high)
                                                          ⚠️  Financial data / reconciliation   (weight: medium) — not explicitly mentioned
                                                            ❌  dbt (data build tool)             (weight: medium) — not found
                                                            ```

                                                            ## Project Structure

                                                            ```
                                                            ats-analyzer/
                                                            ├── ATS_analyzer.py      # Main script
                                                            ├── config_example.ini   # Configuration template
                                                            ├── config.ini           # Your local config (gitignored)
                                                            └── .gitignore
                                                            ```

                                                            ## License

                                                            MIT
