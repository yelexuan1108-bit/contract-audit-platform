# Contract Note Audit Platform — User Guide

An AI-assisted audit platform for Hong Kong investment contract notes. It checks contract notes against official templates and reports missing or inconsistent clauses.

## 1. Overview

The platform audits four product types:

| Product | Page | Description |
|---|---|---|
| 股票成交单 (Stock) | Stock Contract Note | Equity trades; auto-detects HK/US markets and subtype |
| 基金成交单 (Fund) | Fund Contract Note | Fund transactions; auto-detects language |
| VA 虚拟资产 (Virtual Asset) | VA Virtual Asset | Crypto contract notes; auto-detects Buy/Sell and language; extra VA-specific checks |
| 投资月结单 (Statement) | Investment Monthly Statement | Monthly statements; 3 subtypes: Monthly / BB Invest / Southbound |

Each audit performs two kinds of checks:

- **Clause audit (条款核查)** — a local rule engine that compares extracted PDF text against stored clause templates and required fields.
- **AI audit (AI 审核)** — an optional LLM review (Stock and Fund only) that flags risk findings, fee waivers and a summary.
- **VA special check (VA 专项检查)** — a dedicated checker for Virtual Asset contract notes (50 items).

## 2. Setup

### Requirements

- Python 3.10+
- Dependencies in `requirements.txt`

### Install & run

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit .env
python app.py
```

Open http://localhost:8000 in a browser.

### Configuration (`.env`)

| Variable | Purpose | Optional |
|---|---|---|
| `OPENROUTER_API_KEY` | API key for the AI audit (OpenRouter/Claude). If unset, only the local rule engine runs. | Yes |
| `PORT` | Server port (default `8000`). | Yes |

The top-right badge shows whether AI is enabled.

## 3. Auditing a product

All product pages (Stock / Fund / VA / Statement) follow the same workflow.

### Step 1 — Upload files

- Drag a **folder** or **PDF files** into the drop zone, or click **选择 PDF 文件 / 选择文件夹**.
- Multiple files are supported (up to **200 per batch**).
- The file list shows each selected file and total size.

### Step 2 — (Statement only) choose a subtype

On the Statement page, select **子类型**: 投资月结单 / BB Invest / Southbound 南向通.

### Step 3 — (Stock / Fund only) optionally skip AI

Tick **跳过 AI 审核** to run only the local rule engine. This is much faster for large batches.

### Step 4 — Run

Click **开始审核**. A progress bar shows live upload/processing progress. Files are processed concurrently.

### Step 5 — Review results

Each file is tagged with its detected product, subtype and overall result:

- **条款通过 (clauses passed)** — all clause checks passed.
- **条款问题 (clause issues)** — lists the failing clauses.

Expand a result to see:

- **英文条款 / 中文条款** — per-clause pass/fail with matched keywords.
- **个人资料** — personal information check.
- **AI 审核** — findings, critical/warning/info counts and summary (Stock/Fund).
- **VA 专项检查** — the 50-item VA checklist (VA).

## 4. Clause template management (条款模板)

The **条款模板** page manages the clause templates used by the local rule engine.

### Tabs

- **Product tabs**: Stock / Fund / VA / Statement.
- **Subtype tabs**: shown for products with subtypes (Stock has 6; VA has Buy/Sale; Statement has Monthly/BB Invest/Southbound).
- **Language tabs**: English / 繁体中文 / 简体中文.

Each product stores clauses per subtype and language, plus a version label.

### Manual editing

- Click **+ 添加条款** to add a clause, edit inline, then **保存全部条款**.
- Clause numbering is auto-renumbered on save.

### Import from HTML templates

Three ways:

1. **单文件导入 (single file)** — replaces the current product + language clauses.
2. **批量导入 (batch)** — select multiple HTML files; language (`_hk_` / `_zh_`) and subtype (`bbInvest` / `southBound` / default `monthly`) are detected automatically from the filename, and the clauses are written into the matching slot.
3. **一键同步 (folder sync)** — scan a whole template folder and import every HTML file, auto-detecting product, subtype and language from the path.

> After importing, click **保存全部条款** to persist to `data/clauses.json`.

## 5. History (历史记录)

Lists all previous audit reports. Click a record to view details, or **导出 Excel** to download a full report.

## 6. AI assistant (AI 助手)

The floating chat box in the bottom corner answers questions about file content and audit results.

## 7. Excel export

- Each product page: **导出 Excel 报告** downloads a clause-audit spreadsheet (`clause_audit_report.xlsx`).
- History page: **导出 Excel** downloads a combined report with three sheets (contract-note summary, monthly-statement summary, VA summary).

## 8. FAQ

**Q: Why is a file tagged 条款问题 even though I imported the template?**
Check that you selected the correct product page for the file. A Fund file uploaded on the VA page will fail all VA checks — upload to the matching product page.

**Q: What does "跳过 AI 审核" do?**
It disables the LLM review, keeping only the fast local rule engine.

**Q: What is the upload limit?**
200 PDF files per batch.

**Q: Does the platform work without an API key?**
Yes — clause and VA checks run fully offline. Only the AI review requires `OPENROUTER_API_KEY`.