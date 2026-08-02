# Hướng dẫn cho Claude Code khi làm việc trong repo này

Agent trả lời câu hỏi chứng khoán Việt Nam (LangGraph + Groq + vnstock +
Postgres/pgvector + FastAPI + Streamlit, chạy Docker Compose). Xây dựng theo
các file trong `Promt xây dựng/` (`prompt_mvp.txt` → `prompt_v1.txt` →
`prompt_v2.txt` → `prompt_v3.txt`), mỗi bản sau nâng cấp trên bản trước.

**Đọc trước khi làm bất kỳ việc gì:**
- `PROJECT_CONTEXT.md` — bắt buộc đọc trước. Ghi toàn bộ quyết định kỹ thuật,
  lỗi đã fix (kèm nguyên nhân gốc), giới hạn đã biết, và gotcha môi trường.
  Đừng lặp lại lỗi/quyết định đã cân nhắc kỹ ở đây.
- `README.md` — kiến trúc/module hiện tại, biến môi trường, lệnh chạy.

## Quy tắc bắt buộc

- **Không con số nào trong câu trả lời cuối được LLM tự bịa/tự tính.** Mọi số
  liệu phải bắt nguồn từ tool_result (resolvers tất định + tool gọi vnstock/SQL
  thật). Câu hỏi về chỉ số không hỗ trợ → từ chối tất định, KHÔNG đưa qua LLM
  tự do trả lời (xem lỗi #7, #24 trong `PROJECT_CONTEXT.md` — đây là lớp lỗi
  nghiêm trọng nhất từng gặp trong dự án).
- **Luôn xác nhận đã hiểu yêu cầu trước khi code** mỗi khi bắt đầu 1 phần việc
  mới (đọc prompt tương ứng trong `Promt xây dựng/`, hỏi lại nếu chưa rõ).
- **Luôn rebuild + test bằng dữ liệu/API thật trước khi báo xong việc** —
  không chỉ đọc code hay chạy unit test tất định. Phần lớn lỗi nghiêm trọng
  (hallucination, deadlock, cache collision, bug nguồn dữ liệu vnstock) chỉ lộ
  ra khi test sống. Trước khi tin 1 API/thư viện bên thứ 3 trả đúng dữ liệu
  "gần nhất", verify bằng dữ liệu thật (xem lỗi #24 — 1 lần verify hời hợt
  suýt khiến 5 chỉ số BCTC dùng nhầm dữ liệu sai).
- Khi sửa xong 1 tính năng/bug, cập nhật `PROJECT_CONTEXT.md` (mục lỗi/quyết
  định liên quan) trước khi coi là xong.

## Lệnh hay dùng

```bash
# Chạy toàn bộ stack (GROQ_API_KEY thật đã có sẵn trong .env, đừng ghi đè)
docker compose up --build

# Hot-patch nhanh khi sửa code (nhanh hơn rebuild) -- COPY TỪNG FILE, không copy cả thư mục
MSYS_NO_PATHCONV=1 docker compose cp path/to/file.py app:/srv/path/to/file.py
docker compose restart app   # bắt buộc, hot-patch không tự reload module

# Test
MSYS_NO_PATHCONV=1 docker compose cp tests app:/srv/tests
docker compose exec -T app python -m pytest tests/ -q

# Xóa cache ngữ nghĩa khi live-test lại 1 câu đã hỏi trước đó (tránh trả lời cũ)
docker compose exec -T db psql -U vn_agent -d vn_agent -c "TRUNCATE TABLE semantic_cache;"
```

## Gotcha môi trường (xem đầy đủ trong `PROJECT_CONTEXT.md`)

- Windows Git Bash: luôn `MSYS_NO_PATHCONV=1` trước `docker compose exec/cp`.
- `docker compose cp <dir> app:/srv/<dir>` khi đích đã tồn tại sẽ tạo thư mục
  lồng — copy từng file lẻ.
- Sau khi sửa cấu trúc class/hàm lồng nhau trong 1 file, luôn
  `python -c "import ast; ast.parse(open(path, encoding='utf-8').read())"`
  trước khi tin là đúng — đọc lại diff không đủ để bắt lỗi thụt lề.
