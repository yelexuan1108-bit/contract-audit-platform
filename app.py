"""
AI 股票成交单审核平台
FastAPI Web 应用 — 上传 PDF -> 解析 -> AI 审核 -> 展示报告
"""
import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, UploadFile, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from modules.pdf_parser import PDFParser, ContractData
from modules.audit_engine import AuditEngine, AuditReport
from modules.statement_parser import StatementParser
from modules.va_checker import VAChecker
from modules.contract_auditor import ContractAuditor

# ===== 应用初始化 =====
app = FastAPI(
    title="Contract Note Audit Platform",
    description="AI 驱动的股票成交单审核平台",
    version="1.0.0",
)

# 静态文件 & 模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 目录
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
RECORDS_DIR = Path("records")
RECORDS_DIR.mkdir(exist_ok=True)


# ===== 辅助函数 =====
def get_audit_engine() -> AuditEngine:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    return AuditEngine(api_key=api_key)

def save_record(data: dict):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    record_path = RECORDS_DIR / f"{timestamp}.json"
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== 路由 =====

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "title": "AI 成交单审核平台",
    })


@app.post("/api/audit", response_class=JSONResponse)
async def audit_contract(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        return JSONResponse({"error": "仅支持 PDF 文件"}, status_code=400)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name

    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        return JSONResponse({"error": f"文件保存失败: {str(e)}"}, status_code=500)

    try:
        parser = PDFParser()
        contract_data = parser.parse(str(file_path))
        engine = get_audit_engine()
        report = engine.audit(contract_data, file.filename)

        result = {
            "success": True,
            "file_name": file.filename,
            "audit_time": report.audit_time,
            "contract_data": contract_data.model_dump(),
            "findings": [f.model_dump() for f in report.findings],
            "total_findings": report.total_findings,
            "critical_count": report.critical_count,
            "warning_count": report.warning_count,
            "info_count": report.info_count,
            "ai_summary": report.ai_summary,
            "fee_waiver_details": report.fee_waiver_details,
        }

        save_record(result)
        return result

    except Exception as e:
        return JSONResponse({"error": f"审核失败: {str(e)}"}, status_code=500)


@app.get("/api/records", response_class=JSONResponse)
async def get_records():
    records = []
    for f in sorted(RECORDS_DIR.glob("*.json"), reverse=True)[:50]:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                records.append({
                    "id": f.stem,
                    "file_name": data.get("file_name", ""),
                    "audit_time": data.get("audit_time", ""),
                    "total_findings": data.get("total_findings", 0),
                    "critical_count": data.get("critical_count", 0),
                    "warning_count": data.get("warning_count", 0),
                })
        except Exception:
            continue
    return {"records": records}


@app.get("/api/records/{record_id}", response_class=JSONResponse)
async def get_record(record_id: str):
    record_path = RECORDS_DIR / f"{record_id}.json"
    if not record_path.exists():
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    with open(record_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/chat", response_class=JSONResponse)
async def chat(request: Request):
    body = await request.json()
    question = body.get("question", "")
    contract_data = body.get("contract_data", {})
    api_key = os.environ.get("OPENROUTER_API_KEY", "")

    if not api_key:
        return {"answer": "未配置 API Key，无法使用聊天功能。"}

    import httpx

    has_data = bool(contract_data and any(v for v in contract_data.values() if v))

    if has_data:
        context = json.dumps(contract_data, ensure_ascii=False)
        prompt = f"以下是一份股票成交单的数据：\n{context}\n\n用户问题：{question}\n\n请用简洁专业的语言回答，使用简体中文。"
    else:
        prompt = f"{question}\n\n请用简洁专业的语言回答，使用简体中文。"

    try:
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "nvidia/nemotron-3-nano-30b-a3b:free",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
            },
            timeout=30,
        )
        answer = response.json()["choices"][0]["message"]["content"]
        return {"answer": answer}
    except Exception as e:
        return {"answer": f"AI 回答失败: {str(e)}"}


