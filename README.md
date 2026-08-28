# AI 成交单审核平台 — 安装指南

一个用于香港投资成交单的 AI 辅助审核平台。将成交单与官方模板自动对照，找出缺失或不一致的条款。支持股票、基金、VA 虚拟资产、投资月结单四类产品。

本指南说明如何在一台电脑上安装并启动平台。

---

## 1. 系统要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11、macOS、Linux 均可 |
| Python | 3.10 或更高版本（开发环境为 3.12） |
| 磁盘空间 | 约 200 MB（含依赖） |
| 网络 | 安装依赖时需联网；运行条款核查可完全离线，AI 审核需联网 |

> 说明：平台运行不需要数据库、不需要 Docker，直接 `python app.py` 即可启动。Docker 和云端部署见文末「进阶」章节。

---

## 2. 第一步：安装 Python

如果电脑上已装有 Python 3.10+，可跳过本步骤。

**Windows：**

1. 打开 https://www.python.org/downloads/
2. 下载最新的 Python 3.x（如 3.12）。
3. 运行安装程序，**务必勾选底部的「Add Python to PATH」**，然后点「Install Now」。
4. 安装完成后，打开「命令提示符」或 PowerShell，输入以下命令验证：
   ```bash
   python --version
   ```
   显示 `Python 3.x.x` 即成功。

**macOS：**

1. 打开终端，如果没装 Homebrew，先安装：https://brew.sh
2. 安装 Python：
   ```bash
   brew install python@3.12
   ```
3. 验证：
   ```bash
   python3 --version
   ```

---

## 3. 第二步：解压项目

1. 将收到的压缩包 `contract-audit-platform.zip` 解压到任意目录。
2. 解压后会得到一个文件夹 `contract-audit-platform`。
3. 进入该文件夹（后续所有命令都在此文件夹内执行）。

---

## 4. 第三步：安装依赖

在当前文件夹打开终端：

- **Windows**：在文件夹空白处按住 Shift 右键，选择「在此处打开 PowerShell」；
- **macOS**：在终端中 `cd` 到该文件夹。

然后执行：

```bash
pip install -r requirements.txt
```

> 如果提示 `pip` 不是可用命令，改用：
> ```bash
> python -m pip install -r requirements.txt
> ```
>
> 如果安装过程中网络慢或超时，可换用国内镜像源（中国大陆用户）：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

看到命令结束且无红色报错，即安装完成。

---

## 5. 第四步：配置（可选）

平台默认即可运行「条款核查」和「VA 专项检查」，这两项**完全离线**，无需任何配置。

只有 **AI 审核**（股票、基金的 LLM 复核）需要一个 API Key。如需使用，按以下步骤配置：

1. 复制配置模板：
   ```bash
   # Windows PowerShell
   copy .env.example .env

   # macOS / Linux
   cp .env.example .env
   ```

2. 用记事本或任意编辑器打开生成的 `.env` 文件，填入你的 Key：
   ```
   OPENROUTER_API_KEY=你的-key
   PORT=8000
   ```

   | 变量 | 用途 | 是否必填 |
   |---|---|---|
   | `OPENROUTER_API_KEY` | OpenRouter/Claude 的 API Key，用于 AI 审核 | 否 |
   | `PORT` | 服务端口（默认 8000） | 否 |

3. 保存文件。

> 不配置 `.env` 也不会报错，平台自动运行在「规则引擎模式」，右上角徽标会显示。

---

## 6. 第五步：启动

在项目文件夹内执行：

```bash
python app.py
```

看到类似输出即启动成功：

```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## 7. 第六步：打开使用

浏览器打开：

```
http://localhost:8000
```

- 首次打开会看到**薄荷绿＋黄色的动画封面页**，点「开始使用」进入审核界面。
- 审核界面地址：`http://localhost:8000/app`

---

## 8. 常见问题排查

| 现象 | 原因 | 解决办法 |
|---|---|---|
| `python` 不是内部或外部命令 | 安装 Python 时未勾选 Add to PATH | 重装 Python 并勾选，或改用 `py` 命令 |
| `pip install` 报错 / 超时 | 网络问题 | 换国内镜像源重试（见第 4 节） |
| 启动时报 `ModuleNotFoundError` | 依赖没装全 | 重新执行 `pip install -r requirements.txt` |
| 浏览器打不开 localhost:8000 | 服务没启动 | 确认 `python app.py` 还在运行、终端没关 |
| 8000 端口被占用 | 其他程序占用了端口 | 改 `.env` 里的 `PORT` 为其他值，如 `8080` |
| 上传文件后报「条款问题」 | 文件传到了错误的产品页 | 基金文件要传到基金页，VA 文件传到 VA 页 |

---

## 9. 进阶：Docker 部署（可选）

已提供 `Dockerfile`，无需在宿主机安装 Python：

```bash
docker build -t contract-audit .
docker run -p 8000:8000 contract-audit
```

---

## 10. 进阶：云端部署（可选）

项目已包含云端部署配置：

- **`Procfile`**：适用于 Railway / Render 等 PaaS 平台。
- **`Dockerfile`**：适用于任意支持 Docker 的平台。

部署到 Railway 的要点：

1. 将项目推送到 GitHub 仓库。
2. 在 Railway 新建项目，选择「从 GitHub 部署」并选中该仓库。
3. Railway 会读取 `Procfile` 自动执行 `pip install` + `python app.py`，无需额外配置。
4. 若需 AI 审核，在 Railway 的环境变量（Variables）中添加 `OPENROUTER_API_KEY`。

> 注意：云端部署时环境变量要通过平台后台设置，**不要**把含真实 Key 的 `.env` 文件提交到 Git。

---

## 11. 项目结构

```
contract-audit-platform/
├── app.py                  # 主程序（FastAPI 服务）
├── requirements.txt        # Python 依赖
├── Dockerfile              # Docker 镜像定义
├── Procfile                # 云端部署配置
├── .env.example            # 环境变量模板
├── data/
│   └── clauses.json        # 条款模板数据
├── modules/                # 核心逻辑
│   ├── contract_auditor.py # 条款核查引擎
│   ├── audit_engine.py     # AI 审核引擎
│   ├── va_checker.py       # VA 专项检查（50 项）
│   ├── pdf_parser.py       # PDF 解析
│   ├── hk_holidays.py      # 香港工作日判断
│   └── statement_parser.py # 月结单解析
├── templates/              # 前端页面
│   ├── landing.html        # 封面页
│   └── index.html          # 审核界面
├── static/
│   └── style.css           # 样式
└── docs/                   # 用户指南文档
```

---

如仍有问题，请联系项目维护者并提供：终端里的报错信息、Python 版本（`python --version`）、操作系统版本。