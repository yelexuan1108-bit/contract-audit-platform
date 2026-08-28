"""
AI 审核引擎 — 使用 Claude API 对成交单进行智能审核
包含：费用豁免识别、合规检查、异常检测、数据验证
"""
import json
import os
from typing import Optional
from pydantic import BaseModel
from .pdf_parser import ContractData


class AuditFinding(BaseModel):
    """单条审核发现"""
    category: str          # fee_waiver | compliance | anomaly | data_quality
    severity: str          # info | warning | critical
    title: str
    detail: str
    suggestion: str = ""


class AuditReport(BaseModel):
    """审核报告"""
    # 基本信息
    file_name: str
    audit_time: str

    # 提取的结构化数据
    contract_data: ContractData

    # 审核发现列表
    findings: list[AuditFinding]

    # 汇总
    total_findings: int
    critical_count: int
    warning_count: int
    info_count: int

    # AI 审核摘要
    ai_summary: str = ""

    # 费用豁免详情
    fee_waiver_details: dict = {}


class AuditEngine:
    """AI 审核引擎"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")

    def audit(self, contract: ContractData, file_name: str) -> AuditReport:
        """对成交单执行全面审核"""
        findings: list[AuditFinding] = []

        # 1. 规则引擎审核（本地执行，无需 API）
        rule_findings = self._rule_based_audit(contract)
        findings.extend(rule_findings)

        # 2. AI 审核（使用 Claude API）
        if self.api_key:
            try:
                ai_findings, ai_summary = self._ai_audit(contract)
                findings.extend(ai_findings)
            except Exception as e:
                findings.append(AuditFinding(
                    category="data_quality",
                    severity="warning",
                    title="AI 审核未能完成",
                    detail=f"AI API 调用失败: {str(e)}。规则引擎审核已完成。",
                    suggestion="请检查 ANTHROPIC_API_KEY 是否正确配置。"
                ))
                ai_summary = "AI 深度审核未执行（API 连接失败），以下为规则引擎审核结果。"
        else:
            ai_summary = "未配置 OPENROUTER_API_KEY，仅执行规则引擎审核。"
            findings.append(AuditFinding(
                category="data_quality",
                severity="info",
                title="未启用 AI 审核",
                detail="当前仅运行规则引擎审核。设置 OPENROUTER_API_KEY 环境变量后可使用 Gemma 4 进行深度分析。",
                suggestion="在 .env 文件中设置 OPENROUTER_API_KEY"
            ))

        # 构建报告
        fee_waiver_details = self._analyze_fee_waiver(contract, findings)
        critical = [f for f in findings if f.severity == "critical"]
        warnings = [f for f in findings if f.severity == "warning"]
        infos = [f for f in findings if f.severity == "info"]

        from datetime import datetime
        return AuditReport(
            file_name=file_name,
            audit_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            contract_data=contract,
            findings=findings,
            total_findings=len(findings),
            critical_count=len(critical),
            warning_count=len(warnings),
            info_count=len(infos),
            ai_summary=ai_summary,
            fee_waiver_details=fee_waiver_details,
        )

    def _rule_based_audit(self, c: ContractData) -> list[AuditFinding]:
        """基于规则的审核（本地执行，速度快，无 API 成本）"""
        findings = []

        # ===== 费用豁免识别 =====
        is_commission_waived = c.commission is not None and c.commission == 0
        is_platform_fee_waived = c.platform_fee is not None and c.platform_fee == 0

        if is_commission_waived:
            findings.append(AuditFinding(
                category="fee_waiver",
                severity="info",
                title="✅ 佣金已豁免",
                detail=f"本次交易佣金为 {c.commission_currency or 'USD'} 0.00，已被完全豁免。",
                suggestion="确认该豁免符合客户协议条款。"
            ))

        if is_platform_fee_waived:
            findings.append(AuditFinding(
                category="fee_waiver",
                severity="info",
                title="✅ 平台费已豁免",
                detail=f"本次交易平台费为 {c.platform_fee_currency or 'USD'} 0.00，已被完全豁免。备注: {c.remark or '无'}",
                suggestion="核实平台费豁免是否在有效期内，是否符合银行的豁免政策。"
            ))

        if is_commission_waived and is_platform_fee_waived:
            findings.append(AuditFinding(
                category="fee_waiver",
                severity="info",
                title="📌 全部费用已豁免",
                detail="本次交易的佣金和平台费均已全部豁免，客户零费用交易。",
                suggestion="建议定期审查费用豁免的持续合理性，确保与客户等级匹配。"
            ))

        if not is_commission_waived and not is_platform_fee_waived:
            findings.append(AuditFinding(
                category="fee_waiver",
                severity="info",
                title="无费用豁免",
                detail="本次交易未发现费用豁免，佣金和平台费正常收取。",
                suggestion=""
            ))

        # ===== 合规性检查 =====
        # 小数股交易检查
        if c.quantity and c.quantity < 1:
            findings.append(AuditFinding(
                category="compliance",
                severity="info",
                title="小数股交易 (Fractional Share)",
                detail=f"成交股数为 {c.quantity} 股，属于小数股交易。这在美股市场是合法的。",
                suggestion="小数股交易通常不享有股东投票权，如客户需要投票权，建议购买整股。"
            ))

        # 交易金额合理性
        if c.total_amount and c.total_amount < 1:
            findings.append(AuditFinding(
                category="compliance",
                severity="info",
                title="小额交易",
                detail=f"交易金额仅 {c.total_amount_currency or 'USD'} {c.total_amount:.2f}，属于极小金额交易。",
                suggestion="确认该小额交易为合法交易（如零钱投资、定投计划等）。"
            ))

        # ===== 异常检测 =====
        # 检查金额一致性
        if (c.total_amount and c.settlement_amount and
                c.commission is not None and c.platform_fee is not None):
            expected_settlement = c.total_amount + c.commission + c.platform_fee
            actual = c.settlement_amount
            if abs(expected_settlement - actual) > 0.02:  # 允许2美分舍入误差
                findings.append(AuditFinding(
                    category="anomaly",
                    severity="critical",
                    title="🚨 金额不一致",
                    detail=(
                        f"交易金额 ({c.total_amount}) + 佣金 ({c.commission}) + "
                        f"平台费 ({c.platform_fee}) = {expected_settlement}，"
                        f"但交收金额为 {actual}，差额 {abs(expected_settlement - actual):.4f}"
                    ),
                    suggestion="立即核实交收金额的计算是否正确，可能存在系统计算错误。"
                ))
            else:
                findings.append(AuditFinding(
                    category="data_quality",
                    severity="info",
                    title="✅ 金额校验通过",
                    detail=f"交易金额 + 佣金 + 平台费 = 交收金额 ({c.settlement_amount})，金额一致。",
                    suggestion=""
                ))

        # 检查成交日期与交收日期间隔
        if c.contract_date and c.settlement_date:
            from datetime import datetime
            try:
                contract_dt = datetime.strptime(c.contract_date, "%d %b %Y")
                settlement_dt = datetime.strptime(c.settlement_date, "%d %b %Y")
                diff_days = (settlement_dt - contract_dt).days
                if diff_days <= 0:
                    findings.append(AuditFinding(
                        category="anomaly",
                        severity="warning",
                        title="⚠️ 交收日期异常",
                        detail=f"成交日期 ({c.contract_date}) 与交收日期 ({c.settlement_date}) 间隔仅 {diff_days} 天。",
                        suggestion="美股标准交收周期为 T+1。检查日期是否符合市场规则。"
                    ))
                elif diff_days > 3:
                    findings.append(AuditFinding(
                        category="anomaly",
                        severity="warning",
                        title="⚠️ 交收日期偏长",
                        detail=f"成交到交收间隔 {diff_days} 天，超过常规 T+1/T+2 周期。",
                        suggestion="核实是否存在假期或其他特殊情况导致延迟交收。"
                    ))
            except ValueError:
                pass

        # ===== 数据质量检查 =====
        if not c.order_reference:
            findings.append(AuditFinding(
                category="data_quality",
                severity="warning",
                title="⚠️ 缺少交易编号",
                detail="未能从成交单中提取到交易编号 (Order Reference)。",
                suggestion="检查 PDF 是否完整或格式是否有变化。"
            ))

        if not c.account_number:
            findings.append(AuditFinding(
                category="data_quality",
                severity="warning",
                title="⚠️ 缺少账户号码",
                detail="未能从成交单中提取到投资账户号码。",
                suggestion="检查 PDF 是否完整。"
            ))

        return findings

    def _ai_audit(self, contract: ContractData) -> tuple[list[AuditFinding], str]:
        """使用 OpenRouter 进行深度 AI 审核，返回简洁中文摘要"""
        import httpx

        c = contract
        prompt = f"""你是一位专业的金融合规审核专家。请用简洁的中文对以下股票成交单做总结分析，直接输出3-5句话的审核摘要，不要用JSON格式，不要分点列举，只需要自然段落文字。

