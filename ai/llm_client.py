"""
ai/llm_client.py — TIP ESG Platform · Azure OpenAI Client
==========================================================
Sends anonymised KPI summaries to Azure OpenAI for ESG insight generation.

Data privacy rules (enforced in code, never bypassed):
  ✅ Only derived KPI values (numbers, percentages) are sent
  ✅ Company names are anonymised to "Client Company" before any API call
  ✅ No raw Excel files, no PII, no connection strings are ever sent
  ✅ Azure OpenAI enterprise DPA guarantees zero data retention

Configuration: set AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT in
.streamlit/secrets.toml or as environment variables.
If not configured, all methods return mock responses gracefully.
"""

import os, json, logging, re, time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv(
    "AZURE_OPENAI_ENDPOINT",
    "https://YOUR-RESOURCE.openai.azure.com",   # placeholder — must be overridden
)
AZURE_OPENAI_KEY    = os.getenv("AZURE_OPENAI_KEY",        "")
AZURE_OPENAI_DEPLOY = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION         = "2024-02-01"
MAX_TOKENS          = 800
TEMPERATURE         = 0.2   # low = deterministic / factual


# ─── Privacy sanitiser ───────────────────────────────────────────────────────

def _anonymise(company: str) -> str:
    """Replace company name with generic label before sending to the LLM."""
    return "Client Company"


def _build_kpi_summary(kpis: dict, company: str, year: int) -> str:
    """Convert a KPI dict to structured text. Numbers only — never raw files."""
    anon  = _anonymise(company)
    lines = [
        f"Company: {anon} | Reporting year: {year}",
        f"Production: {kpis.get('production_mt', 0):,.0f} metric T",
        f"Total Energy: {kpis.get('total_energy_gj', 0):,.0f} GJ "
        f"| Intensity: {kpis.get('energy_kpi', 0):.2f} GJ/T",
        f"CO2 Scope 1: {kpis.get('co2_scope1', 0):,.0f} T "
        f"| Scope 2: {kpis.get('co2_scope2', 0):,.0f} T",
        f"Total CO2: {kpis.get('total_co2', 0):,.0f} T "
        f"| Intensity: {kpis.get('co2_kpi', 0):.4f} T/T",
        f"Water: {kpis.get('water_m3', 0):,.0f} m3 "
        f"| Intensity: {kpis.get('water_kpi', 0):.2f} m3/T",
        f"Renewable electricity: {kpis.get('renew_elec_pct', 0):.1f}% of total",
        f"Waste recovery rate: {kpis.get('waste_recovery_pct', 0):.1f}%",
        f"YoY CO2 change: {kpis.get('yoy_co2_pct', 0):+.1f}%",
        f"YoY energy change: {kpis.get('yoy_energy_pct', 0):+.1f}%",
    ]
    if kpis.get("benchmarks"):
        lines.append("\nIndustry benchmarking position (TIP 2023 quartiles):")
        for b in kpis["benchmarks"]:
            lines.append(
                f"  {b['kpi']}: {b['position']} "
                f"(company={b['value']:.3f}, industry Q2={b['median']:.3f})"
            )
    return "\n".join(lines)


# ─── Prompt templates ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an ESG analyst assistant for dss+, a sustainability consulting firm.
You analyse KPI data from tire manufacturers participating in the WBCSD Tire Industry Project.
Your role is to generate factual, concise insights from KPI summaries.

Rules:
- Base insights ONLY on the KPI numbers provided. Never invent data.
- Write in clear, professional English suitable for a consulting report.
- Always note that insights require analyst review before publication.
- Do NOT speculate about causes unless explicitly asked.
- Keep responses to 2-4 short paragraphs maximum.
"""

INSIGHT_PROMPT = """Based on the following ESG KPI summary, provide:
1. A 2-sentence performance headline (strengths and gaps)
2. Key year-on-year observations
3. Industry benchmark commentary
4. One actionable recommendation

KPI Summary:
{kpi_summary}

Format: plain paragraphs, no bullet points. Max 300 words.
Conclude with: 'Note: All insights are AI-generated and require analyst review before use.'
"""

GAPS_PROMPT = """Review the following ESG KPI summary and list data quality issues:
- Missing or zero values where data would be expected
- Year-on-year variations above 20% that need explanation
- Completeness issues by section

KPI Summary:
{kpi_summary}

Flags provided:
{flags}

Format: numbered list of issues. Keep each item to one sentence.
"""

READINESS_PROMPT = """Rate the readiness of this submission for inclusion in the TIP consolidated report.
Score from 0-100 and give a 2-sentence justification.

KPI Summary:
{kpi_summary}

Completeness by section:
{completeness}

Flags: {n_errors} errors, {n_warnings} warnings.

