"""
月结单解析模块 — 从 ZA Bank 月结单中提取交易记录
"""
import re
from typing import Optional
from pydantic import BaseModel
import pdfplumber


class StatementTransaction(BaseModel):
    trade_date: Optional[str] = None
    settlement_date: Optional[str] = None
    description: Optional[str] = None
    stock_code: Optional[str] = None
    stock_name: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    commission: Optional[float] = None
    platform_fee: Optional[float] = None
    settlement_amount: Optional[float] = None
    transaction_amount: Optional[float] = None


class StatementData(BaseModel):
    account_number: Optional[str] = None
    customer_name: Optional[str] = None
    statement_period: Optional[str] = None
    transactions: list[StatementTransaction] = []
    raw_text: Optional[str] = None


class StatementParser:
    def parse(self, file_path: str) -> StatementData:
        raw_text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    raw_text += text + "\n"

        data = StatementData(raw_text=raw_text.strip())

        # 账户号码
        m = re.search(r'Account Number[^:]*:\s*(\d+)', raw_text)
        if m:
            data.account_number = m.group(1).strip()

        # 客户姓名
        m = re.search(r'^([A-Z]+(?:\s+[A-Z]+)+)\s+[一-鿿]', raw_text, re.MULTILINE)
        if m:
            data.customer_name = m.group(1).strip()

        # 结单期间
        m = re.search(r'(\d{2}\s+\w+\s+\d{4})\s*[—-]\s*(\d{2}\s+\w+\s+\d{4})', raw_text)
        if m:
            data.statement_period = f"{m.group(1)} — {m.group(2)}"

        # 解析 HK Market 交易记录
        data.transactions = self._parse_hk_transactions(raw_text)

        return data

    def _parse_hk_transactions(self, text: str) -> list[StatementTransaction]:
        transactions = []

        # 匹配交易行: 日期 日期 描述 数量 单价 金额
        pattern = re.compile(
            r'(\d{1,2}\s+\w{3}\s+\d{4})\s+(\d{1,2}\s+\w{3}\s+\d{4})\s+'
            r'((?:Regular-Invest\s+)?(?:BUY|SELL)[^\n]*?\n[^\n]+)\s+'
            r'([\d,]+)\s+([\d,.]+)\s+([\d,.]+)',
            re.MULTILINE
        )

        for m in pattern.finditer(text):
            desc = m.group(3).replace('\n', ' ').strip()
            stock_code = None
            stock_name = None

            code_match = re.search(r'(\d{5})\s+(.+?)(?:\s{2,}|$)', desc)
            if code_match:
                stock_code = code_match.group(1)
                stock_name = code_match.group(2).strip()

            tx = StatementTransaction(
                trade_date=m.group(1),
                settlement_date=m.group(2),
                description=desc,
                stock_code=stock_code,
                stock_name=stock_name,
                quantity=float(m.group(4).replace(',', '')),
                unit_price=float(m.group(5).replace(',', '')),
                transaction_amount=float(m.group(6).replace(',', '')),
            )

            # 提取费用
            fee_block = text[m.end():m.end()+500]
            commission_m = re.search(r'Commission[^\d]*([\d,.]+)', fee_block)
            if commission_m:
                tx.commission = float(commission_m.group(1).replace(',', ''))

            platform_m = re.search(r'Platform Fee[^\d]*([\d,.]+)', fee_block)
            if platform_m:
                tx.platform_fee = float(platform_m.group(1).replace(',', ''))

            settlement_m = re.search(r'Settlement\s+Amount\s+([\d,.]+)', fee_block)
            if settlement_m:
                tx.settlement_amount = float(settlement_m.group(1).replace(',', ''))

            transactions.append(tx)

        return transactions
