# Publishing kit: GitHub, portfolio website, LinkedIn

Replace `<your-app>` with your Streamlit URL once it's deployed.

---

## 1. GitHub repo settings

- **Repository name:** `genai-financial-reporting-assistant`
- **Description (About box):**
  Generative AI financial reporting & BI assistant. Ask "Why did operating profit decline?" in plain English and get SQL-grounded answers, profit bridges, charts and automated CFO summaries. Python · SQL · LLM API · Streamlit
- **Website:** [genai-finbi-abrar.streamlit.app](https://genai-finbi-abrar.streamlit.app)
- **Topics:** `generative-ai` `llm` `text-to-sql` `financial-analysis` `business-intelligence` `streamlit` `sql` `python` `fpa` `retail-analytics` `kaggle` `anthropic` `openai`
- **Pin it** on your GitHub profile (Profile → Customize your pins).

---

## 2. Portfolio website (abuabrar09.github.io)

Paste this project card into your `index.html` projects section, and adjust the class names to match your site's CSS:

```html
<div class="project-card">
  <h3>Generative AI Financial Reporting &amp; BI Assistant</h3>
  <p class="tags">Python · SQL · LLM API · Streamlit · Plotly</p>
  <p>
    A natural-language finance assistant for a 54-store supermarket chain (Kaggle Favorita, ~3M rows).
    Managers ask questions like <em>"Why did operating profit decline?"</em> and get an operating-profit
    bridge (volume, mix, promo markdowns, labor, fuel-linked logistics), charts, the SQL used, and an
    automated CFO summary.
  </p>
  <ul>
    <li>LLM text-to-SQL with read-only guardrails and automatic self-correction</li>
    <li>Deterministic variance engine: the LLM explains numbers but never invents them</li>
    <li>SQLite star schema built by a chunked Python ETL; tested with pytest + GitHub Actions</li>
  </ul>
  <p>
    <a href="https://genai-finbi-abrar.streamlit.app" target="_blank">Live demo</a> ·
    <a href="https://github.com/Abuabrar09/GenAI-Financial-Reporting-Assistant" target="_blank">GitHub</a>
  </p>
</div>
```

---

## 3. LinkedIn: Projects section

Go to Profile → **Add profile section → Recommended → Add projects**.

- **Project name:** Generative AI Financial Reporting & Business Intelligence Assistant
- **Associated with:** BMF Capital Holdings, or leave it blank for a personal project
- **Description:**

> Built a natural-language finance assistant that lets managers ask business questions in plain English, such as "Why did operating profit decline in 2015?", and get instant, data-grounded answers.
>
> • Data: Kaggle Corporación Favorita supermarket data (~3M daily rows, 54 stores, 33 product families), modeled into a SQLite star schema with a monthly store P&L via a chunked Python ETL.
> • AI: LLM-powered text-to-SQL (Claude / OpenAI) with read-only guardrails, SQL validation and automatic self-correction.
> • Finance: a deterministic operating-profit bridge (revenue volume, product mix, promo markdowns, labor, occupancy, fuel-linked logistics, overhead) so the LLM explains numbers and never invents them.
> • Reporting: one-click executive summaries vs prior period and prior year, plus an interactive P&L explorer in Streamlit.
> • Engineering: pytest suite and GitHub Actions CI; an offline mode keeps the public demo working without an API key.
>
> Outcome: reduces manual monthly reporting and makes financial insights self-service for non-technical stakeholders.

- **Skills:** Generative AI · Large Language Models (LLM) · SQL · Python · Streamlit · Financial Analysis · Business Intelligence · Data Modeling
- **Media/link:** add the GitHub repo and live demo, plus a screenshot or GIF of the "Why did operating profit decline?" answer

---

## 4. LinkedIn post (optional, for reach)

> What if your CFO could just *ask* the data?
>
> I built a Generative AI Financial Reporting Assistant on 3M rows of real supermarket data (Kaggle – Corporación Favorita, 54 stores).
>
> Ask "Why did operating profit decline in 2015?" and it:
> 📉 builds an operating-profit bridge (volume, mix, promo markdowns, labor, fuel-linked logistics)
> 🧠 uses an LLM to explain the drivers in plain English, grounded only in computed numbers
> 📊 shows the chart and the exact SQL behind every answer
> 📝 writes a one-click executive summary vs last period and last year
>
> The hardest part wasn't the LLM. It was making sure the AI never invents a number. The finance math is deterministic, and the LLM is only the storyteller.
>
> Stack: Python · SQL · Claude/OpenAI API · Streamlit
> 🔗 Demo: https://genai-finbi-abrar.streamlit.app
> 💻 Code: https://github.com/Abuabrar09/GenAI-Financial-Reporting-Assistant
>
> #GenerativeAI #DataAnalytics #FinancialAnalysis #SQL #Python #BusinessIntelligence #FPandA

---

## 5. Resume bullets

- Built a Generative AI financial reporting assistant (Python, SQL, LLM API, Streamlit) that answers natural-language questions over ~3M rows of retail sales data, using text-to-SQL with read-only guardrails and automatic query self-correction.
- Designed a deterministic operating-profit bridge (volume, mix, markdown, opex drivers) and automated executive summaries, so "why did profit change?" analysis takes one click instead of a manual walk built in Excel.
