"""
VA 成交单审核模块
- 自动识别繁体/简体
- 自动识别买入/卖出
- 对照官方模板检查条款完整性
"""
import re
from typing import Optional
from pydantic import BaseModel
import pdfplumber


# ===== 官方模板条款 =====
# 英文条款（买卖相同）
EN_CLAUSES = [
    "Any errors or discrepancies in this document should be reported to the Bank within 90 days from the issue date.",
    "All virtual asset transactions are executed by third-party virtual asset trading platform operator(s) licensed by the Securities and Futures Commission.",
    "For the avoidance of doubt, this document also serves as a receipt for client virtual assets received by the Bank on your behalf",
    "Client assets received or held outside Hong Kong are subject to the applicable laws and regulations of the relevant overseas jurisdiction",
    "Client virtual assets may not enjoy the same protection as that conferred on",
    "You may consider saving an electronic copy of this document",
    "ZA Bank acts as agent in handling this transaction.",
    "For details of applicable fees and charges, please refer to the fee schedule",
    "In the event of discrepancies between the Chinese and English versions, the English version shall prevail.",
    "You confirm that all your personal information with the Bank is accurate and updated.",
]

# 繁体中文条款
ZH_HK_CLAUSES = [
    "如此文件有任何錯漏或不符，須於此文件發出後90日內通知本行",
    "所有虛擬資產的交易均是由獲證監會發牌的第三方虛擬資產交易平台進行",
    "為免生疑問，本文件亦作本行代閣下收取的任何有關本文件列明之虛擬資產",
    "在香港以外地方收取或持有的客戶資產",
    "客戶虛擬資產可能不會享有在《證券及期貨條例》",
    "閣下可考慮將此文件的電子副本儲存於個人存儲裝置",
    "眾安銀行以代理人的身份處理此交易",
    "有關適用的費用和收費，請參見本行網站上的費率表",
    "若中文版本與英文版本有異，一概以英文版本為準",
    "閣下確認向本行提供的個人資料為準確及最新",
]

# 简体中文条款
ZH_CN_CLAUSES = [
    "如此文件有任何错漏或不符，须于此文件发出后90日内通知本行",
    "所有虚拟资产的交易均是由获证监会发牌的第三方虚拟资产交易平台进行",
    "为免生疑问，本文件亦作本行代阁下收取的任何有关本文件列明之虚拟资产",
    "在香港以外地方收取或持有的客户资产",
    "客户虚拟资产可能不会享有在《证券及期货条例》",
    "阁下可考虑将此文件的电子副本储存于个人存储装置",
    "众安银行以代理人的身份处理此交易",
    "有关适用的费用和收费，请参见本行网站上的费率表",
    "若中文版本与英文版本有异，一概以英文版本为准",
    "阁下确认向本行提供的个人资料为准确及最新",
]

# 必须存在的字段标签（繁体）
REQUIRED_FIELDS_HK = [
    "Virtual Asset Name", "虛擬資產名稱",
    "Virtual Asset Code", "虛擬資產代碼",
    "SFC-Licensed Virtual Asset Trading Platform", "證監會持牌虛擬資產交易平台",
    "Transaction Type", "交易類別",
    "Contract Date", "成交日期",
    "Average Execution Price", "平均成交價",
    "Execution Quantities", "成交數量",
    "Total Consideration Amount", "交易金額",
    "Commission", "佣金金額",
    "Platform Fee", "平台費",
    "Settlement Amount", "交收金額",
    "Settlement Date", "交收日期",
    "Order Reference", "交易編號",
]

# 必须存在的字段标签（简体）
REQUIRED_FIELDS_CN = [
    "Virtual Asset Name", "虚拟资产名称",
    "Virtual Asset Code", "虚拟资产代码",
    "SFC-Licensed Virtual Asset Trading Platform", "证监会持牌虚拟资产交易平台",
    "Transaction Type", "交易类别",
    "Contract Date", "成交日期",
    "Average Execution Price", "平均成交价",
    "Execution Quantities", "成交数量",
    "Total Consideration Amount", "交易金额",
    "Commission", "佣金金额",
    "Platform Fee", "平台费",
    "Settlement Amount", "交收金额",
    "Settlement Date", "交收日期",
    "Order Reference", "交易编号",
]


class VACheckItem(BaseModel):
    category: str
    item: str
    result: str   # pass / fail / warning
    detail: str = ""


class VACheckResult(BaseModel):
    file_name: str
    audit_time: str
    language: str        # 繁体 / 简体
    transaction_type: str  # Buy / Sell
    customer_name: Optional[str] = None
    account_number: Optional[str] = None
    asset_name: Optional[str] = None
    asset_code: Optional[str] = None
    platform: Optional[str] = None
    contract_date: Optional[str] = None
    checks: list[VACheckItem] = []
    total: int = 0
    passed: int = 0
    failed: int = 0
    overall: str = "pass"  # pass / fail


