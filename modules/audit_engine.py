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
        """使用 OpenRouter Gemma 4 进行深度 AI 审核"""
        import httpx

        prompt = self._build_audit_prompt(contract)

        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "messages": [
                    {
                        "role": "user",
                        "content": f"""你是一位专业的金融交易审核专家，擅长审查股票成交单（Contract Note）。
你的职责是对成交单进行深度审核，包括但不限于：
1. 识别费用豁免/减免模式，判断是否正常
2. 检测潜在的合规风险
3. 发现数据异常或不一致
4. 提供专业的改进建议

请用 JSON 格式返回审核结果。

{prompt}"""
                    }
                ],
                "max_tokens": 2048,
            },
            timeout=60,
        )

        response.raise_for_status()
        result_text = response.json()["choices"][0]["message"]["content"]

        # 解析 AI 返回的 JSON
        try:
            # 提取 JSON 部分
            json_match = result_text
            if "```json" in result_text:
                json_match = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                json_match = result_text.split("```")[1].split("```")[0]

            ai_result = json.loads(json_match.strip())

            findings = []
            for f in ai_result.get("findings", []):
                findings.append(AuditFinding(
                    category=f.get("category", "compliance"),
                    severity=f.get("severity", "info"),
                    title=f.get("title", ""),
                    detail=f.get("detail", ""),
                    suggestion=f.get("suggestion", ""),
                ))

            summary = ai_result.get("summary", "AI 审核完成。")
            return findings, summary

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            # JSON 解析失败，返回原始分析文本
            return [
                AuditFinding(
                    category="compliance",
                    severity="info",
                    title="AI 深度分析结果",
                    detail=result_text[:1000],
                    suggestion=""
                )
            ], result_text[:500]

    def _build_audit_prompt(self, c: ContractData) -> str:
        """构建发送给 Claude 的审核提示"""
        return f"""请审核以下股票成交单，重点关注费用豁免、合规性和异常情况。

## 成交单信息

| 字段 | 值 |
|------|----|
| 客户姓名 | {c.customer_name or '未知'} ({c.customer_name_cn or ''}) |
| 投资账户 | {c.account_number or '未知'} |
| 股票 | {c.stock_name or '未知'} ({c.stock_code or ''}) |
| 市场 | {c.stock_market or '未知'} |
| 交易类别 | {c.transaction_type or '未知'} |
| 成交日期 | {c.contract_date or '未知'} |
| 成交价 | {c.avg_price_currency or ''} {c.avg_price or 0} |
| 股数 | {c.quantity or 0} |
| 交易金额 | {c.total_amount_currency or ''} {c.total_amount or 0} |
| 佣金 | {c.commission_currency or ''} {c.commission if c.commission is not None else '未知'} |
| 平台费 | {c.platform_fee_currency or ''} {c.platform_fee if c.platform_fee is not None else '未知'} |
| 交收金额 | {c.settlement_amount_currency or ''} {c.settlement_amount or 0} |
| 交收日期 | {c.settlement_date or '未知'} |
| 交易编号 | {c.order_reference or '未知'} |
| 备注 | {c.remark or '无'} |
| 备注(中文) | {c.remark_cn or '无'} |

## 审核要求

请从以下维度审核并返回 JSON：

1. **费用豁免分析** — 佣金和平台费是否被豁免？该豁免是否正常？是否存在"股票回赠"转换为"平台费豁免"的模式？
2. **合规性检查** — 小数股交易、跨境交易、客户适当性等是否合规？
3. **异常检测** — 金额是否一致？日期是否合理？是否存在不寻常的交易模式？
4. **数据质量** — 是否有缺失的关键字段？

请严格按以下 JSON 格式返回（不要包含其他文字）：

```json
{{
  "findings": [
    {{
      "category": "fee_waiver|compliance|anomaly|data_quality",
      "severity": "critical|warning|info",
      "title": "简洁的发现标题",
      "detail": "详细分析内容",
      "suggestion": "改进建议"
    }}
  ],
  "summary": "整体审核摘要（2-3句话）"
}}
```

备注原文: {c.raw_text[:500] if c.raw_text else '无'}"""

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
