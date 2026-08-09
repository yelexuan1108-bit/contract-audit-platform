"""
AI 股票成交单审核平台
FastAPI Web 应用 — 上传 PDF → 解析 → AI 审核 → 展示报告
"""
import os
import shutil
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from modules.pdf_parser import PDFParser, ContractData
from modules.audit_engine import AuditEngine, AuditReport

# ===== 应用初始化 =====
app = FastAPI(
    title="Contract Note Audit Platform",
    description="AI 驱动的股票成交单审核平台",
    version="1.0.0",
)

# 静态文件 & 模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 上传目录
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


# ===== 辅助函数 =====
def get_audit_engine() -> AuditEngine:
    """获取审核引擎实例"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return AuditEngine(api_key=api_key)


# ===== 路由 =====

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """主页 — 上传界面"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "title": "AI 成交单审核平台",
    })


@app.post("/api/audit", response_class=JSONResponse)
async def audit_contract(file: UploadFile = File(...)):
    """
    上传 PDF 成交单并执行 AI 审核
    """
    # 验证文件类型
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        return JSONResponse(
            {"error": "仅支持 PDF 文件，请上传 .pdf 格式的成交单。"},
            status_code=400,
        )

    # 保存上传文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name

    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        return JSONResponse(
            {"error": f"文件保存失败: {str(e)}"},
            status_code=500,
        )

    try:
        # Step 1: PDF 解析
        parser = PDFParser()
        contract_data = parser.parse(str(file_path))

        # Step 2: AI 审核
        engine = get_audit_engine()
        report = engine.audit(contract_data, file.filename)

        # 构建响应
        return {
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

    except Exception as e:
        return JSONResponse(
            {"error": f"审核失败: {str(e)}"},
            status_code=500,
        )


@app.post("/api/audit/batch", response_class=JSONResponse)
async def batch_audit(files: list[UploadFile] = File(...)):
    """批量审核多个成交单"""
    results = []
    errors = []

    for file in files:
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            errors.append({"file": file.filename, "error": "非 PDF 文件"})
            continue

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = f"{timestamp}_{file.filename}"
        file_path = UPLOAD_DIR / safe_name

        try:
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)

            parser = PDFParser()
            contract_data = parser.parse(str(file_path))
            engine = get_audit_engine()
            report = engine.audit(contract_data, file.filename)

            results.append({
                "file_name": file.filename,
                "success": True,
                "contract_data": contract_data.model_dump(),
                "findings": [f.model_dump() for f in report.findings],
                "total_findings": report.total_findings,
                "critical_count": report.critical_count,
                "fee_waiver_details": report.fee_waiver_details,
            })

        except Exception as e:
            errors.append({"file": file.filename, "error": str(e)})

    return {
        "success": True,
        "total_processed": len(results),
        "total_errors": len(errors),
        "results": results,
        "errors": errors,
    }


@app.get("/api/health")
async def health_check():
    """健康检查 — 验证服务状态和 API 连接"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "ai_enabled": bool(api_key),
        "ai_provider": "Anthropic Claude" if api_key else "未配置",
    }


# ===== 启动脚本 =====
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("📊 AI 股票成交单审核平台")
    print("=" * 60)
    api_status = "✅ AI 审核已启用 (Claude API)" if os.environ.get("ANTHROPIC_API_KEY") else "⚠️  AI 审核未启用 (规则引擎模式)"
    print(f"   {api_status}")
    print(f"   🌐 访问地址: http://localhost:8000")
    print(f"   📖 API 文档: http://localhost:8000/docs")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