class VAChecker:
    def check(self, file_path: str, file_name: str) -> VACheckResult:
        from datetime import datetime

        # 提取文本
        raw_text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    raw_text += t + "\n"

        checks = []

        # 1. 识别语言
        language = self._detect_language(raw_text)
        checks.append(VACheckItem(
            category="文件识别",
            item="语言识别",
            result="pass",
            detail=f"识别为{language}"
        ))

        # 2. 识别交易类型
        tx_type = self._detect_tx_type(raw_text)
        checks.append(VACheckItem(
            category="文件识别",
            item="交易类型识别",
            result="pass",
            detail=f"识别为 {tx_type}"
        ))

        # 3. 识别文件类型
        is_va = "Virtual Asset Contract Note" in raw_text or "虛擬資產成交單" in raw_text or "虚拟资产成交单" in raw_text
        checks.append(VACheckItem(
            category="文件识别",
            item="VA成交单确认",
            result="pass" if is_va else "fail",
            detail="确认为VA成交单" if is_va else "未识别为VA成交单，请确认文件类型"
        ))

        # 4. 检查必填字段
        required_fields = REQUIRED_FIELDS_HK if language == "繁体" else REQUIRED_FIELDS_CN
        for field in required_fields:
            found = field in raw_text
            checks.append(VACheckItem(
                category="必填字段",
                item=field,
                result="pass" if found else "fail",
                detail="字段存在" if found else "字段缺失"
            ))

        # 5. 检查英文条款
        for i, clause in enumerate(EN_CLAUSES):
            key = clause[:40]
            found = key in raw_text
            checks.append(VACheckItem(
                category="英文条款",
                item=f"条款 {i+1}",
                result="pass" if found else "fail",
                detail=f"{'✓ 存在' if found else '✗ 缺失'}: {clause[:60]}..."
            ))

        # 6. 检查中文条款
        cn_clauses = ZH_HK_CLAUSES if language == "繁体" else ZH_CN_CLAUSES
        for i, clause in enumerate(cn_clauses):
            key = clause[:15]
            found = key in raw_text
            checks.append(VACheckItem(
                category="中文条款",
                item=f"条款 {i+1}",
                result="pass" if found else "fail",
                detail=f"{'✓ 存在' if found else '✗ 缺失'}: {clause[:40]}..."
            ))

        # 7. 金额一致性校验
        total_m = re.search(r'Total Consideration Amount[^\d]*([\d,]+\.\d+)', raw_text)
        commission_m = re.search(r'Commission[^\d]*([\d,]+\.\d+)', raw_text)
        platform_m = re.search(r'Platform Fee[^\d]*([\d,]+\.\d+)', raw_text)
        settlement_m = re.search(r'Settlement Amount[^\d]*([\d,]+\.\d+)', raw_text)

        if total_m and commission_m and platform_m and settlement_m:
            total = float(total_m.group(1).replace(',', ''))
            commission = float(commission_m.group(1).replace(',', ''))
            platform = float(platform_m.group(1).replace(',', ''))
            settlement = float(settlement_m.group(1).replace(',', ''))
            expected = total + commission + platform
            ok = abs(expected - settlement) < 0.10
            checks.append(VACheckItem(
                category="金额校验",
                item="交易金额 + 佣金 + 平台费 = 交收金额",
                result="pass" if ok else "fail",
                detail=f"{total} + {commission} + {platform} = {expected:.2f}，交收金额 {settlement}{'（一致）' if ok else '（不一致）'}"
            ))
        else:
            checks.append(VACheckItem(
                category="金额校验",
                item="金额完整性",
                result="warning",
                detail="部分金额字段未能提取，无法校验"
            ))

        # 统计
        passed = sum(1 for c in checks if c.result == "pass")
        failed = sum(1 for c in checks if c.result == "fail")
        overall = "pass" if failed == 0 else "fail"

        # 提取基本信息
        customer_m = re.search(r'^([A-Z]+(?:\s+[A-Z]+)+)\s+[^\n]*Issue Date', raw_text, re.MULTILINE)
        account_m = re.search(r'Investment Account Number[^:]*:\s*(\d+)', raw_text)
        asset_m = re.search(r'Virtual Asset Name[^\n]*\n([^\n]+)', raw_text)
        code_m = re.search(r'Virtual Asset Code[^\n]*\n([^\n]+)', raw_text)
        platform_name_m = re.search(r'SFC-Licensed[^\n]*\n([^\n]+)', raw_text)
        date_m = re.search(r'Contract Date[^\n]*\n([^\n]+)', raw_text)

        from datetime import datetime
        return VACheckResult(
            file_name=file_name,
            audit_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            language=language,
            transaction_type=tx_type,
            customer_name=customer_m.group(1).strip() if customer_m else None,
            account_number=account_m.group(1).strip() if account_m else None,
            asset_name=asset_m.group(1).strip() if asset_m else None,
            asset_code=code_m.group(1).strip() if code_m else None,
            platform=platform_name_m.group(1).strip() if platform_name_m else None,
            contract_date=date_m.group(1).strip() if date_m else None,
            checks=checks,
            total=len(checks),
            passed=passed,
            failed=failed,
            overall=overall,
        )

    def _detect_language(self, text: str) -> str:
        # 繁体特有字
        trad_chars = "虛擬資產類別數量編號賬戶發佣費額幣種"
        simp_chars = "虚拟资产类别数量编号账户发佣费额币种"
        trad_count = sum(1 for c in trad_chars if c in text)
        simp_count = sum(1 for c in simp_chars if c in text)
        return "繁体" if trad_count >= simp_count else "简体"

    def _detect_tx_type(self, text: str) -> str:
        if "Buy/買入" in text or "Buy/买入" in text:
            return "Buy（买入）"
        elif "Sell/賣出" in text or "Sell/卖出" in text:
            return "Sell（卖出）"
        return "未知"
