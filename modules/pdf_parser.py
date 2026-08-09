"""
PDF 解析模块 — 从 ZA Bank 股票成交单中提取结构化数据
支持 PyPDF2 + pdfplumber 双引擎解析
"""
import re
from typing import Optional
from pydantic import BaseModel
import pdfplumber


class ContractData(BaseModel):
    """成交单结构化数据模型"""
    # 客户信息
    customer_name: Optional[str] = None
    customer_name_cn: Optional[str] = None
    account_number: Optional[str] = None
    address: Optional[str] = None

    # 股票信息
    stock_name: Optional[str] = None
    stock_code: Optional[str] = None
    stock_market: Optional[str] = None

    # 交易信息
    transaction_type: Optional[str] = None      # Buy/Sell
    contract_date: Optional[str] = None
    avg_price: Optional[float] = None
    avg_price_currency: Optional[str] = None
    quantity: Optional[float] = None
    total_amount: Optional[float] = None
    total_amount_currency: Optional[str] = None

    # 费用信息 — 核心审核字段
    commission: Optional[float] = None
    commission_currency: Optional[str] = None
    platform_fee: Optional[float] = None
    platform_fee_currency: Optional[str] = None
    settlement_amount: Optional[float] = None
    settlement_amount_currency: Optional[str] = None

    # 结算信息
    settlement_date: Optional[str] = None
    issue_date: Optional[str] = None
    order_reference: Optional[str] = None

    # 备注
    remark: Optional[str] = None
    remark_cn: Optional[str] = None

    # 原始全文（供 AI 审核用）
    raw_text: Optional[str] = None