@app.post("/api/compare", response_class=JSONResponse)
async def compare_documents(
    contract_file: UploadFile = File(...),
    statement_file: UploadFile = File(...),
):
    """对比成交单和月结单"""
    results = {"matches": [], "mismatches": [], "unmatched": []}

    # 保存并解析成交单
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    contract_path = UPLOAD_DIR / f"{ts}_contract_{contract_file.filename}"
    statement_path = UPLOAD_DIR / f"{ts}_statement_{statement_file.filename}"

    with open(contract_path, "wb") as f:
        f.write(await contract_file.read())
    with open(statement_path, "wb") as f:
        f.write(await statement_file.read())

    contract = PDFParser().parse(str(contract_path))
    statement = StatementParser().parse(str(statement_path))

    # 构建成交单摘要
    cn = {
        "stock_code": contract.stock_code,
        "stock_name": contract.stock_name,
        "trade_date": contract.contract_date,
        "settlement_date": contract.settlement_date,
        "quantity": contract.quantity,
        "unit_price": contract.avg_price,
        "commission": contract.commission,
        "platform_fee": contract.platform_fee,
        "settlement_amount": contract.settlement_amount,
        "account_number": contract.account_number,
        "customer_name": contract.customer_name,
    }

    # 在月结单中找匹配交易
    matched_tx = None
    for tx in statement.transactions:
        code_match = tx.stock_code == contract.stock_code
        qty_match = tx.quantity == contract.quantity if tx.quantity and contract.quantity else False
        if code_match and qty_match:
            matched_tx = tx
            break
        elif code_match:
            matched_tx = tx  # 股票代码匹配就算找到，继续比对其他字段

    if not matched_tx and statement.transactions:
        # 尝试只匹配股票代码
        for tx in statement.transactions:
            if tx.stock_code == contract.stock_code:
                matched_tx = tx
                break

    def check(field, cn_val, st_val, label):
        if cn_val is None and st_val is None:
            return
        if cn_val is None or st_val is None:
            results["mismatches"].append({
                "field": label,
                "contract": str(cn_val) if cn_val is not None else "未提取到",
                "statement": str(st_val) if st_val is not None else "未提取到",
                "note": "其中一方未能提取数据"
            })
            return
        if isinstance(cn_val, float) and isinstance(st_val, float):
            ok = abs(cn_val - st_val) < 0.02
        else:
            ok = str(cn_val).strip() == str(st_val).strip()
        item = {"field": label, "contract": str(cn_val), "statement": str(st_val)}
        if ok:
            results["matches"].append(item)
        else:
            results["mismatches"].append(item)

    if matched_tx:
        check("stock_code", cn["stock_code"], matched_tx.stock_code, "股票代码")
        check("quantity", cn["quantity"], matched_tx.quantity, "成交股数")
        check("unit_price", cn["unit_price"], matched_tx.unit_price, "成交单价")
        check("commission", cn["commission"], matched_tx.commission, "佣金")
        check("platform_fee", cn["platform_fee"], matched_tx.platform_fee, "平台费")
        check("settlement_amount", cn["settlement_amount"], matched_tx.settlement_amount, "交收金额")
    else:
        results["unmatched"].append({
            "note": f"月结单中未找到股票代码 {contract.stock_code} 的对应交易记录"
        })

    # 账户核对
    if statement.account_number and contract.account_number:
        check("account_number", cn["account_number"], statement.account_number, "账户号码")

    return {
        "success": True,
        "contract_summary": cn,
        "statement_summary": {
            "account_number": statement.account_number,
            "customer_name": statement.customer_name,
            "period": statement.statement_period,
            "transaction_count": len(statement.transactions),
            "matched_transaction": matched_tx.model_dump() if matched_tx else None,
        },
        "matches": results["matches"],
        "mismatches": results["mismatches"],
        "unmatched": results["unmatched"],
        "overall": "pass" if not results["mismatches"] and not results["unmatched"] else "fail",
    }


@app.post("/api/batch-audit", response_class=JSONResponse)
async def batch_audit_contracts(files: list[UploadFile] = File(...)):
    """批量审核成交单重要提示条款"""
    auditor = ContractAuditor()
    results = []
    errors = []

    for file in files:
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            errors.append({"file": file.filename, "error": "非 PDF 文件"})
            continue

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        file_path = UPLOAD_DIR / f"{ts}_{file.filename}"
        try:
            with open(file_path, "wb") as f:
                f.write(await file.read())
            result = auditor.audit(str(file_path), file.filename)
            data = result.model_dump()
            save_record({"type": "clause_audit", **data})
            results.append(data)
        except Exception as e:
            errors.append({"file": file.filename, "error": str(e)})

    return {
        "success": True,
        "total": len(results),
        "errors": errors,
        "results": results,
    }


