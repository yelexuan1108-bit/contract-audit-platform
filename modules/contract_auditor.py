"""
Contract Note 条款审核模块
支持：股票 HK / 股票 US / VA 虚拟资产
自动识别文件类型、语言、市场
对照官方模板逐条核查重要提示
"""
import re
from typing import Optional
from pydantic import BaseModel
import pdfplumber


# ============================================================
# 官方模板条款库
# ============================================================

# 股票成交单（HK + US）英文条款 — 10条完全一致
STOCK_EN_CLAUSES = [
    ("条款1", "reported to the Bank within 90 days from the issue date"),
    ("条款2", "saving an electronic copy of this document in your own storage or printing a hard copy"),
    ("条款3", "ZA Bank acts as agent in handling this transaction"),
    ("条款4", "relevant handling fees will be charged on the same date as the effective date of the relevant corporate action"),
    ("条款5", "securities in your account are held in the name or to the order of ZA Bank Limited on behalf of you"),
    ("条款6", "All U.S. securities transactions are executed by third party execution brokers"),
    ("条款7", "unit price of the HK securities transaction or the U.S. securities transactions"),
    ("条款8", "[For HK Stock] The Bank confirms that the stamp duty has been or will be paid"),
    ("条款9", "[For Corporate action] The above corporate action is subject to the conditions"),
    ("条款10", "fee schedule in ZA Bank website https://bank.za.group"),
]

# 股票成交单繁体中文条款
STOCK_ZH_HK_CLAUSES = [
    ("条款1", "須於此文件發出後90 日內通知本行"),
    ("条款2", "你可考慮將此文件的電子副本儲存於個人存儲裝置"),
    ("条款3", "ZA Bank以代理人的身份處理此交易"),
    ("条款4", "有關手續費會在相關公司行動生效當日同日收取"),
    ("条款5", "你的戶口内之證券以眾安銀行有限公司的名義或按其指示代你持有"),
    ("条款6", "所有美國證券交易均由第三方證券經紀商以代理人名義透過紐約證券交易所"),
    ("条款7", "此文件內的香港證券交易或美國證券交易"),
    ("条款8", "[港股適用] 本行確認已/將付印花稅予香港聯合交易所有限公司"),
    ("条款9", "[公司行動適用]上述公司行動受限於公司公告中規定的條款"),
    ("条款10", "有關適用的費用和收費，請參見本行網站上的費率表 https://bank.za.group"),
]

# 股票成交单简体中文条款
STOCK_ZH_CN_CLAUSES = [
    ("条款1", "需在此文件发出后90日内通知本行"),
    ("条款2", "你可考虑将此文件的电子副本存储于个人存储设备"),
    ("条款3", "众安银行以代理人的身份处理此交易"),
    ("条款4", "有关手续费会在相关公司行动生效当日同日收取"),
    ("条款5", "你的户口内的证券以众安银行有限公司的名义或按其指示代你持有"),
    ("条款6", "所有美国证券交易均由第三方证券经纪商以代理人名义透过纽约证券交易所"),
    ("条款7", "此文件内的香港证券交易或美国证券交易"),
    ("条款8", "[港股适用] 本行确认已/将支付印花税给香港联合交易所有限公司"),
    ("条款9", "[公司行动适用]上述公司行动受限于公司公告中规定的条款"),
    ("条款10", "有关适用的费用和收费，请参见本行网站上的费率表 https://bank.za.group"),
]

# VA 英文条款
VA_EN_CLAUSES = [
    ("条款1", "reported to the Bank within 90 days from the issue date"),
    ("条款2", "All virtual asset transactions are executed by third-party virtual asset trading platform operator"),
    ("条款3", "this document also serves as a receipt for client virtual assets received by the Bank"),
    ("条款4", "Client assets received or held outside Hong Kong are subject to the applicable laws"),
    ("条款5", "Client virtual assets may not enjoy the same protection as that conferred on"),
    ("条款6", "saving an electronic copy of this document in your own storage or printing a hard copy"),
    ("条款7", "ZA Bank acts as agent in handling this transaction"),
    ("条款8", "refer to the fee schedule in the Bank"),
    ("条款9", "the English version shall prevail"),
    ("条款10", "all your personal information with the Bank is accurate and updated"),
]

# VA 繁体中文条款
VA_ZH_HK_CLAUSES = [
    ("条款1", "須於此文件發出後90日內通知本行"),
    ("条款2", "所有虛擬資產的交易均是由獲證監會發牌的第三方虛擬資產交易平台進行"),
    ("条款3", "本文件亦作本行代閣下收取的任何有關本文件列明之虛擬資產"),
    ("条款4", "在香港以外地方收取或持有的客戶資產"),
    ("条款5", "客戶虛擬資產可能不會享有在《證券及期貨條例》"),
    ("条款6", "閣下可考慮將此文件的電子副本儲存於個人存儲裝置"),
    ("条款7", "眾安銀行以代理人的身份處理此交易"),
    ("条款8", "有關適用的費用和收費，請參見本行網站上的費率表"),
    ("条款9", "若中文版本與英文版本有異，一概以英文版本為準"),
    ("条款10", "閣下確認向本行提供的個人資料為準確及最新"),
]

# VA 简体中文条款
VA_ZH_CN_CLAUSES = [
    ("条款1", "须于此文件发出后90日内通知本行"),
    ("条款2", "所有虚拟资产的交易均是由获证监会发牌的第三方虚拟资产交易平台进行"),
    ("条款3", "本文件亦作本行代阁下收取的任何有关本文件列明之虚拟资产"),
    ("条款4", "在香港以外地方收取或持有的客户资产"),
    ("条款5", "客户虚拟资产可能不会享有在《证券及期货条例》"),
    ("条款6", "阁下可考虑将此文件的电子副本储存于个人存储装置"),
    ("条款7", "众安银行以代理人的身份处理此交易"),
    ("条款8", "有关适用的费用和收费，请参见本行网站上的费率表"),
    ("条款9", "若中文版本与英文版本有异，一概以英文版本为准"),
    ("条款10", "阁下确认向本行提供的个人资料为准确及最新"),
]