class PDFParser:
    """ZA Bank 成交单 PDF 解析器"""

    def parse(self, file_path: str) -> ContractData:
        """解析 PDF 文件，返回结构化数据"""
        raw_text = self._extract_text(file_path)
        return self._parse_fields(raw_text)

    def _extract_text(self, file_path: str) -> str:
        """从 PDF 提取纯文本"""
        full_text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
        return full_text.strip()

    def _parse_fields(self, text: str) -> ContractData:
        """从文本中提取结构化字段"""
        data = ContractData(raw_text=text)

        # --- 客户姓名 ---
        # 英文名: 在 Issue Date 之前的大写英文名 (可能是单字母姓如 "YE")
        m = re.search(r'([A-Z]+(?:[ ][A-Z]+)*)\s*[一-鿿]{2,4}\s*Issue Date', text)
        if m:
            data.customer_name = m.group(1).strip()
        else:
            # fallback: 直接匹配行首的大写英文名
            m = re.search(r'^([A-Z]+(?:[ ][A-Z]+)+)', text, re.MULTILINE)
            if m:
                data.customer_name = m.group(1).strip()

        # 中文名
        m = re.search(r'([一-鿿]{2,4})\s*Issue Date', text)
        if m:
            data.customer_name_cn = m.group(1).strip()

        # --- 账户号码 ---
        m = re.search(r'Investment Account Number[^:]*:\s*(\d+)', text)
        if m:
            data.account_number = m.group(1).strip()

        # --- 股票名称 ---
        m = re.search(r'Stock Name\n([^\n]+)', text)
        if m:
            data.stock_name = m.group(1).strip()

        # --- 股票代码 ---
        m = re.search(r'Stock Code\n([^\n]+)', text)
        if m:
            data.stock_code = m.group(1).strip()

        # --- 股票市场 ---
        m = re.search(r'Stock Market\n[^\n]*Market[ ]*([^\n]+)', text)
        if m:
            data.stock_market = m.group(1).strip()

        # --- 交易类别 ---
        m = re.search(r'Transaction Type\n([^\n]+)', text)
        if m:
            data.transaction_type = m.group(1).strip()

        # --- 成交日期 ---
        m = re.search(r'Contract Date\n([^\n]+)', text)
        if m:
            data.contract_date = m.group(1).strip()

        # --- 平均成交价 ---
        m = re.search(r'Average Execution Price[^\n]*\n[^\n]*([A-Z]{3})\s+([\d,.]+)', text)
        if m:
            data.avg_price_currency = m.group(1).strip()
            try:
                data.avg_price = float(m.group(2).replace(',', ''))
            except ValueError:
                pass

        # --- 成交股数 ---
        m = re.search(r'Execution Quantities\n([\d,.]+)', text)
        if m:
            try:
                data.quantity = float(m.group(1).replace(',', ''))
            except ValueError:
                pass

        # --- 交易金额 ---
        m = re.search(r'Total Consideration\s*\n?Amount[^\n]*\n?[^\n]*([A-Z]{3})\s+([\d,.]+)', text)
        if m:
            data.total_amount_currency = m.group(1).strip()
            try:
                data.total_amount = float(m.group(2).replace(',', ''))
            except ValueError:
                pass

        # --- 佣金 ---
        m = re.search(r'Commission\n[^\n]*佣金金额\n?([A-Z]{3})?\s*([\d,.]+)', text)
        if not m:
            m = re.search(r'Commission\n[^\n]*([A-Z]{3})?\s*([\d,.]+)', text)
        if m:
            currency = m.group(1) or "USD"
            data.commission_currency = currency.strip()
            try:
                data.commission = float(m.group(2).replace(',', ''))
            except ValueError:
                pass

        # --- 平台费 ---
        m = re.search(r'Platform Fee\n[^\n]*平台费\n?([A-Z]{3})?\s*([\d,.]+)', text)
        if not m:
            m = re.search(r'Platform Fee\n[^\n]*([A-Z]{3})?\s*([\d,.]+)', text)
        if m:
            currency = m.group(1) or "USD"
            data.platform_fee_currency = currency.strip()
            try:
                data.platform_fee = float(m.group(2).replace(',', ''))
            except ValueError:
                pass

        # --- 交收金额 ---
        m = re.search(r'Settlement Amount\n[^\n]*交收金额\n?([A-Z]{3})?\s*([\d,.]+)', text)
        if not m:
            m = re.search(r'Settlement Amount\n([A-Z]{3})\s+([\d,.]+)', text)
        if m:
            currency = m.group(1) or "USD"
            data.settlement_amount_currency = currency.strip()
            try:
                data.settlement_amount = float(m.group(2).replace(',', ''))
            except ValueError:
                pass

        # --- 交收日期 ---
        m = re.search(r'Settlement Date\n([^\n]+)', text)
        if m:
            data.settlement_date = m.group(1).strip()

        # --- 发出日期 ---
        m = re.search(r'Issue Date[^:]*:\s*(\d{2}\s+\w{3}\s+\d{4})', text)
        if m:
            data.issue_date = m.group(1).strip()

        # --- 交易编号 ---
        m = re.search(r'Order Reference\n[^\n]*交易编号\n?(\d+)', text)
        if not m:
            m = re.search(r'Order Reference\n(\d+)', text)
        if m:
            data.order_reference = m.group(1).strip()

        # --- 备注 ---
        # 备注跨行: "Platform Fee waived. (...) then deduct the\nRemark\nsame amount for settlement.)\n备注\n平台费已豁免 (...)"
        m = re.search(r'(Platform Fee waived\..*?)(?:\nImportant Notice|\n\d+[.])', text, re.DOTALL)
        if m:
            raw_remark = m.group(1).strip()
            # 清理掉中间的 "Remark\n" 和 "备注\n" 标签
            raw_remark = re.sub(r'\nRemark\n', ' ', raw_remark)
            raw_remark = re.sub(r'\n备注\n', '\n', raw_remark)

            # 拆分英文和中文行
            lines = raw_remark.split('\n')
            if lines:
                # 第一行是英文备注
                data.remark = lines[0].strip()
                # 如果中文行存在
                for line in lines[1:]:
                    line = line.strip()
                    if line and not line.startswith('Platform Fee'):
                        data.remark_cn = line
                        break

            # 从英文备注中提取关键信息: "Platform Fee waived."
            if data.remark and 'Platform Fee waived' in data.remark:
                data.remark = 'Platform Fee waived. ' + data.remark.split('Platform Fee waived.')[-1].strip()
                # 截断不要太长
                if len(data.remark) > 200:
                    data.remark = data.remark[:200] + '...'

        return data
