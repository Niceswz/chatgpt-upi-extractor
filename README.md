# CHATUPI — ChatGPT UPI 免费支付链接提取工具

> 📣 **更多 AI 福利羊毛信息，欢迎加入 Telegram 频道：[Free\_to\_AI](https://t.me/Free_to_AI)**
> 专注分享 AI 平台漏洞、限时优惠、免费额度等第一手羊毛情报！

---

## 项目简介

**CHATUPI** 是一个独立的 FastAPI + SQLite 服务，用于自动提取 ChatGPT 的 UPI 支付链接。

通过该工具，你可以利用 ChatGPT Free 账号的印度首月免费促销活动，自动生成 UPI 支付链接（适用于 PhonePe / GPay / Paytm 等印度支付应用）。

## 主要功能

- 🔐 **密码保护管理后台**（Session Cookie + CSRF 双重验证）
- 🗄️ **SQLite 任务队列**（单并发提取，带任务记录持久化）
- 🌏 **双代理策略**：结账/UPI 环节走印度代理，促销环节走越南代理
- 🔄 **在线 / 维护模式**切换（管理员可动态控制）
- ⚛️ **React 组件**，可嵌入到更大的门户类前端项目中

## 项目结构（部署示例）

```
/opt/chatupi/
  .env                 # 密钥与代理配置（禁止提交到版本库）
  data/                # SQLite 数据库
  run-output/          # 任务调试产物
  api_python/          # FastAPI 应用包
```

服务仅监听 `127.0.0.1:8104`，通过 Nginx 以 `/CHATUPI/` 路径对外暴露。

## 环境变量配置

将 `.env.example` 复制为 `.env`（生产环境使用 `/opt/chatupi/.env`），并填写以下变量：

| 变量名 | 说明 |
|---|---|
| `CHATUPI_SECRET_KEY` | Session Cookie 随机密钥（至少 48 字符） |
| `CHATUPI_PASSWORD_HASH` | PBKDF2 密码哈希（格式：`pbkdf2_sha256$...`） |
| `CHATUPI_BASE_PATH` | 公开访问路径，例如 `/CHATUPI` |
| `CHATUPI_DATABASE` | SQLite 数据库文件路径 |
| `CHATUPI_RETENTION_DAYS` | 任务记录保留天数（默认 30 天） |
| `CHATUPI_HOURLY_LIMIT` | 每用户每小时最大任务数（默认 10） |
| `CHATUPI_ALLOWED_HOSTS` | 允许访问的主机名（逗号分隔，默认 `localhost,127.0.0.1`） |
| `VERIFY_APP_ROOT` | 项目根目录（用于清理 run-output） |
| `UPI_LINK_PROXY` | 印度出口代理 URL |
| `UPI_LINK_PROMOTION_PROXY` | 越南促销代理 URL |

可选代理专用文件：将 `env_upi_link.txt.example` 复制为 `env_upi_link.txt`。

### 生成密码哈希

```bash
python -c "from api_python.security import hash_password; print(hash_password('你的密码'))"
```

## 本地运行

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
export CHATUPI_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export CHATUPI_PASSWORD_HASH="$(python -c 'from api_python.security import hash_password; print(hash_password("changeme"))')"
export CHATUPI_ALLOWED_HOSTS="localhost,127.0.0.1"
uvicorn api_python.main:app --host 127.0.0.1 --port 8104 --workers 1
```

打开浏览器访问：`http://127.0.0.1:8104/login`（或你配置的 `CHATUPI_BASE_PATH`）

> ⚠️ **请只使用单个 Uvicorn Worker**：提取队列和实时任务状态存储在进程内存中，多 Worker 会导致状态不一致。

## 生产部署

`deploy/` 目录中提供了 systemd 服务单元文件和 Nginx 配置示例，根据你的环境修改路径、用户名和主机名即可。**切勿将真实密钥、代理凭证或生产主机名提交到代码仓库。**

## 安全说明

- Session JSON / Access Token 仅在当前任务的内存中使用，不以明文写入 SQLite。
- 控制台显示的代理 URL 已做脱敏处理（掩码）。
- 所有错误信息在返回给客户端前均经过脱敏。
- `.env` 文件、代理凭证及任何真实 Session 数据请务必加入 `.gitignore`，不要提交到版本库。

## 可选模块

- **`chatgpt_rt_oauth`**（可选）：如未安装，审批请求将在没有 OpenAI Sentinel Token 的情况下运行，可能会降低对风控机制的成功率。
- **`src/components/`**：React 嵌入组件，供宿主门户项目使用。已附带 `src/utils/`、`src/constants/` 及相关 Stub，可独立解析导入。宿主项目仍需自行安装 React 和 `lucide-react`。

## 前端依赖（仅嵌入组件）

```text
react
lucide-react
```

本仓库不包含完整的 SPA 构建；核心产品是 `api_python/templates/` 下的 FastAPI 管理控制台。

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

---

## 📢 欢迎关注 Telegram 频道

如果你对 **AI 平台漏洞福利、限免资源、羊毛情报** 感兴趣，欢迎加入：

**👉 [https://t.me/Free\_to\_AI](https://t.me/Free_to_AI)**

频道内容包括：
- 🐑 各大 AI 平台（ChatGPT、Claude、Gemini 等）免费额度薅羊毛攻略
- 🔓 AI 账号注册与使用技巧
- 💰 限时优惠、促销活动第一时间推送
- 🛠️ 开源工具与实用脚本分享

**欢迎转发、Star 本项目，让更多人受益！** 🌟