# ============================================================
# 数据模型
# ============================================================

class ClauseCheck(BaseModel):
    clause_num: str
    keyword: str
    result: str   # pass / fail
    note: str = ""


class ContractAuditResult(BaseModel):
    file_name: str
    audit_time: str
    doc_type: str        # Stock-HK / Stock-US / VA / Unknown
    language: str        # 繁体 / 简体
    transaction_type: str  # Buy / Sell / N/A
    customer_name: Optional[str] = None
    account_number: Optional[str] = None
    contract_date: Optional[str] = None
    # 条款检查
    en_clauses: list[ClauseCheck] = []
    zh_clauses: list[ClauseCheck] = []
    en_total: int = 0
    en_passed: int = 0
    zh_total: int = 0
    zh_passed: int = 0
    overall: str = "pass"  # pass / fail
    issues: list[str] = []


# ============================================================
# 审核引擎
# ============================================================

class ContractAuditor:

    def audit(self, file_path: str, file_name: str) -> ContractAuditResult:
        from datetime import datetime

        # 提取文本
        raw_text = self._extract_text(file_path)

        # 识别文件属性
        doc_type = self._detect_doc_type(raw_text)
        language = self._detect_language(raw_text)
        tx_type  = self._detect_tx_type(raw_text)

        # 提取基本信息
        customer  = self._extract_customer(raw_text)
        account   = self._extract_account(raw_text)
        date      = self._extract_date(raw_text)

        # 选择对应条款库
        en_clauses, zh_clauses = self._select_clauses(doc_type, language)

        # 核查条款
        en_checks = self._check_clauses(raw_text, en_clauses, "EN")
        zh_checks = self._check_clauses(raw_text, zh_clauses, "ZH")

        en_passed = sum(1 for c in en_checks if c.result == "pass")
        zh_passed = sum(1 for c in zh_checks if c.result == "pass")

        issues = []
        for c in en_checks + zh_checks:
            if c.result == "fail":
                issues.append(f"{c.clause_num} ({c.keyword[:30]}...)")

        overall = "pass" if not issues else "fail"

        return ContractAuditResult(
            file_name=file_name,
            audit_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            doc_type=doc_type,
            language=language,
            transaction_type=tx_type,
            customer_name=customer,
            account_number=account,
            contract_date=date,
            en_clauses=en_checks,
            zh_clauses=zh_checks,
            en_total=len(en_checks),
            en_passed=en_passed,
            zh_total=len(zh_checks),
            zh_passed=zh_passed,
            overall=overall,
            issues=issues,
        )

    def _extract_text(self, file_path: str) -> str:
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        return text.strip()

    def _detect_doc_type(self, text: str) -> str:
        if "Virtual Asset Contract Note" in text or "虛擬資產成交單" in text or "虚拟资产成交单" in text:
            return "VA"
        if "Stock Contract Note" in text or "股票成交單" in text or "股票成交单" in text:
            # 区分 HK / US 市场
            if "HK Market" in text or "香港市場" in text or "香港市场" in text:
                return "Stock-HK"
            if "US Market" in text or "美國市場" in text or "美国市场" in text:
                return "Stock-US"
            return "Stock-HK"  # 默认HK
        return "Unknown"

    def _detect_language(self, text: str) -> str:
        trad = "虛擬資產類別數量編號賬戶發佣費額幣種戶口閣下"
        simp = "虚拟资产类别数量编号账户发佣费额币种户口阁下"
        t = sum(1 for c in trad if c in text)
        s = sum(1 for c in simp if c in text)
        return "繁体" if t >= s else "简体"

    def _detect_tx_type(self, text: str) -> str:
        if "Buy/買入" in text or "Buy/买入" in text:
            return "Buy"
        if "Sell/賣出" in text or "Sell/卖出" in text:
            return "Sell"
        return "N/A"

    def _extract_customer(self, text: str) -> Optional[str]:
        m = re.search(r'^([A-Z]+(?:\s+[A-Z]+)+)\s', text, re.MULTILINE)
        return m.group(1).strip() if m else None

    def _extract_account(self, text: str) -> Optional[str]:
        m = re.search(r'(?:Investment Account Number|投資賬戶號碼|投资账户号码)[^:：]*[：:]\s*(\d+)', text)
        return m.group(1).strip() if m else None

    def _extract_date(self, text: str) -> Optional[str]:
        m = re.search(r'(?:Contract Date|成交日期)\s*\n([^\n]+)', text)
        return m.group(1).strip() if m else None

    def _select_clauses(self, doc_type: str, language: str):
        if doc_type == "VA":
            en = VA_EN_CLAUSES
            zh = VA_ZH_HK_CLAUSES if language == "繁体" else VA_ZH_CN_CLAUSES
        else:
            en = STOCK_EN_CLAUSES
            zh = STOCK_ZH_HK_CLAUSES if language == "繁体" else STOCK_ZH_CN_CLAUSES
        return en, zh

    def _check_clauses(self, text: str, clauses: list, lang: str) -> list[ClauseCheck]:
        results = []
        for name, keyword in clauses:
            found = keyword in text
            results.append(ClauseCheck(
                clause_num=f"{lang}-{name}",
                keyword=keyword,
                result="pass" if found else "fail",
                note="条款存在" if found else f"条款缺失: {keyword[:50]}",
            ))
        return results
