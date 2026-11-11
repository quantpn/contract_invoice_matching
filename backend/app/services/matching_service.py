"""Orchestration service for Contract (Source of Truth) & Invoice Extraction, Editing, and Compliance Reconciliation.
100% AI-driven via refactored Odoo-ET LLMApiService, AIEmbedding (RAG), and AgentService (no hardcoded regex/if-else).
"""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from sqlalchemy.orm import Session

from ..core.ai_citation import apply_numeric_citations
from ..core.ai_fields_tools import (
    AI_FIELDS_INSTRUCTIONS,
    AUDIT_REPORT_SCHEMA,
    extract_contract_summary_with_ai,
    extract_invoice_table_with_ai,
)
from ..core.attachment_processor import (
    build_ai_file_payloads,
    compute_checksum,
    extract_attachment_content,
    guess_file_mimetype,
)
from ..core.exceptions import UserError
from ..core.llm_api_service import LLMApiService, get_config_parameter
from ..core.llm_providers import TEMPERATURE_MAP, get_provider
from ..domain.models import (
    AIAgent,
    AIAgentSource,
    AITopic,
    AuditReportRecord,
    ContractRecord,
    InvoiceRecord,
)
from .agent_service import PREPROMPTS, AgentService
from .audit_tools_service import AuditToolsService
from .embedding_service import EmbeddingService

_logger = logging.getLogger(__name__)

UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
SAMPLE_DATA_DIR = Path("/home/quan/Documents/Data")