Respond as JSON: {{"score": 82, "label": "Review required", "justification": "..."}}
"""


# ─── LLM client ──────────────────────────────────────────────────────────────

def _is_placeholder_endpoint(endpoint: str) -> bool:
    """Return True if the endpoint is still the default placeholder."""
    return not endpoint or "YOUR-RESOURCE" in endpoint


class LLMClient:
    """Azure OpenAI client. Only receives anonymised KPI summaries."""

    def __init__(self):
        self.endpoint = AZURE_OPENAI_ENDPOINT
        self.key      = AZURE_OPENAI_KEY
        self.deploy   = AZURE_OPENAI_DEPLOY

    def _call(self, messages: list, max_tokens: int = MAX_TOKENS) -> str:
        """
        Make a single API call to Azure OpenAI.

        M6 FIX: validates both key AND endpoint before attempting a network
        request.  Previously only the key was checked — a set key combined
        with the placeholder endpoint URL would raise an unhandled
        requests.ConnectionError instead of returning the mock response.
        """
        if not self.key or _is_placeholder_endpoint(self.endpoint):
            reason = "key not set" if not self.key else "endpoint is placeholder"
            logger.warning("Azure OpenAI not configured (%s) — returning mock", reason)
            preview = (messages[-1].get("content", "") or "")[:80]
            return _mock_response(preview)

        url = (
            f"{self.endpoint}/openai/deployments/{self.deploy}"
            f"/chat/completions?api-version={API_VERSION}"
        )
        headers = {"api-key": self.key, "Content-Type": "application/json"}
        payload = {
            "messages":   messages,
            "max_tokens": max_tokens,
            "temperature":TEMPERATURE,
        }

        for attempt in range(3):
            try:
                resp = requests.post(url, headers=headers,
                                     json=payload, timeout=30)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
            except requests.HTTPError as e:
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Rate limited — retrying in %ss", wait)
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError("Azure OpenAI call failed after 3 retries")

    def generate_insight(self, kpis: dict, company: str, year: int) -> str:
        summary  = _build_kpi_summary(kpis, company, year)
        prompt   = INSIGHT_PROMPT.format(kpi_summary=summary)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]
        result = self._call(messages)
        logger.info("Insight generated for %s %s (%d chars)",
                    company, year, len(result))
        return result

    def identify_gaps(self, kpis: dict, company: str, year: int,
                      flags: list) -> str:
        summary   = _build_kpi_summary(kpis, company, year)
        flags_txt = "\n".join(
            f"- [{f.get('severity','').upper()}] "
            f"{f.get('message','')}: {f.get('detail','')}"
            for f in flags
        ) or "No validation flags raised."
        prompt   = GAPS_PROMPT.format(kpi_summary=summary, flags=flags_txt)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]
        return self._call(messages)

    def score_readiness(self, kpis: dict, company: str, year: int,
                        completeness: dict, flags: list) -> dict:
        summary    = _build_kpi_summary(kpis, company, year)
        comp_txt   = "\n".join(f"  {k}: {v}%" for k, v in completeness.items())
        n_errors   = sum(1 for f in flags if f.get("severity") == "error")
        n_warnings = sum(1 for f in flags if f.get("severity") == "warning")
        prompt     = READINESS_PROMPT.format(
            kpi_summary=summary, completeness=comp_txt,
            n_errors=n_errors, n_warnings=n_warnings,
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]
        raw = self._call(messages, max_tokens=200)
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"score": 70, "label": "Review required",
                "justification": raw[:200]}


# ─── Mock response ────────────────────────────────────────────────────────────

def _mock_response(prompt_preview: str) -> str:
    return (
        "[AI MOCK — Azure OpenAI not configured]\n\n"
        "This is a placeholder response generated without calling the API. "
        "Set AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT in your .env file "
        "to enable live AI insights.\n\n"
        "Note: All insights are AI-generated and require analyst review before use."
    )


# ─── Singleton ────────────────────────────────────────────────────────────────

_llm: Optional[LLMClient] = None

def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


# ─── Self-test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    llm = get_llm()
    test_kpis = {
        "production_mt":    1_515_000,
        "total_energy_gj":  13_300_000,
        "energy_kpi":       8.78,
        "co2_scope1":       405_000,
        "co2_scope2":       376_000,
        "total_co2":        781_000,
        "co2_kpi":          0.516,
        "water_m3":         9_180_000,
        "water_kpi":        6.06,
        "renew_elec_pct":   69.1,
        "waste_recovery_pct": 92.4,
        "yoy_co2_pct":      -3.2,
        "yoy_energy_pct":   +1.1,
        "benchmarks": [
            {"kpi":"CO2 intensity","position":"Top 25%","value":0.516,"median":0.68},
            {"kpi":"Energy intensity","position":"Above avg","value":8.78,"median":9.2},
        ],
    }

    print("=== INSIGHT ===")
    print(llm.generate_insight(test_kpis, "VerdaTyres Corp", 2023))
    print("\n=== GAPS ===")
    print(llm.identify_gaps(test_kpis, "VerdaTyres Corp", 2023, []))
    print("\n=== READINESS SCORE ===")
    completeness = {
        "ISO 14001":100, "Production":100, "Water":100,
        "Energy":95, "CO2 Scope 1":100, "CO2 Scope 2":85,
        "Waste":88,
    }
    score = llm.score_readiness(test_kpis, "VerdaTyres Corp", 2023,
                                completeness, [])
    print(json.dumps(score, indent=2))