FROM python:3.12

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

# 启动：由 Python 代码读取 PORT 环境变量
CMD ["python", "app.py"]