class MatchingService:
    """High-level application service connecting the refactored Odoo-ET AI engine to Contract-Invoice Matching."""

    @classmethod
    def ensure_default_agent(cls, db: Session) -> AIAgent:
        agent = db.query(AIAgent).first()
        if not agent:
            topic = AITopic(
                code="contract_invoice_reconciliation",
                name="Đối soát Hóa đơn & Hợp đồng Đa loại hình (AI Compliance Audit)",
                description="Kiểm tra tính hợp lệ của Hóa đơn so với bất kỳ loại Hợp đồng gốc nào và pháp luật thuế.",
                instructions=(
                    "Luôn sử dụng các công cụ `search_contract_clauses` (tìm kiếm RAG điều khoản Hợp đồng) "
                    "và `verify_invoice_arithmetic` (kiểm tra tính toán số học) trước khi đưa ra kết luận kiểm toán. "
                    "Gắn trích dẫn [SOURCE:id] cho mọi điều khoản tham chiếu từ Hợp đồng."
                ),
                tool_names_json=json.dumps(["search_contract_clauses", "verify_invoice_arithmetic"]),
            )
            db.add(topic)
            agent = AIAgent(
                name="AI Compliance Auditor",
                subtitle="Chuyên gia Đối soát Hóa đơn - Hợp đồng Đa loại hình & Kiểm tra Luật Thuế",
                system_prompt=PREPROMPTS["default_system_prompt"],
                response_style="analytical",
                llm_model="gpt-4.1",
                restrict_to_sources=True,
                is_system_agent=True,
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
        return agent

    @classmethod
    def has_active_api_key(cls, llm_model: str) -> bool:
        try:
            provider = get_provider(llm_model)
            key = (
                get_config_parameter("ai.openai_key")
                if provider == "openai"
                else get_config_parameter("ai.google_key")
            )
            return bool(key and key.strip())
        except Exception:
            return False

    @classmethod
    def require_active_api_key(cls, llm_model: str) -> None:
        """Enforce Odoo-ET LLMApiService._get_api_token requirement: raise UserError if API key is missing."""
        if not cls.has_active_api_key(llm_model):
            provider = get_provider(llm_model)
            provider_label = "OpenAI" if provider == "openai" else "Google Gemini"
            raise UserError(
                f"Chưa cấu hình API Key cho nhà cung cấp '{provider_label}' (Model: {llm_model}). "
                f"Vui lòng bấm vào nút '⚙ Cấu hình API Key & Model' ở góc trên bên phải để nhập API Key trước khi thực hiện."
            )

    @classmethod
    def ingest_contract(
        cls,
        db: Session,
        filename: str,
        file_bytes: bytes,
        mimetype: str | None = None,
    ) -> ContractRecord:
        """Upload any type of Contract as a Source of Truth, index RAG chunks in AIEmbedding, and extract AI summary."""
        agent = cls.ensure_default_agent(db)
        cls.require_active_api_key(agent.llm_model)

        mimetype = mimetype or guess_file_mimetype(filename, file_bytes)
        checksum = compute_checksum(file_bytes)

        contracts_dir = UPLOADS_DIR / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{checksum[:8]}_{Path(filename).name}"
        file_path = contracts_dir / safe_name
        file_path.write_bytes(file_bytes)

        raw_text = extract_attachment_content(file_bytes, filename, mimetype)

        # 1. Index Contract in AIAgentSource & AIEmbedding (Vector RAG Source of Truth)
        source = EmbeddingService.create_source_with_chunks(
            db=db,
            agent=agent,
            name=filename,
            checksum=checksum,
            content=raw_text,
            file_path=str(file_path),
            mimetype=mimetype,
            file_size=len(file_bytes),
        )

        # 2. Extract structured Contract Summary via LLMApiService + CONTRACT_SUMMARY_SCHEMA
        files_payload = build_ai_file_payloads(
            file_bytes, filename, mimetype, raw_text, file_index=1
        )
        summary = extract_contract_summary_with_ai(agent.llm_model, files_payload)

        contract = ContractRecord(
            source_id=source.id,
            filename=filename,
            file_path=str(file_path),
            mimetype=mimetype,
            checksum=checksum,
            contract_number=str(summary.get("contract_number") or ""),
            contract_type=str(summary.get("contract_type") or "Hợp đồng kinh tế"),
            signing_date=str(summary.get("signing_date") or ""),
            buyer_name=str(summary.get("buyer_name") or ""),
            buyer_tax_code=str(summary.get("buyer_tax_code") or ""),
            seller_name=str(summary.get("seller_name") or ""),
            seller_tax_code=str(summary.get("seller_tax_code") or ""),
            total_amount=float(summary.get("total_amount") or 0.0),
            vat_rate=float(summary.get("vat_rate") or 0.0),
            raw_text=raw_text,
            summary_json=json.dumps(summary, ensure_ascii=False),
            extraction_mode=f"ai ({agent.llm_model})",
        )
        db.add(contract)
        db.commit()
        db.refresh(contract)
        return contract

    @classmethod
    def ingest_invoice(
        cls,
        db: Session,
        filename: str,
        file_bytes: bytes,
        mimetype: str | None = None,
        contract_id: int | None = None,
    ) -> InvoiceRecord:
        """Upload an Invoice and dynamically extract its Excel-like Key-Value fields & Line Items via LLMApiService."""
        agent = cls.ensure_default_agent(db)
        cls.require_active_api_key(agent.llm_model)

        mimetype = mimetype or guess_file_mimetype(filename, file_bytes)
        checksum = compute_checksum(file_bytes)

        invoices_dir = UPLOADS_DIR / "invoices"
        invoices_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{checksum[:8]}_{Path(filename).name}"
        file_path = invoices_dir / safe_name
        file_path.write_bytes(file_bytes)

        raw_text = extract_attachment_content(file_bytes, filename, mimetype)

        files_payload = build_ai_file_payloads(
            file_bytes, filename, mimetype, raw_text, file_index=1
        )
        extracted_data = extract_invoice_table_with_ai(
            agent.llm_model, files_payload, raw_text
        )

        if contract_id is None and agent.sources:
            # Automatically discover the related Contract from agent.sources via Vector RAG (Odoo-ET _build_rag_context)
            fields_preview = ", ".join(
                f"{f.get('label')}: {f.get('value')}"
                for f in extracted_data.get("fields", [])
                if f.get("value")
            )
            rag_query = f"{fields_preview}\n{raw_text[:800]}"
            _, matched_sources = AgentService.build_rag_context_with_matched_sources(
                db=db, agent=agent, prompt=rag_query, sources=None, top_n=5
            )
            if matched_sources:
                top_source = matched_sources[0]
                matched_contract = (
                    db.query(ContractRecord)
                    .filter(ContractRecord.source_id == top_source.id)
                    .first()
                )
                if matched_contract:
                    contract_id = matched_contract.id

        invoice = InvoiceRecord(
            contract_id=contract_id,
            filename=filename,
            file_path=str(file_path),
            mimetype=mimetype,
            checksum=checksum,
            status="extracted",
            extraction_mode=f"ai ({agent.llm_model})",
            raw_text=raw_text,
            fields_json=json.dumps(extracted_data.get("fields", []), ensure_ascii=False),
            line_items_json=json.dumps(extracted_data.get("line_items", []), ensure_ascii=False),
        )
        db.add(invoice)
        db.commit()
        db.refresh(invoice)
        return invoice

    @classmethod
    def re_extract_invoice_with_ai(cls, db: Session, invoice_id: int) -> InvoiceRecord:
        """Re-run AI extraction on an uploaded invoice using the active LLM API Key."""
        invoice = db.query(InvoiceRecord).filter(InvoiceRecord.id == invoice_id).first()
        if not invoice:
            raise ValueError(f"Invoice #{invoice_id} not found")

        agent = cls.ensure_default_agent(db)
        cls.require_active_api_key(agent.llm_model)

        file_bytes = Path(invoice.file_path).read_bytes()
        files_payload = build_ai_file_payloads(
            file_bytes, invoice.filename, invoice.mimetype, invoice.raw_text, file_index=1
        )
        extracted_data = extract_invoice_table_with_ai(
            agent.llm_model, files_payload, invoice.raw_text
        )
        invoice.fields_json = json.dumps(extracted_data.get("fields", []), ensure_ascii=False)
        invoice.line_items_json = json.dumps(
            extracted_data.get("line_items", []), ensure_ascii=False
        )
        invoice.extraction_mode = f"ai ({agent.llm_model})"
        invoice.status = "extracted"
        invoice.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(invoice)
        return invoice

    @classmethod
    def update_invoice_fields(
        cls,
        db: Session,
        invoice_id: int,
        fields: list[dict],
        line_items: list[dict],
        contract_id: int | None = None,
    ) -> InvoiceRecord:
        """Save user's edits to the Excel-like Key-Value table and Line Items before reconciliation."""
        invoice = db.query(InvoiceRecord).filter(InvoiceRecord.id == invoice_id).first()
        if not invoice:
            raise ValueError(f"Invoice #{invoice_id} not found")

        invoice.fields_json = json.dumps(fields, ensure_ascii=False)
        invoice.line_items_json = json.dumps(line_items, ensure_ascii=False)
        if contract_id is not None:
            invoice.contract_id = contract_id
        invoice.status = "verified_by_user"
        invoice.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(invoice)
        return invoice

    @classmethod
    def reconcile_invoice_with_contract(
        cls,
        db: Session,
        invoice_id: int,
        contract_id: int | None = None,
    ) -> AuditReportRecord:
        """Run 100% AI-driven compliance reconciliation comparing user-confirmed Invoice against any Contract (Source of Truth)."""
        invoice = db.query(InvoiceRecord).filter(InvoiceRecord.id == invoice_id).first()
        if not invoice:
            raise ValueError(f"Invoice #{invoice_id} not found")

        agent = cls.ensure_default_agent(db)
        cls.require_active_api_key(agent.llm_model)

        target_contract_id = contract_id if contract_id is not None else invoice.contract_id
        contract: ContractRecord | None = None
        if target_contract_id:
            contract = (
                db.query(ContractRecord)
                .filter(ContractRecord.id == target_contract_id)
                .first()
            )
            invoice.contract_id = target_contract_id

        invoice_fields = json.loads(invoice.fields_json or "[]")
        invoice_items = json.loads(invoice.line_items_json or "[]")

        # Build ORM snapshot of user-confirmed invoice (using BaseModelMixin._get_ai_context)
        invoice_snapshot = invoice._get_ai_context(
            {
                "filename": invoice.filename,
                "verified_fields": invoice_fields,
                "verified_line_items": invoice_items,
            }
        )

        sources: list[AIAgentSource] | None = None
        if contract and contract.source_id:
            src = (
                db.query(AIAgentSource)
                .filter(AIAgentSource.id == contract.source_id)
                .first()
            )
            if src:
                sources = [src]

        # Retrieve RAG context across agent.sources (auto-discovers matching Contract if not pinned)
        rag_messages, matched_sources = AgentService.build_rag_context_with_matched_sources(
            db=db,
            agent=agent,
            prompt=invoice_snapshot,
            sources=sources,
            top_n=5,
        )
        if not contract and matched_sources:
            top_src = matched_sources[0]
            contract = (
                db.query(ContractRecord)
                .filter(ContractRecord.source_id == top_src.id)
                .first()
            )
            if contract:
                invoice.contract_id = contract.id

        tool_calls_history: list[dict] = []
        tools = AuditToolsService.get_ai_tools(
            db=db,
            agent=agent,
            invoice_fields=invoice_fields,
            invoice_items=invoice_items,
            sources=sources,
            tool_calls_history=tool_calls_history,
        )

        arithmetic_sheet = AuditToolsService.compute_arithmetic_sheet(
            invoice_fields, invoice_items
        )

        extra_context = [
            f"## 1. Dữ liệu Hóa đơn đã được người dùng kiểm tra và chốt trên bảng Excel (ORM Snapshot):\n{invoice_snapshot}",
            f"## 2. Bảng tính toán số học tự động trên Hóa đơn:\n{json.dumps(arithmetic_sheet, ensure_ascii=False, indent=2)}",
        ]
        if contract:
            extra_context.append(
                f"## 3. Hợp đồng gốc liên quan (Source of Truth — Loại: {contract.contract_type}, Số HĐ: {contract.contract_number}, source_id={contract.source_id}):\n"
                f"### Tóm tắt cấu trúc Hợp đồng:\n{contract.summary_json}"
            )

        # Step 1: Execute the Odoo-ET Agent RAG + Tool Calling loop (AgentService.generate_response)
        agent_prompt = (
            "Hãy thực hiện kiểm toán và đối soát toàn diện Hóa đơn đã chốt với Hợp đồng gốc trong RAG Context (Source of Truth) và quy định pháp luật về hóa đơn chứng từ.\n"
            f"Thông tin Hóa đơn cần đối chiếu:\n{invoice_snapshot}\n"
            "Hãy gọi công cụ `verify_invoice_arithmetic` và `search_contract_clauses` để thu thập đầy đủ bằng chứng trước khi kết luận."
        )
        agent_reasoning_Notes = ""
        try:
            agent_responses = AgentService.generate_response(
                db=db,
                agent=agent,
                prompt=agent_prompt,
                extra_system_context=extra_context,
                tools=tools,
                sources=sources,
            )
            if agent_responses:
                agent_reasoning_Notes = "\n\n".join(agent_responses)
        except Exception as e:
            _logger.warning("Agent tool loop warning: %s", e)

        # Step 2: Generate structured Audit Report via LLMApiService._request_llm + AUDIT_REPORT_SCHEMA
        provider = get_provider(agent.llm_model)
        llm_api = LLMApiService(provider=provider)

        structured_prompt = (
            "Dựa trên toàn bộ dữ liệu Hóa đơn (sau khi người dùng đã kiểm tra), bảng tính toán số học, kết quả phân tích của Agent và Hợp đồng gốc (Source of Truth):\n"
            "1. Hãy đánh giá Hóa đơn này là HỢP LỆ (`GOOD`) hay VI PHẠM (`VIOLATION`).\n"
            "2. Tự động thích ứng với loại hợp đồng thực tế (Mua bán, Dịch vụ, Xây dựng, Thuê khoán, Đại lý...): kiểm tra xem các trường bắt buộc trên hóa đơn có bị bỏ trống không, các phép tính số lượng x đơn giá / cộng tiền hàng / thuế suất / tiền thuế / tổng thanh toán có chính xác không, và các thông tin (Chủ thể, Mã số thuế, Đơn giá, Số lượng/Khối lượng, Thuế suất, Tổng tiền, Điều kiện thanh toán/Hồ sơ) có vi phạm Hợp đồng gốc hay không.\n"
            "3. Nếu có vi phạm, liệt kê cụ thể từng lỗi vào `violations`: chỉ rõ `field_key`, `field_label`, `invoice_value`, `expected_value`, `location` (điều khoản nào của hợp đồng kèm `[SOURCE:id]` hoặc điều luật nào), và `explanation`.\n"
            "4. Viết báo cáo tổng hợp chi tiết vào `narrative_markdown` (có gắn `[SOURCE:id]` khi dẫn chiếu hợp đồng)."
        )

        system_prompts = [
            PREPROMPTS["default_system_prompt"],
            AI_FIELDS_INSTRUCTIONS,
            *extra_context,
            *rag_messages,
        ]
        if agent_reasoning_Notes:
            system_prompts.append(f"## Kết quả phân tích bước 1 của AI Agent:\n{agent_reasoning_Notes}")

        responses, *__ = llm_api._request_llm(
            llm_model=agent.llm_model,
            system_prompts=system_prompts,
            user_prompts=[structured_prompt],
            schema=AUDIT_REPORT_SCHEMA,
            temperature=TEMPERATURE_MAP.get(agent.response_style, 0.2),
            web_grounding=False,
        )
        if not responses:
            raise UserError("Không nhận được kết quả đối soát từ mô hình AI.")

        audit_data = json.loads(responses[0], strict=False)
        violations = audit_data.get("violations", [])
        passed_checks = audit_data.get("passed_checks", [])
        missing_fields = audit_data.get("missing_fields", [])
        overall_status = audit_data.get("overall_status", "VIOLATION" if violations else "GOOD")
        is_compliant = bool(audit_data.get("is_compliant", len(violations) == 0))
        risk_score = int(audit_data.get("risk_score", min(100, len(violations) * 25)))
        summary_text = audit_data.get("summary", "")
        raw_narrative = audit_data.get("narrative_markdown") or agent_reasoning_Notes or summary_text

        # Convert [SOURCE:id] tags into numeric citation badges across all agent.sources (Odoo-ET _get_llm_response_with_sources)
        att_map = {
            src.id: {
                "source_name": src.name,
                "url": src.url or f"#contract-source-{src.id}",
            }
            for src in agent.sources
        }
        if att_map:
            narrative_html = apply_numeric_citations(raw_narrative, att_map)
            for v in violations:
                v["explanation_html"] = apply_numeric_citations(v.get("explanation", ""), att_map)
                v["location"] = apply_numeric_citations(v.get("location", ""), att_map)
        else:
            narrative_html = raw_narrative

        invoice.status = "reconciled"
        report = AuditReportRecord(
            invoice_id=invoice.id,
            contract_id=contract.id if contract else None,
            overall_status=overall_status,
            is_compliant=is_compliant,
            risk_score=risk_score,
            summary=summary_text,
            violations_json=json.dumps(violations, ensure_ascii=False),
            passed_checks_json=json.dumps(passed_checks, ensure_ascii=False),
            missing_fields_json=json.dumps(missing_fields, ensure_ascii=False),
            tool_calls_log_json=json.dumps(tool_calls_history, ensure_ascii=False),
            rendered_narrative_html=narrative_html,
            audit_mode=f"ai_agent ({agent.llm_model})",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return report
