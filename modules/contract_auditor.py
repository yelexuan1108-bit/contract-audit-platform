"""
Contract Note 条款审核模块
支持：股票 HK / 股票 US / VA 虚拟资产
自动识别文件类型、语言、市场
对照官方模板逐条核查重要提示
"""
import re
import json
from collections import Counter
from pathlib import Path
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


# 基金成交单英文条款 — 3条（所有交易类型通用）
FUND_EN_CLAUSES = [
    ("条款1", "All errors or discrepancies on this document should be reported to the Bank as soon as practicable"),
    ("条款2", "saving an electronic copy of this document in your own storage or print a hard copy"),
    ("条款3", "ZA Bank acts as agent in handling this transaction"),
]

# 基金成交单繁体中文条款
FUND_ZH_HK_CLAUSES = [
    ("条款1", "如此文件有任何錯漏，請盡快通知本行"),
    ("条款2", "你可考慮將此文件的電子副本儲存於個人存儲裝置"),
    ("条款3", "ZA Bank 以代理人的身份處理此交易"),
]

# 基金成交单简体中文条款
FUND_ZH_CN_CLAUSES = [
    ("条款1", "如此文件有任何错漏，请尽快通知本行"),
    ("条款2", "你可考虑将此文件的电子副本储存于个人存储装置"),
    ("条款3", "ZA Bank 以代理人的身份处理此交易"),
]


# 月结单「个人投资信息」核查项
# 检查月结单上是否存在这些固定识别/字段标签（名称 + 关键字）。
# 关键字统一使用英文（中英文模板均包含英文标签），避免繁体/简体差异。
# 通用字段：所有月结单子类型（monthly / bbInvest / southBound）均包含。
STATEMENT_PERSONAL_INFO_COMMON = [
    ("月结单标题", "Investment Account Monthly Statement"),
    ("结单日期", "Statement Date"),
    ("账户号码", "Account Number"),
    ("总金额", "Total Amount"),
    ("银行名称", "ZA Bank Limited"),
    ("银行地址", "Unit 1301,Level 13,IT Street,Cyberport 3,100 Cyberport Road"),
    ("银行网址", "bank.za.group"),
    ("重要提示标题", "Important Notice"),
    ("投资持仓", "Investment Holdings"),
    ("基金", "Fund"),
    ("已确认交易", "Confirmed Transaction"),
    ("基金处理中交易", "Fund Pending Transaction"),
    ("收益及费用摘要", "Income and Charges Summary"),
    ("持仓及份额变动", "Holdings Movement"),
    ("基金名称", "Fund Name"),
    ("期初结余", "Opening Balance"),
    ("期终结余", "Closing Balance"),
    ("币种", "Currency"),
    ("参考价", "Reference Price"),
    ("市值", "Market Value"),
    ("日期", "Date"),
    ("说明", "Description"),
    ("单位数目", "No. of Units"),
    ("单位价格", "Unit Price"),
    ("费用", "Fee"),
    ("金额", "Amount"),
]

# 仅「投资月结单」(monthly) 子类型包含股票/虚拟资产栏位
STATEMENT_PERSONAL_INFO_MONTHLY = [
    ("股票", "Stock"),
    ("美国市场", "US Market"),
    ("香港市场", "HK Market"),
    ("虚拟资产", "Virtual Asset"),
    ("虚拟资产平台", "SFC-Licensed Virtual Asset Trading Platform"),
    ("股票名称", "Stock Name"),
    ("虚拟资产名称及代码", "Virtual Asset Name and Code"),
    ("交易日期", "Trade Date"),
    ("交收日期", "Settlement Date"),
    ("数量/面值", "Quantity/Nominal"),
    ("红股", "Bonus Share"),
    ("目标公司", "Target Company"),
    ("存入/提取", "In/Out"),
]


# 基金成交单「个人投资信息」核查项
# 检查基金成交单上是否存在这些固定识别/字段标签（名称 + 关键字）。
# 关键字统一使用英文（中英文模板均包含英文标签），避免繁体/简体差异。
# 通用字段：所有基金交易类型（apply/redeem/deposit/takeout/divid/divid_share）均包含。
FUND_PERSONAL_INFO_COMMON = [
    ("银行名称", "ZA Bank Limited"),
    ("银行地址", "Unit 1301,Level 13,IT Street,Cyberport 3,100 Cyberport Road,Hong Kong"),
    ("银行网址", "bank.za.group"),
    ("成交单标题", "Investment Fund"),
    ("发出日期", "Issue Date"),
    ("账户号码", "Account Number"),
    ("基金名称", "Fund Name"),
    ("ISIN编码", "ISIN Code"),
    ("交易类别", "Transaction Type"),
    ("交易编号", "Transaction Reference"),
    ("重要提示标题", "Important Notice"),
]