@app.get("/api/export/clause-audit", response_class=StreamingResponse)
async def export_clause_audit():
    """导出条款审核结果为 Excel"""
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from io import BytesIO

    wb = openpyxl.Workbook()

    # ===== 颜色定义 =====
    GREEN  = PatternFill("solid", fgColor="DCFCE7")
    RED    = PatternFill("solid", fgColor="FEE2E2")
    HEADER = PatternFill("solid", fgColor="030516")
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
    BOLD   = Font(bold=True, size=10)
    NORMAL = Font(size=10)
    CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
    LEFT   = Alignment(horizontal="left", vertical="center", wrap_text=True)
    thin   = Side(style="thin", color="E5E7EB")
    BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)

    def style_header(ws, row=1):
        for cell in ws[row]:
            cell.fill   = HEADER
            cell.font   = HEADER_FONT
            cell.alignment = CENTER
            cell.border = BORDER

    def style_row(ws, row_num, fill=None):
        for cell in ws[row_num]:
            if fill: cell.fill = fill
            cell.font = NORMAL
            cell.alignment = LEFT
            cell.border = BORDER

    # ===== Sheet 1: 汇总 =====
    ws1 = wb.active
    ws1.title = "审核汇总"
    headers1 = [
        "文件名", "审核时间", "文件类型", "市场", "语言", "交易类型",
        "客户姓名", "账户号码", "成交日期",
        "英文条款总数", "英文通过", "英文失败",
        "中文条款总数", "中文通过", "中文失败",
        "总体结论", "失败条款"
    ]
    ws1.append(headers1)
    style_header(ws1)

    # ===== Sheet 2: 英文条款详情 =====
    ws2 = wb.create_sheet("英文条款详情")
    headers2 = ["文件名", "客户姓名", "文件类型", "条款编号", "关键词", "结果", "备注"]
    ws2.append(headers2)
    style_header(ws2)

    # ===== Sheet 3: 中文条款详情 =====
    ws3 = wb.create_sheet("中文条款详情")
    headers3 = ["文件名", "客户姓名", "文件类型", "条款编号", "关键词", "结果", "备注"]
    ws3.append(headers3)
    style_header(ws3)

    # 读取所有条款审核记录
    for f in sorted(RECORDS_DIR.glob("*.json"), reverse=True)[:500]:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
            if d.get("type") != "clause_audit":
                continue

            pass_fill = GREEN if d.get("overall") == "pass" else RED

            # 汇总行
            row1 = [
                d.get("file_name", ""),
                d.get("audit_time", ""),
                d.get("doc_type", ""),
                "HK" if "HK" in d.get("doc_type","") else ("US" if "US" in d.get("doc_type","") else d.get("doc_type","")),
                d.get("language", ""),
                d.get("transaction_type", ""),
                d.get("customer_name", ""),
                d.get("account_number", ""),
                d.get("contract_date", ""),
                d.get("en_total", 0),
                d.get("en_passed", 0),
                d.get("en_total", 0) - d.get("en_passed", 0),
                d.get("zh_total", 0),
                d.get("zh_passed", 0),
                d.get("zh_total", 0) - d.get("zh_passed", 0),
                "通过" if d.get("overall") == "pass" else "失败",
                "; ".join(d.get("issues", [])),
            ]
            ws1.append(row1)
            style_row(ws1, ws1.max_row, pass_fill)

            # 英文条款行
            for c in d.get("en_clauses", []):
                r_fill = GREEN if c.get("result") == "pass" else RED
                ws2.append([
                    d.get("file_name",""),
                    d.get("customer_name",""),
                    d.get("doc_type",""),
                    c.get("clause_num",""),
                    c.get("keyword","")[:80],
                    "通过" if c.get("result") == "pass" else "失败",
                    c.get("note",""),
                ])
                style_row(ws2, ws2.max_row, r_fill)

            # 中文条款行
            for c in d.get("zh_clauses", []):
                r_fill = GREEN if c.get("result") == "pass" else RED
                ws3.append([
                    d.get("file_name",""),
                    d.get("customer_name",""),
                    d.get("doc_type",""),
                    c.get("clause_num",""),
                    c.get("keyword","")[:80],
                    "通过" if c.get("result") == "pass" else "失败",
                    c.get("note",""),
                ])
                style_row(ws3, ws3.max_row, r_fill)

        except Exception:
            continue

    # 调整列宽
    col_widths = {
        ws1: [30,18,10,6,6,8,18,14,12,8,8,8,8,8,8,8,40],
        ws2: [30,18,10,10,60,6,40],
        ws3: [30,18,10,10,60,6,40],
    }
    for ws, widths in col_widths.items():
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
        ws.row_dimensions[1].height = 30
        ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=clause_audit_report.xlsx"}
    )