成交单信息：
- 客户：{c.customer_name or '未知'} {c.customer_name_cn or ''}
- 股票：{c.stock_name or '未知'}（{c.stock_code or ''}），{c.stock_market or ''}市场
- 交易：{c.transaction_type or '未知'}，{c.quantity or 0}股，成交价 {c.avg_price_currency or ''} {c.avg_price or 0}
- 金额：交易金额 {c.total_amount_currency or ''} {c.total_amount or 0}，佣金 {c.commission if c.commission is not None else '未知'}，平台费 {c.platform_fee if c.platform_fee is not None else '未知'}，交收金额 {c.settlement_amount or 0}
- 日期：成交 {c.contract_date or '未知'}，交收 {c.settlement_date or '未知'}
- 备注：{c.remark_cn or c.remark or '无'}

请重点说明：费用是否豁免、交易是否合规、有无异常。语言简洁专业，使用简体中文。"""

        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "nvidia/nemotron-3-nano-30b-a3b:free",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
            },
            timeout=20,
        )

        response.raise_for_status()
        summary = response.json()["choices"][0]["message"]["content"].strip()
        return [], summary

    def _analyze_fee_waiver(self, c: ContractData, findings: list[AuditFinding]) -> dict:
        """分析费用豁免详情"""
        return {
            "commission_waived": c.commission == 0 if c.commission is not None else False,
            "platform_fee_waived": c.platform_fee == 0 if c.platform_fee is not None else False,
            "total_fees_saved": (c.commission or 0) + (c.platform_fee or 0),
            "waiver_currency": c.commission_currency or c.platform_fee_currency or "USD",
            "has_remark": bool(c.remark),
            "remark_text": c.remark or "",
            "remark_text_cn": c.remark_cn or "",
        }