# 各交易类型特有的字段标签
# apply   = 认购 (Subscription)
# redeem  = 赎回 (Redemption)
# deposit = 存入 (Deposit)
# takeout = 提取 (Withdrawal)
# divid        = 现金派息 (Cash Dividend)
# divid_share  = 单位派息 (Unit Dividend)
FUND_PERSONAL_INFO_BY_SUBTYPE = {
    "apply": [
        ("交易类别名称", "Subscription"),
        ("订单日期", "Order Date"),
        ("交易日期", "Dealing Date"),
        ("确认日期", "Confirmation Date"),
        ("认购金额", "Subscription Amount"),
        ("认购费", "Subscription Fee"),
        ("单位数目", "No. of Units"),
        ("单位价格", "Unit Price"),
    ],
    "redeem": [
        ("交易类别名称", "Redemption"),
        ("订单日期", "Order Date"),
        ("交易日期", "Dealing Date"),
        ("确认日期", "Confirmation Date"),
        ("赎回金额", "Redemption Amount"),
        ("赎回费", "Redemption Fee"),
        ("单位数目", "No. of Units"),
        ("单位价格", "Unit Price"),
    ],
    "deposit": [
        ("交易类别名称", "Deposit"),
        ("交易日期", "Dealing Date"),
        ("单位数目", "No. of Units"),
    ],
    "takeout": [
        ("交易类别名称", "Withdrawal"),
        ("交易日期", "Dealing Date"),
        ("单位数目", "No. of Units"),
    ],
    "divid": [
        ("交易类别名称", "Cash Dividend"),
        ("纪录日", "Record Date"),
        ("持有单位数目", "No. of Unit Holding"),
        ("每单位派息", "Dividend per Unit"),
        ("派发日", "Distribution Date"),
        ("已派发金额", "Dividend Amount Distributed"),
    ],
    "divid_share": [
        ("交易类别名称", "Unit Dividend"),
        ("纪录日", "Record Date"),
        ("持有单位数目", "No. of Unit Holding"),
        ("每单位派息", "Dividend per Unit"),
        ("派发日", "Distribution Date"),
        ("已派发单位数量", "Dividend Amount Distributed"),
    ],
}


# 股票成交单「个人信息」核查项
# 检查股票成交单上是否存在这些固定识别/字段标签（名称 + 关键字）。
# 关键字统一使用英文（中英文模板均包含英文标签），避免繁体/简体差异。
# 通用字段：所有股票子类型（order/orderHk/companyAction/companyActionHk/business/businessHk）均包含。
STOCK_PERSONAL_INFO_COMMON = [
    ("银行名称", "ZA Bank Limited"),
    ("银行地址", "Unit 1301,Level 13,IT Street,Cyberport 3,100 Cyberport Road"),
    ("银行网址", "bank.za.group"),
    ("发出日期", "Issue Date"),
    ("账户号码", "Investment Account Number"),
    ("股票名称", "Stock Name"),
    ("股票代码", "Stock Code"),
    ("股票市场", "Stock Market"),
    ("市场", "Market"),
    ("重要提示标题", "Important Notice"),
]

