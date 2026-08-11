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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from modules.pdf_parser import PDFParser, ContractData
from modules.audit_engine import AuditEngine, AuditReport
from modules.statement_parser import StatementParser

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
    context = json.dumps(contract_data, ensure_ascii=False)
    prompt = f"以下是一份股票成交单的数据：\n{context}\n\n用户问题：{question}\n\n请用简洁专业的语言回答。"

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