@app.post("/api/va-audit", response_class=JSONResponse)
async def va_audit(file: UploadFile = File(...)):
    """VA成交单审核"""
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        return JSONResponse({"error": "仅支持 PDF 文件"}, status_code=400)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = UPLOAD_DIR / f"{ts}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(await file.read())

    try:
        checker = VAChecker()
        result = checker.check(str(file_path), file.filename)
        data = result.model_dump()
        save_record({"type": "va", **data})
        return {"success": True, **data}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/export/excel", response_class=StreamingResponse)
async def export_excel():
    """导出所有审核记录为 Excel"""
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment
    from io import BytesIO

    wb = openpyxl.Workbook()

    # ===== Sheet 1: 成交单审核汇总 =====
    ws1 = wb.active
    ws1.title = "成交单审核"
    headers1 = ["文件名", "审核时间", "客户姓名", "账户号码", "股票", "成交日期",
                "严重问题", "警告", "信息", "总计", "AI摘要"]
    ws1.append(headers1)
    for cell in ws1[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="4F46E5")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center")

    # ===== Sheet 2: VA审核汇总 =====
    ws2 = wb.create_sheet("VA成交单审核")
    headers2 = ["文件名", "审核时间", "客户姓名", "账户号码", "资产名称", "资产代码",
                "语言", "交易类型", "成交日期", "总检查项", "通过", "失败", "总体结论"]
    ws2.append(headers2)
    for cell in ws2[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
        cell.alignment = Alignment(horizontal="center")

    # ===== Sheet 3: VA详细检查项 =====
    ws3 = wb.create_sheet("VA详细检查项")
    headers3 = ["文件名", "客户姓名", "检查类别", "检查项目", "结果", "详情"]
    ws3.append(headers3)
    for cell in ws3[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
        cell.alignment = Alignment(horizontal="center")

    # 读取所有记录
    pass_fill = PatternFill("solid", fgColor="DCFCE7")
    fail_fill = PatternFill("solid", fgColor="FEE2E2")
    warn_fill = PatternFill("solid", fgColor="FEF3C7")

    for f in sorted(RECORDS_DIR.glob("*.json"), reverse=True)[:200]:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            if data.get("type") == "va":
                row = [
                    data.get("file_name", ""),
                    data.get("audit_time", ""),
                    data.get("customer_name", ""),
                    data.get("account_number", ""),
                    data.get("asset_name", ""),
                    data.get("asset_code", ""),
                    data.get("language", ""),
                    data.get("transaction_type", ""),
                    data.get("contract_date", ""),
                    data.get("total", 0),
                    data.get("passed", 0),
                    data.get("failed", 0),
                    "通过" if data.get("overall") == "pass" else "失败",
                ]
                r = ws2.append(row)
                last = ws2.max_row
                fill = pass_fill if data.get("overall") == "pass" else fail_fill
                for cell in ws2[last]:
                    cell.fill = fill

                # 写详细检查项
                for check in data.get("checks", []):
                    ws3.append([
                        data.get("file_name", ""),
                        data.get("customer_name", ""),
                        check.get("category", ""),
                        check.get("item", ""),
                        check.get("result", ""),
                        check.get("detail", ""),
                    ])
                    last3 = ws3.max_row
                    r = check.get("result", "")
                    f3 = pass_fill if r == "pass" else (fail_fill if r == "fail" else warn_fill)
                    ws3[last3][4].fill = f3

            elif data.get("success"):
                cd = data.get("contract_data", {})
                row = [
                    data.get("file_name", ""),
                    data.get("audit_time", ""),
                    f"{cd.get('customer_name','')} {cd.get('customer_name_cn','')}".strip(),
                    cd.get("account_number", ""),
                    f"{cd.get('stock_name','')} ({cd.get('stock_code','')})".strip(),
                    cd.get("contract_date", ""),
                    data.get("critical_count", 0),
                    data.get("warning_count", 0),
                    data.get("info_count", 0),
                    data.get("total_findings", 0),
                    data.get("ai_summary", "")[:100],
                ]
                ws1.append(row)
                last = ws1.max_row
                fill = pass_fill if data.get("critical_count", 0) == 0 else fail_fill
                for cell in ws1[last]:
                    cell.fill = fill
        except Exception:
            continue

    # 调整列宽
    for ws in [ws1, ws2, ws3]:
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=audit_report.xlsx"}
    )


@app.get("/api/health")
async def health_check():
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "ai_enabled": bool(api_key),
        "ai_provider": "OpenRouter Nemotron" if api_key else "未配置",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