# 各股票子类型特有的字段标签
# order          = 股票成交单（美股 buy/sell）
# orderHk        = 股票成交单（港股 buy/sell）
# companyAction  = 公司行动通知（美股+港股）
# companyActionHk= 公司行动通知（纯港股）
# business       = 资金/股票转账、存入、派息预扣税等
# businessHk     = IPO 认购/分配
STOCK_PERSONAL_INFO_BY_SUBTYPE = {
    "order": [
        ("成交单标题", "Stock Contract Note"),
        ("交易类别", "Transaction Type"),
        ("成交日期", "Contract Date"),
        ("平均成交价", "Average Execution Price"),
        ("成交股数", "Execution Quantities"),
        ("交易金额", "Total Consideration Amount"),
        ("佣金金额", "Commission"),
        ("平台费", "Platform Fee"),
        ("交收金额", "Settlement Amount"),
        ("交收日期", "Settlement Date"),
        ("交易编号", "Order Reference"),
    ],
    "orderHk": [
        ("成交单标题", "Stock Contract Note"),
        ("香港市场", "HK Market"),
        ("交易类别", "Transaction Type"),
        ("成交日期", "Contract Date"),
        ("平均成交价", "Average Execution Price"),
        ("成交股数", "Execution Quantities"),
        ("交易金额", "Total Consideration Amount"),
        ("佣金金额", "Commission"),
        ("平台费", "Platform Fee"),
        ("印花税", "Stamp Duty"),
        ("交收金额", "Settlement Amount"),
        ("交收日期", "Settlement Date"),
        ("交易编号", "Order Reference"),
    ],
    "companyAction": [
        ("通知标题", "Corporate Action"),
        ("行动类别", "Event Type"),
        ("记录日", "Record Date"),
        ("持股数量", "Share Holdings"),
        ("分派日", "Payment Date"),
    ],
    "companyActionHk": [
        ("通知标题", "Corporate Action"),
        ("行动类别", "Event Type"),
        ("记录日", "Record Date"),
        ("持股数量", "Share Holdings"),
        ("分派日", "Payment Date"),
    ],
    "business": [
        ("行动类别", "Event Type"),
        ("执行日", "Effective Date"),
        ("交易编号", "Reference"),
    ],
    "businessHk": [
        ("类别", "Type"),
        ("认购数量", "Subscription Quantity"),
        ("分派日", "Payment Date"),
    ],
}


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
    stock_subtype: Optional[str] = None  # order / orderHk / companyAction / ...
    template_version: Optional[str] = None  # 模板版本号
    customer_name: Optional[str] = None
    account_number: Optional[str] = None
    contract_date: Optional[str] = None
    issue_date: Optional[str] = None
    # 日期校验
    date_check_result: Optional[str] = None  # pass / fail / skip
    date_check_note: Optional[str] = None
    # 条款检查
    en_clauses: list[ClauseCheck] = []
    zh_clauses: list[ClauseCheck] = []
    en_total: int = 0
    en_passed: int = 0
    zh_total: int = 0
    zh_passed: int = 0
    # Statement 个人投资信息核查
    personal_info: list[ClauseCheck] = []
    personal_info_total: int = 0
    personal_info_passed: int = 0
    overall: str = "pass"  # pass / fail
    issues: list[str] = []


# ============================================================
# 审核引擎
# ============================================================

