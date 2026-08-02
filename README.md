# VN Stock Agent

Agent trả lời câu hỏi về chứng khoán Việt Nam. LangGraph + Groq + PostgreSQL/pgvector
(checkpointer + session/usage log + semantic cache + BCTC SQL) + Next.js frontend,
chạy bằng Docker Compose.

Xây dựng tăng dần qua các bản `Promt xây dựng/prompt_{mvp,v1,v2,v3}.txt`. Xem
`PROJECT_CONTEXT.md` để biết đầy đủ quyết định kỹ thuật, lỗi đã fix, và việc còn dở.

## Kiến trúc

```
resolvers/    entity_resolver.py (tên/alias -> ticker) và time_resolver.py
              (cụm thời gian -> date range) -- cả hai HOÀN TOÀN tất định,
              không qua LLM.
tools/        company_profile_tool, ohlcv_tool, indicator_tool (SMA/RSI qua
              pandas_ta), news_tool (tin tức + sentiment theo mã/ngành),
              financial_tool (BCTC: doanh thu/LNST/EPS/nợ vay, quý/năm, SQL
              thật KHÔNG qua RAG), screener_tool (lọc cổ phiếu tất định trên
              danh sách mã curated). Mọi con số agent trả lời đều bắt nguồn từ đây.
nlp/          sentiment.py (PhoBERT, phân loại cảm xúc tin tức cục bộ -- không
              gọi Groq) và embeddings.py (multilingual-e5-small, cho semantic cache).
graph/        LangGraph: router (fast-path rule-based TRƯỚC, chỉ gọi Groq khi
              không tự tin) -> cache_lookup -> [tool -> synthesize | (đường
              company_evaluation) bctc_research_node + news_sentiment_node
              chạy SONG SONG -> evaluate] -> guardrail (đối chiếu số liệu câu
              trả lời với tool_result, tự retry 1 lần nếu phát hiện số không
              khớp) -> cache_write. context_trim.py tóm tắt hội thoại dài.
db/           Postgres: `sessions`, `groq_usage_log`, `semantic_cache`
              (pgvector), `conversation_summaries`, `rate_limit_events`,
              `financial_metrics` (BCTC, EAV), `request_log` (observability),
              và PostgresSaver checkpointer (bộ nhớ hội thoại theo thread_id).
llm/          Wrapper gọi Groq, log token usage mỗi lần gọi.
app/          FastAPI backend: /chat, /sessions, /sessions/{id}/history,
              /usage/{id}, /observability, /screener.
frontend/     Next.js (App Router, TypeScript, Tailwind, shadcn/ui) -- UI
              chuyên nghiệp thay Streamlit cũ. Route Handlers trong
              `src/app/api/*` proxy sang FastAPI phía server (browser không
              bao giờ gọi thẳng `BACKEND_URL`). Sidebar chung (logo/thu gọn,
              menu Chat/Observability/Screener, danh sách phiên có ghim/đổi
              tên/xóa) hiển thị trên mọi trang, quản lý qua React Context
              (`SessionsProvider`). Không có màn đăng nhập -- app dùng nội bộ.
data/tickers.json  Mapping ticker-tên-alias (xem "Tạo lại danh sách mã" bên dưới).
scripts/      build_ticker_mapping.py, benchmark.py.
tests/        Unit test cho resolver, chỉ báo kỹ thuật, financial_tool,
              guardrail, screener (xem `docker compose exec app pytest`).
```

3 service Docker Compose: **app** (FastAPI backend chứa toàn bộ logic agent),
**frontend** (Next.js UI, chỉ là HTTP client của app), **db** (Postgres + pgvector).

## Yêu cầu

- Docker + Docker Compose.
- 1 API key Groq (https://console.groq.com).

## Chạy nhanh

```bash
cp .env.example .env
# Mở .env, điền GROQ_API_KEY và đổi POSTGRES_PASSWORD nếu cần.

docker compose up --build
```

- Frontend: http://localhost:3000 (không có màn đăng nhập).
- FastAPI backend: http://localhost:8000/health

## Biến môi trường (`.env`)

| Biến | Ý nghĩa |
|---|---|
| `GROQ_API_KEY` | API key Groq |
| `GROQ_MODEL` | Model Groq đang dùng |
| `POSTGRES_*` | Kết nối Postgres (service `db` trong compose) |
| `BACKEND_URL` | URL FastAPI backend mà frontend gọi tới (mặc định `http://app:8000` trong compose) |
| `TICKER_MAPPING_PATH` | Đường dẫn file mapping ticker (mặc định `data/tickers.json`) |

## Các tính năng chính (tóm tắt — chi tiết WHY/lỗi đã fix xem `PROJECT_CONTEXT.md`)

- **Giá/chỉ báo/hồ sơ doanh nghiệp** (MVP): OHLCV, SMA/RSI, company profile —
  toàn bộ tất định, agent chỉ trích lại số liệu từ `tool_result`.
- **Chỉ hỗ trợ chứng khoán niêm yết tại Việt Nam** (HOSE/HNX/UPCoM): câu hỏi
  về cổ phiếu/công ty nước ngoài (Apple, Tesla...) bị từ chối tất định thay
  vì để LLM tự trả lời bằng kiến thức nền không kiểm chứng được. Chit-chat
  thường (không liên quan chứng khoán/tài chính) vẫn trả lời tự nhiên.
- **Tin tức + sentiment, router 2 tầng, semantic cache, tóm tắt hội thoại,
  session cookie, rate-limit** (v1).
- **BCTC** (v2 phần 1): doanh thu/LNST/EPS/nợ vay theo quý/năm, bảng SQL thật
  `financial_metrics`, hỗ trợ tra cứu 1 mã lẫn so sánh nhiều mã. ROE/ROA/
  P-E/P-B/biên lợi nhuận KHÔNG hỗ trợ (nguồn dữ liệu vnstock không đáng tin
  cậy cho các chỉ số này, đã verify).
- **Node đánh giá công ty + guardrail** (v2 phần 3 / v3 phần 1): "Đánh giá
  công ty HPG" chạy song song BCTC + tin tức/sentiment rồi tổng hợp thành
  báo cáo có cấu trúc (điểm mạnh/yếu/rủi ro/số liệu chính), mỗi ý trích
  nguồn cụ thể. Guardrail đối chiếu số liệu câu trả lời cuối với dữ liệu
  nguồn, tự yêu cầu viết lại tối đa 1 lần nếu phát hiện số không khớp.
- **Observability** (v3 phần 3): trang `/observability` trong frontend, dùng
  bảng `request_log` + `groq_usage_log` đã có — không cần Langfuse/LangSmith.
- **Screener** (v3 phần 4): trang `/screener`, lọc tất định (không qua LLM)
  trên ~20 mã lớn theo RSI/SMA/1 chỉ số BCTC.
- **RAG báo cáo phân tích CTCK** (v2 phần 2): CHƯA làm, đang chờ nguồn PDF
  đúng loại (xem `PROJECT_CONTEXT.md`).

**Benchmark**: `scripts/benchmark.py` chạy 1 bộ câu hỏi cố định 2 lần (cache lạnh
rồi cache ấm) qua API thật, đo tokens/query, latency p50/p95, tỉ lệ fast-path, tỉ
lệ cache-hit, in bảng so sánh:

```bash
docker compose exec app python scripts/benchmark.py
```

## Tạo lại danh sách mã (ticker mapping)

Repo đã kèm sẵn `data/tickers.json` sinh từ toàn bộ danh sách mã do vnstock
cung cấp (~1700+ mã, kèm alias tự động rút gọn từ tên công ty + một số brand-name
phổ biến như "vinamilk", "sabeco"...). Muốn làm mới danh sách này (ví dụ khi có
mã mới niêm yết):

```bash
pip install -r requirements-app.txt
python scripts/build_ticker_mapping.py
```

Script này gọi trực tiếp `vnstock` nên cần internet. Entity resolver không bao
giờ để LLM tự đoán mã -- chỉ so khớp (chính xác + fuzzy match) với file này.

## Chạy test

```bash
# Backend (pytest)
pip install -r requirements-dev.txt
pytest tests/ -v

# Frontend (build + lint)
cd frontend && npm install && npm run build && npm run lint
```

Test resolver/tool chạy hoàn toàn tất định/offline (trừ tool gọi trực tiếp
vnstock, chỉ chạy khi live-test qua Docker). Test chỉ báo kỹ thuật so sánh
output của `pandas_ta` với công thức tính tay bằng pandas thuần, không gọi mạng.

## Lưu ý quan trọng

- **Không có con số nào trong câu trả lời cuối cùng là do LLM tự bịa/tự tính**:
  entity resolver, time resolver và các tool (OHLCV, SMA, RSI, BCTC, screener)
  đều tất định; node `synthesize`/`evaluate` chỉ được phép trích lại số liệu
  có trong `tool_result` JSON, và node `guardrail` đối chiếu lại số liệu câu
  trả lời cuối trước khi trả về người dùng.
- Mỗi lần gọi Groq (router/synthesize/evaluate/title) đều được log số token
  input/output + latency vào bảng `groq_usage_log`; mỗi lượt `/chat` (kể cả
  cache-hit/fast-path không gọi Groq) được log vào `request_log` -- cả 2 bảng
  phục vụ trang Observability.
- **Về `vnstock`**: thư viện này (qua dependency `vnai`) có thu thập một số
  thông tin máy (OS/CPU/RAM, công cụ IDE đang chạy) và gửi telemetry định kỳ về
  máy chủ của họ, đồng thời từng ghi một file `AGENTS.md` chứa hướng dẫn tự
  động cho AI coding agent vào thư mục project khi được import lần đầu (đã bị
  gỡ khỏi repo này). Đây là hành vi của bản thân thư viện `vnstock`, không phải
  của code trong repo.
- **Model ML tải lần đầu qua mạng**: `nlp/sentiment.py` và `nlp/embeddings.py`
  tải model từ HuggingFace Hub khi được gọi lần đầu tiên -- lượt tin tức/cache
  đầu tiên sau khi khởi động sẽ chậm hơn bình thường, các lượt sau dùng lại
  model đã tải (volume `hf_cache` persist qua restart).
- **Screener chậm**: mỗi lượt lọc gọi vnstock tuần tự cho từng mã trong danh
  sách ~20 mã curated, có thể mất 1-2 phút.
