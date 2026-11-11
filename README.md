# Hệ thống AI Agent Đối soát Hóa đơn & Hợp đồng (Refactored từ Odoo Enterprise 19)
---

## 1. Kiến trúc Phân tầng (Clean Architecture)

### Backend (`/home/quan/Documents/contract_invoice_matching/backend`)
1. **`app/core/` (Core AI Utilities & LLM Adapter Layer — Pure Python):**
   - `llm_providers.py`: Định nghĩa `Provider`, `PROVIDERS` (`openai`, `google`), `EMBEDDING_CONFIG`, `TEMPERATURE_MAP` (`analytical`: 0.2, `balanced`: 0.5, `creative`: 0.8).
   - `llm_api_service.py`: (`get_embedding`, `get_transcription`, `request_llm`, `_request_llm_openai`, `_request_llm_google`, vòng lặp đệ quy Tool Calling `_request_llm_silent`, và `__end_message`).
   - `ai_fields_tools.py`: Refactor từ `ai_fields/tools.py` (`AI_FIELDS_INSTRUCTIONS`, `INVOICE_EXTRACTION_SCHEMA`, `CONTRACT_SUMMARY_SCHEMA`, cơ chế kiểm soát ảo giác `value`, `could_not_resolve`, `unresolved_cause`).
   - `tools_schema/`: `validators.py` & `param_schema_validator.py` kiểm duyệt JSON Schema nghiêm ngặt cho Function/Tool Calling.
   - `ai_citation.py`: Bộ xử lý trích dẫn `[SOURCE:id]` thành thẻ số thứ tự `[1]`, `[2]` (`apply_numeric_citations`).
   - `attachment_processor.py`: Trích xuất nội dung PDF/DOCX/Ảnh, làm sạch văn bản (`clean_text`), chia đoạn (`chunk_text` 1500 ký tự, overlap 200), và băm SHA-1 (`compute_checksum`).
2. **`app/domain/` (Domain & Persistence Layer — SQLAlchemy ORM):**
   - `models.py`: Refactor `BaseModelMixin` (`_ai_serialize_fields_data`, `_get_ai_context`), `AITopic`, `AIAgent`, `AIAgentSource`, `AIEmbedding`, `ContractRecord`, `InvoiceRecord`, `AuditReportRecord`.
   - `field_vector.py`: Kiểu cột `Vector` và hàm `cosine_similarity`.
3. **`app/services/` (Application Services Layer):**
   - `embedding_service.py`: Lập chỉ mục RAG cho Hợp đồng gốc (`create_source_with_chunks`, `cron_generate_embedding`, `get_similar_chunks`).
   - `audit_tools_service.py`: Công cụ kiểm toán toán học, kiểm tra trường bắt buộc theo Nghị định 123/2020/NĐ-CP và đối chiếu điều khoản Hợp đồng gốc (`run_invoice_contract_compliance_check`).
   - `agent_service.py`: Điều phối `build_system_context`, `build_rag_context`, `generate_response`, `get_llm_response_with_sources`.
   - `matching_service.py`: Điều phối toàn bộ quy trình nghiệp vụ từ tải Hợp đồng -> tải Hóa đơn -> chỉnh sửa bảng Excel -> xác nhận & đối chiếu.
4. **`app/api/` (Presentation REST API Layer — FastAPI):**
   - `routes.py` & `schemas.py`: Cung cấp các REST API `/api/v1/*`.

### Frontend (`/home/quan/Documents/contract_invoice_matching/frontend`)
- **`src/api/client.js`**: Tầng giao tiếp REST API.
- **`src/components/Navbar.jsx`**: Cấu hình API Key (`OpenAI` / `Google Gemini`), chọn Model và `response_style`.
- **`src/components/ContractPanel.jsx`**: Tải lên và quản lý Hợp đồng gốc (Source of Truth), hiển thị tóm tắt điều khoản và các phân đoạn RAG (`AIEmbedding`).
- **`src/components/InvoiceExcelEditor.jsx`**: Bảng bóc tách Hóa đơn dạng Excel (Sheet 1: Key-Value, Sheet 2: Hàng hóa/Dịch vụ, Sheet 3: Raw Text) cho phép người dùng chỉnh sửa trực tiếp từng trường/giá trị trước khi chốt.
- **`src/components/AuditReportView.jsx`**: Báo cáo kết quả đối chiếu Hợp lệ (`GOOD`) / Vi phạm (`VIOLATION`), bảng chi tiết lỗi vi phạm kèm trích dẫn `[SOURCE:id]` và khung hỏi đáp trực tiếp với AI Compliance Agent.

---

## 2. Hạ tầng Docker & PostgreSQL (`backend/docker/`)

Hệ thống sử dụng **PostgreSQL 16 + pgvector** (`pgvector/pgvector:pg16`) và **FastAPI Backend** được đóng gói trong thư mục `backend/docker/`:
- `backend/docker/docker-compose.yml`: Định nghĩa 2 service `db` (`contract_invoice_postgres`) và `backend` (`contract_invoice_backend`).
- `backend/docker/Dockerfile`: Đóng gói ứng dụng Python FastAPI + SQLAlchemy + `psycopg2-binary`.
- `backend/docker/init.sql`: Tự động kích hoạt `CREATE EXTENSION IF NOT EXISTS vector;` khi khởi tạo PostgreSQL.

**Thông số kết nối PostgreSQL (từ máy Host / DBeaver / pgAdmin):**
- **Host:** `localhost`
- **Port:** `5434` (ánh xạ từ cổng `5432` trong container để tránh trùng cổng `5432` trên máy)
- **Database:** `contract_invoice_db`
- **User:** `ai_user`
- **Password:** `ai_password`
- **Connection URL:** `postgresql+psycopg2://ai_user:ai_password@localhost:5434/contract_invoice_db`

---

## 3. Hướng dẫn Chạy Dự án

```bash
cd /home/quan/Documents/contract_invoice_matching
./run.sh
```

Hoặc chạy riêng Docker Compose cho Backend & Database:
```bash
cd /home/quan/Documents/contract_invoice_matching/backend/docker
docker compose up -d --build
```
- **Frontend:**
  ```bash
  cd /home/quan/Documents/contract_invoice_matching/frontend
  npm run dev
  ```