class ContractAuditor:

    def audit(self, file_path: str, file_name: str, subtype: str = None) -> ContractAuditResult:
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
        contract_date = self._extract_date(raw_text)
        issue_date = self._extract_issue_date(raw_text)

        # Stock 自动识别子类型
        if doc_type in ("Stock-HK", "Stock-US", "Unknown") and not subtype:
            subtype = self._detect_stock_subtype(raw_text)

        # VA 自动识别子类型（buy/sale）
        if doc_type == "VA" and not subtype:
            subtype = "sale" if tx_type == "Sell" else "buy"

        # Statement 自动识别子类型
        if doc_type == "Statement" and not subtype:
            if "Southbound" in raw_text or "南向通" in raw_text:
                subtype = "southBound"
            else:
                subtype = "monthly"  # monthly 和 bbInvest 从PDF内容难以区分，默认 monthly

        # Fund 自动识别子类型（按交易类型）
        if doc_type == "Fund" and not subtype:
            subtype = self._detect_fund_subtype(raw_text)

        # 选择对应条款库
        en_clauses, zh_clauses = self._select_clauses(doc_type, language, subtype)

        # 获取模板版本
        template_version = self._get_template_version(doc_type, language, subtype)

        # 核查条款
        en_checks = self._check_clauses(raw_text, en_clauses, "EN")
        zh_checks = self._check_clauses(raw_text, zh_clauses, "ZH")

        # VA 分期成交字段为条件字段：仅在多笔分期成交时出现。
        # 单笔成交（无 Partial Execution）时对应信息已由「成交數量/平均成交價/交易金額」覆盖，标记为不适用。
        if doc_type == "VA" and "Partial Execution" not in raw_text:
            for c in zh_checks:
                if c.clause_num.removeprefix("ZH-") in ("条款22", "条款23", "条款24"):
                    c.result = "pass"
                    c.note = "单笔成交，无分期成交字段（不适用）"

        en_passed = sum(1 for c in en_checks if c.result == "pass")
        zh_passed = sum(1 for c in zh_checks if c.result == "pass")

        # 月结单：核查「个人投资信息」固定识别/字段标签
        # monthly 子类型包含股票/虚拟资产栏位；bbInvest / southBound 仅含基金栏位
        personal_info_checks = []
        if doc_type == "Statement":
            info_items = list(STATEMENT_PERSONAL_INFO_COMMON)
            if subtype == "monthly":
                info_items += STATEMENT_PERSONAL_INFO_MONTHLY
            personal_info_checks = self._check_clauses(raw_text, info_items, "INFO")
        elif doc_type == "Fund":
            # 基金成交单：核查个人投资信息（通用字段 + 交易类型特定字段）
            info_items = list(FUND_PERSONAL_INFO_COMMON)
            info_items += FUND_PERSONAL_INFO_BY_SUBTYPE.get(subtype or "apply", [])
            personal_info_checks = self._check_clauses(raw_text, info_items, "INFO")
        elif doc_type in ("Stock-HK", "Stock-US", "Unknown"):
            # 股票成交单：核查个人信息（通用字段 + 子类型特定字段）
            info_items = list(STOCK_PERSONAL_INFO_COMMON)
            info_items += STOCK_PERSONAL_INFO_BY_SUBTYPE.get(subtype or "order", [])
            personal_info_checks = self._check_clauses(raw_text, info_items, "INFO")
        personal_info_passed = sum(1 for c in personal_info_checks if c.result == "pass")

        issues = []
        for c in en_checks + zh_checks:
            if c.result == "fail":
                issues.append(f"{c.clause_num} ({c.keyword[:30]}...)")
        for c in personal_info_checks:
            if c.result == "fail":
                issues.append(f"{c.clause_num} ({c.keyword[:30]}...)")

        # 日期校验: contract/dealing date + N HK business days = issue date
        # Stock / VA 允许 T ~ T+2；Fund / Statement 严格 T+2
        date_allowed = (0, 1, 2) if doc_type in ("Stock-HK", "Stock-US", "VA", "Unknown") else (2,)
        date_check = self._validate_date(contract_date, issue_date, date_allowed)

        if date_check["result"] == "fail":
            issues.append(f"日期校验失败: {date_check['note']}")

        overall = "pass" if not issues else "fail"

        return ContractAuditResult(
            file_name=file_name,
            audit_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            doc_type=doc_type,
            language=language,
            transaction_type=tx_type,
            stock_subtype=subtype,
            template_version=template_version,
            customer_name=customer,
            account_number=account,
            contract_date=contract_date,
            issue_date=issue_date,
            date_check_result=date_check["result"],
            date_check_note=date_check["note"],
            en_clauses=en_checks,
            zh_clauses=zh_checks,
            en_total=len(en_checks),
            en_passed=en_passed,
            zh_total=len(zh_checks),
            zh_passed=zh_passed,
            personal_info=personal_info_checks,
            personal_info_total=len(personal_info_checks),
            personal_info_passed=personal_info_passed,
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
        if ("Investment Fund Contract Note" in text or "基金成交單" in text or "基金成交单" in text or
                "Investment Fund Deposit Advice" in text or "基金存入通知" in text or
                "Investment Fund Withdrawal Advice" in text or "基金提取通知" in text or
                "Investment Fund Dividend Advice" in text or "基金派息通知" in text):
            return "Fund"
        if "Monthly Statement" in text or "月結單" in text or "月结单" in text or "投資月結單" in text or "投资月结单" in text:
            return "Statement"
        if "Stock Contract Note" in text or "股票成交單" in text or "股票成交单" in text:
            if "HK Market" in text or "香港市場" in text or "香港市场" in text:
                return "Stock-HK"
            if "US Market" in text or "美國市場" in text or "美国市场" in text:
                return "Stock-US"
            return "Stock-HK"
        return "Unknown"

    def _detect_stock_subtype(self, text: str) -> str:
        """从 PDF 文本自动识别股票子类型"""
        # IPO 类（businessHk）
        if "IPO Allotment" in text or "新股分配" in text or "新股配售" in text:
            return "businessHk"
        # Corporate Action Advice
        if "Corporate Action Advice" in text or "公司行動通知書" in text or "公司行动通知书" in text:
            # 含 US 条款或 [For HK Stock] → companyAction（HK+US），否则 companyActionHk（纯港股）
            if ("All U.S. securities" in text or "U.S. securit" in text or
                    "[For HK Stock]" in text or "[港股適用]" in text or "[港股适用]" in text):
                return "companyAction"
            return "companyActionHk"
        # Money/Stock Transfer（business）
        if ("Money Transfer Advice" in text or "資金轉賬通知書" in text or "资金转账通知书" in text or
                "Stock Transfer Advice" in text or "股票轉賬通知書" in text or "股票转账通知书" in text or
                "Stock Deposit Advice" in text or "股票存入通知書" in text):
            return "business"
        # Stock Contract Note（buy/sell）— orderHk vs order
        if "Stock Contract Note" in text or "股票成交單" in text or "股票成交单" in text:
            if "HK Market 香港市場" in text or "HK Market香港市場" in text:
                return "orderHk"
            return "order"
        return "order"  # 默认

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
        # 基金交易类型
        if "Subscription" in text or "認購" in text or "认购" in text:
            return "Subscription"
        if "Redemption" in text or "贖回" in text or "赎回" in text:
            return "Redemption"
        if "Deposit" in text or "存入" in text:
            return "Deposit"
        if "Withdrawal" in text or "提取" in text:
            return "Withdrawal"
        if "Dividend" in text or "派息" in text:
            return "Dividend"
        return "N/A"

    def _detect_fund_subtype(self, text: str) -> str:
        """从 PDF 文本自动识别基金交易子类型。

        apply       → Subscription 认购
        redeem      → Redemption 赎回
        deposit     → Deposit 存入
        takeout     → Withdrawal 提取
        divid       → Cash Dividend 现金派息
        divid_share → Unit Dividend 单位派息
        """
        if "Unit Dividend" in text or "單位派息" in text or "单位派息" in text:
            return "divid_share"
        if "Cash Dividend" in text or "現金派息" in text or "现金派息" in text:
            return "divid"
        if "Redemption" in text or "贖回" in text or "赎回" in text:
            return "redeem"
        if "Deposit" in text or "存入" in text:
            return "deposit"
        if "Withdrawal" in text or "提取" in text:
            return "takeout"
        if "Subscription" in text or "認購" in text or "认购" in text:
            return "apply"
        return "apply"  # 默认认购

    def _extract_customer(self, text: str) -> Optional[str]:
        m = re.search(r'^([A-Z]+(?:\s+[A-Z]+)+)\s', text, re.MULTILINE)
        return m.group(1).strip() if m else None

    def _extract_account(self, text: str) -> Optional[str]:
        m = re.search(r'(?:Investment Account Number|投資賬戶號碼|投资账户号码)[^:：]*[：:]\s*(\d+)', text)
        return m.group(1).strip() if m else None

    def _extract_date(self, text: str) -> Optional[str]:
        # Contract Date（Stock/VA）
        m = re.search(r'(?:Contract Date|成交日期)\s*\n([^\n]+)', text)
        if m:
            return m.group(1).strip()
        # Dealing Date（Fund）
        m = re.search(r'(?:Dealing Date|交易日期)\s*\n([^\n]+)', text)
        return m.group(1).strip() if m else None

    def _extract_issue_date(self, text: str) -> Optional[str]:
        # Issue Date 發出日期: / Issue Date 发出日期:
        m = re.search(r'Issue Date[^:：]*[：:]\s*(\d{1,2}\s+\w{3}\s+\d{4})', text)
        return m.group(1).strip() if m else None

    def _validate_date(
        self,
        contract_date_str: Optional[str],
        issue_date_str: Optional[str],
        allowed_business_days: tuple = (2,),
    ) -> dict:
        """校验 contract/dealing date + N HK business days = issue date。

        - Stock / VA：允许 T / T+1 / T+2（ZA 在成交日后 0~2 个工作日发出均算通过）
        - Fund：严格 T+2
        """
        if not contract_date_str or not issue_date_str:
            missing = []
            if not contract_date_str:
                missing.append("Contract/Dealing Date")
            if not issue_date_str:
                missing.append("Issue Date")
            return {"result": "skip", "note": f"无法提取: {', '.join(missing)}"}

        from datetime import datetime as dt
        from modules.hk_holidays import add_hk_business_days

        try:
            # 解析 DD MMM YYYY 格式（如 "30 Jun 2026"）
            contract_d = dt.strptime(contract_date_str.strip(), "%d %b %Y").date()
        except ValueError:
            return {"result": "skip", "note": f"无法解析 Contract Date: {contract_date_str}"}

        try:
            issue_d = dt.strptime(issue_date_str.strip(), "%d %b %Y").date()
        except ValueError:
            return {"result": "skip", "note": f"无法解析 Issue Date: {issue_date_str}"}

        valid_dates = [add_hk_business_days(contract_d, n) for n in sorted(allowed_business_days)]

        if issue_d in valid_dates:
            if len(valid_dates) == 1:
                note = f"{contract_d.strftime('%d %b %Y')} + 2 BD = {valid_dates[0].strftime('%d %b %Y')} = Issue Date ✓"
            else:
                note = (
                    f"{contract_d.strftime('%d %b %Y')} + 0~2 BD 允许 "
                    f"{valid_dates[0].strftime('%d %b %Y')}~{valid_dates[-1].strftime('%d %b %Y')}，"
                    f"实际 {issue_d.strftime('%d %b %Y')} ✓"
                )
            return {"result": "pass", "note": note}

        expected_note = " / ".join(d.strftime("%d %b %Y") for d in valid_dates)
        return {
            "result": "fail",
            "note": f"期望 {expected_note} 之一，实际 {issue_d.strftime('%d %b %Y')}",
        }

    def _load_clauses_from_json(self):
        json_path = Path(__file__).parent.parent / "data" / "clauses.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                return data
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def _get_template_version(self, doc_type: str, language: str, subtype: str = None) -> Optional[str]:
        """从 clauses.json 的 _meta 字段读取模板版本"""
        clauses_data = self._load_clauses_from_json()
        if not clauses_data:
            return None
        zh_key = "zh_hk" if language == "繁体" else "zh_cn"
        try:
            if doc_type in ("Stock-HK", "Stock-US", "Unknown"):
                st = subtype or "order"
                meta = clauses_data.get("Stock", {}).get(st, {}).get("_meta", {})
                # 返回中文版本（主要），英文版本（次要）
                zh_ver = meta.get(zh_key, {}).get("version")
                en_ver = meta.get("en", {}).get("version")
                return zh_ver or en_ver
            elif doc_type == "Fund":
                meta = clauses_data.get("Fund", {}).get("_meta", {})
                return meta.get(zh_key, {}).get("version")
            elif doc_type == "Statement":
                st = subtype or "monthly"
                meta = clauses_data.get("Statement", {}).get(st, {}).get("_meta", {})
                return meta.get(zh_key, {}).get("version")
            elif doc_type == "VA":
                st = subtype or "buy"
                meta = clauses_data.get("VA", {}).get(st, {}).get("_meta", {})
                return meta.get(zh_key, {}).get("version")
        except (AttributeError, TypeError):
            pass
        return None

    def _select_clauses(self, doc_type: str, language: str, subtype: str = None):
        clauses_data = self._load_clauses_from_json()
        zh_key = "zh_hk" if language == "繁体" else "zh_cn"

        if clauses_data:
            # Stock 产品：Important Notice 重要提示 10 条（英文 + 中文），
            # 字段固定信息（英文 + 中文 + 子类型字段）由 STOCK_PERSONAL_INFO 核查，
            # 因此 Important Notice 一律使用硬编码常量，与月结单/基金渲染一致。
            if doc_type in ("Stock-HK", "Stock-US", "Unknown"):
                en = STOCK_EN_CLAUSES
                zh = STOCK_ZH_HK_CLAUSES if language == "繁体" else STOCK_ZH_CN_CLAUSES
                return en, zh

            # Fund: Important Notice 重要提示 3 条（英文 + 中文），
            # 条款库中的 Fund 仅含页眉/页脚/字段固定信息（由 FUND_PERSONAL_INFO 核查），
            # 因此 Important Notice 一律使用硬编码常量，与月结单渲染一致。
            if doc_type == "Fund":
                en = FUND_EN_CLAUSES
                zh = FUND_ZH_HK_CLAUSES if language == "繁体" else FUND_ZH_CN_CLAUSES
                return en, zh

            # VA: 嵌套子类型（无 en）
            if doc_type == "VA" and "VA" in clauses_data:
                va_data = clauses_data["VA"]
                # 检测新格式（嵌套子类型）还是旧格式（直接有 zh_hk）
                if "zh_hk" in va_data:
                    # 旧格式
                    en = [(c[0], c[1]) for c in va_data.get("en", [])]
                    zh = [(c[0], c[1]) for c in va_data.get(zh_key, [])]
                    return en, zh
                # 新格式：按子类型
                st = subtype or "buy"
                if st in va_data:
                    en = [(c[0], c[1]) for c in va_data[st].get("en", [])]
                    zh = [(c[0], c[1]) for c in va_data[st].get(zh_key, [])]
                    return en, zh

            # Statement: 嵌套子类型（无 en 顶层）
            # 条款库单列存放：前 9 条为页眉/页脚/字段固定信息（由 STATEMENT_PERSONAL_INFO 核查），
            # 其余为 Important Notice 重要提示（英文在前、中文在后），按关键字是否含中文拆分。
            if doc_type == "Statement" and "Statement" in clauses_data:
                stmt_data = clauses_data["Statement"]
                if "zh_hk" in stmt_data:
                    # 旧格式
                    raw = [(c[0], c[1]) for c in stmt_data.get(zh_key, [])]
                else:
                    # 新格式：按子类型
                    st = subtype or "monthly"
                    raw = [(c[0], c[1]) for c in stmt_data.get(st, {}).get(zh_key, [])]
                # 跳过前 9 条页眉/页脚固定信息
                notice = raw[9:]
                en = [(n, k) for n, k in notice if not re.search(r"[\u4e00-\u9fff]", k)]
                zh = [(n, k) for n, k in notice if re.search(r"[\u4e00-\u9fff]", k)]
                return en, zh

        # 回退到硬编码常量
        if doc_type == "VA":
            en = []  # VA 不检查英文条款
            zh = VA_ZH_HK_CLAUSES if language == "繁体" else VA_ZH_CN_CLAUSES
        elif doc_type == "Fund":
            en = FUND_EN_CLAUSES
            zh = FUND_ZH_HK_CLAUSES if language == "繁体" else FUND_ZH_CN_CLAUSES
        elif doc_type == "Statement":
            en = []  # Statement 不检查英文条款
            zh = []  # 无硬编码条款，需从 clauses.json 导入
        else:
            en = STOCK_EN_CLAUSES
            zh = STOCK_ZH_HK_CLAUSES if language == "繁体" else STOCK_ZH_CN_CLAUSES
        return en, zh

    def _normalized_variants(self, text: str) -> list:
        """生成用于匹配的候选文本（去除所有空白后）。

        PDF 提取的正文会被每页页眉/页脚插入打断，导致跨页长条款无法连续匹配。
        因此除完整文本外，额外生成一份「去除重复行（页眉/页脚）与页码行」的变体。
        条款 1-9 检查页眉/页脚本身，靠完整文本命中；跨页长条款靠变体命中。
        """
        variants = [re.sub(r"\s+", "", text)]

        lines = text.split("\n")
        norm_lines = [re.sub(r"\s+", "", ln) for ln in lines]
        counts = Counter(norm_lines)
        kept = [
            nl for nl in norm_lines
            if counts[nl] < 2 and not re.fullmatch(r"P\.\d+of\d+", nl)
        ]
        variants.append("".join(kept))
        return variants

    def _plural_variants(self, seg: str) -> set:
        """生成英文单词单复数容忍变体（如 Quantity/Quantities），去除空白后返回候选集。"""
        seg = re.sub(r"\s+", "", seg)
        candidates = {seg}
        for plural, singular in (("Quantities", "Quantity"), ("quantities", "quantity")):
            candidates.add(seg.replace(plural, singular))
            candidates.add(seg.replace(singular, plural))
        return candidates

    def _check_clauses(self, text: str, clauses: list, lang: str) -> list[ClauseCheck]:
        results = []
        variants = self._normalized_variants(text)
        for name, keyword in clauses:
            # 双语标签（EN\nZH）在 PDF 中常被值单元格隔开（EN / 值 / ZH），
            # 不能按整体连续匹配，需逐段独立匹配。
            segments = [s for s in keyword.split("\n") if re.sub(r"\s+", "", s)]
            if len(segments) > 1:
                found = all(
                    any(c in v for c in self._plural_variants(seg) for v in variants)
                    for seg in segments
                )
            else:
                found = any(
                    c in v for c in self._plural_variants(keyword) for v in variants
                )
            results.append(ClauseCheck(
                clause_num=f"{lang}-{name}",
                keyword=keyword,
                result="pass" if found else "fail",
                note="条款存在" if found else f"条款缺失: {keyword[:50]}",
            ))
        return results
