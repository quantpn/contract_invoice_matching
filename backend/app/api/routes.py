"""FastAPI REST Endpoints for Contract (Source of Truth) & Invoice Matching."""
import json
from typing import Any
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..core.exceptions import UserError
from ..core.llm_api_service import get_config_parameter, set_config_parameter
from ..core.llm_providers import PROVIDERS, get_provider
from ..domain.database import get_db
from ..domain.models import (
    AIAgentSource,
    AIEmbedding,
    AuditReportRecord,
    ContractRecord,
    InvoiceRecord,
)
from ..services.agent_service import AgentService
from ..services.audit_tools_service import AuditToolsService
from ..services.embedding_service import EmbeddingService
from ..services.matching_service import SAMPLE_DATA_DIR, MatchingService
from .schemas import (
    AgentChatRequest,
    LLMConfigUpdateRequest,
    LoadSampleFileRequest,
    ReconcileRequest,
    UpdateInvoiceFieldsRequest,
)

router = APIRouter(prefix="/api/v1", tags=["Contract-Invoice AI Matching"])


def _serialize_contract(db: Session, c: ContractRecord, include_chunks: bool = False) -> dict[str, Any]:
    chunks = []
    if include_chunks and c.source_id:
        src = db.query(AIAgentSource).filter(AIAgentSource.id == c.source_id).first()
        if src and src.checksum:
            emb_rows = (
                db.query(AIEmbedding)
                .filter(AIEmbedding.checksum == src.checksum)
                .order_by(AIEmbedding.sequence.asc())
                .all()
            )
            chunks = [
                {
                    "id": row.id,
                    "content": row.content,
                    "embedding_model": row.embedding_model,
                    "has_vector": bool(row.embedding_vector),
                }
                for row in emb_rows
            ]

    return {
        "id": c.id,
        "source_id": c.source_id,
        "filename": c.filename,
        "mimetype": c.mimetype,
        "checksum": c.checksum,
        "contract_number": c.contract_number,
        "contract_type": c.contract_type,
        "signing_date": c.signing_date,
        "buyer_name": c.buyer_name,
        "buyer_tax_code": c.buyer_tax_code,
        "seller_name": c.seller_name,
        "seller_tax_code": c.seller_tax_code,
        "total_amount": c.total_amount,
        "vat_rate": c.vat_rate,
        "raw_text": c.raw_text,
        "summary": json.loads(c.summary_json or "{}"),
        "extraction_mode": c.extraction_mode,
        "chunks": chunks,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _serialize_invoice(db: Session, inv: InvoiceRecord) -> dict[str, Any]:
    latest_report = (
        db.query(AuditReportRecord)
        .filter(AuditReportRecord.invoice_id == inv.id)
        .order_by(AuditReportRecord.id.desc())
        .first()
    )
    return {
        "id": inv.id,
        "contract_id": inv.contract_id,
        "filename": inv.filename,
        "mimetype": inv.mimetype,
        "checksum": inv.checksum,
        "status": inv.status,
        "extraction_mode": inv.extraction_mode,
        "raw_text": inv.raw_text,
        "fields": json.loads(inv.fields_json or "[]"),
        "line_items": json.loads(inv.line_items_json or "[]"),
        "latest_report": _serialize_report(latest_report) if latest_report else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
    }


def _serialize_report(rep: AuditReportRecord) -> dict[str, Any]:
    return {
        "id": rep.id,
        "invoice_id": rep.invoice_id,
        "contract_id": rep.contract_id,
        "overall_status": rep.overall_status,
        "is_compliant": rep.is_compliant,
        "risk_score": rep.risk_score,
        "summary": rep.summary,
        "violations": json.loads(rep.violations_json or "[]"),
        "passed_checks": json.loads(rep.passed_checks_json or "[]"),
        "missing_fields": json.loads(rep.missing_fields_json or "[]"),
        "tool_calls_log": json.loads(rep.tool_calls_log_json or "[]"),
        "rendered_narrative_html": rep.rendered_narrative_html,
        "audit_mode": rep.audit_mode,
        "created_at": rep.created_at.isoformat() if rep.created_at else None,
    }


@router.get("/config")
def get_llm_config(db: Session = Depends(get_db)):
    """Get current LLM provider configuration, API key status, and available models from Odoo-ET PROVIDERS."""
    agent = MatchingService.ensure_default_agent(db)
    openai_key = get_config_parameter("ai.openai_key")
    google_key = get_config_parameter("ai.google_key")
    provider = get_provider(agent.llm_model)

    providers_list = [
        {
            "name": p.name,
            "display_name": p.display_name,
            "embedding_model": p.embedding_model,
            "models": [{"id": m[0], "label": m[1]} for m in p.llms],
        }
        for p in PROVIDERS
    ]

    return {
        "llm_model": agent.llm_model,
        "provider": provider,
        "response_style": agent.response_style,
        "has_openai_key": bool(openai_key),
        "has_google_key": bool(google_key),
        "openai_key_masked": f"{openai_key[:6]}...{openai_key[-4:]}" if len(openai_key) > 10 else ("***" if openai_key else ""),
        "google_key_masked": f"{google_key[:6]}...{google_key[-4:]}" if len(google_key) > 10 else ("***" if google_key else ""),
        "active_key_ready": MatchingService.has_active_api_key(agent.llm_model),
        "providers": providers_list,
    }


@router.post("/config")
def update_llm_config(req: LLMConfigUpdateRequest, db: Session = Depends(get_db)):
    """Update API keys, LLM model, and response style (analytical, balanced, creative)."""
    agent = MatchingService.ensure_default_agent(db)
    old_provider = get_provider(agent.llm_model)

    if req.openai_key is not None:
        set_config_parameter("ai.openai_key", req.openai_key.strip())
    if req.google_key is not None:
        set_config_parameter("ai.google_key", req.google_key.strip())

    # Validate model against PROVIDERS
    try:
        new_provider = get_provider(req.llm_model)
        agent.llm_model = req.llm_model
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if req.response_style in ("analytical", "balanced", "creative"):
        agent.response_style = req.response_style

    db.commit()
    db.refresh(agent)

    # Identical to AIAgent.write in et-addons/ai/models/ai_agent.py: sync embeddings when provider changes
    if new_provider != old_provider and MatchingService.has_active_api_key(agent.llm_model):
        try:
            EmbeddingService.sync_new_agent_provider(db, agent)
        except Exception:
            pass

    return get_llm_config(db)


@router.get("/sample-files")
def list_sample_files():
    """List available test files from /home/quan/Documents/Data."""
    if not SAMPLE_DATA_DIR.exists():
        return {"files": []}
    files = []
    for p in sorted(SAMPLE_DATA_DIR.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            lower = p.name.lower()
            is_contract = "hop dong" in lower or "hợp đồng" in lower
            files.append(
                {
                    "filename": p.name,
                    "size_bytes": p.stat().st_size,
                    "suggested_type": "contract" if is_contract else "invoice",
                }
            )
    return {"directory": str(SAMPLE_DATA_DIR), "files": files}


@router.post("/sample-files/load")
def load_sample_file(req: LoadSampleFileRequest, db: Session = Depends(get_db)):
    """Load a sample contract or invoice directly from /home/quan/Documents/Data."""
    target = SAMPLE_DATA_DIR / req.filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Sample file not found: {req.filename}")

    file_bytes = target.read_bytes()
    doc_type = req.doc_type
    if doc_type == "auto":
        lower = req.filename.lower()
        doc_type = "contract" if ("hop dong" in lower or "hợp đồng" in lower) else "invoice"

    try:
        if doc_type == "contract":
            contract = MatchingService.ingest_contract(db, req.filename, file_bytes)
            return {"type": "contract", "contract": _serialize_contract(db, contract, include_chunks=True)}
        else:
            invoice = MatchingService.ingest_invoice(
                db, req.filename, file_bytes, contract_id=req.contract_id
            )
            return {"type": "invoice", "invoice": _serialize_invoice(db, invoice)}
    except UserError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/contracts")
def list_contracts(db: Session = Depends(get_db)):
    """List all uploaded Contracts (Sources of Truth)."""
    rows = db.query(ContractRecord).order_by(ContractRecord.id.desc()).all()
    return {"contracts": [_serialize_contract(db, r, include_chunks=True) for r in rows]}


@router.post("/contracts/upload")
async def upload_contract(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a Contract file (.pdf, .docx, .txt, image) to serve as Source of Truth."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        contract = MatchingService.ingest_contract(
            db=db,
            filename=file.filename or "contract.pdf",
            file_bytes=file_bytes,
            mimetype=file.content_type,
        )
        return _serialize_contract(db, contract, include_chunks=True)
    except UserError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: int, db: Session = Depends(get_db)):
    contract = db.query(ContractRecord).filter(ContractRecord.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return _serialize_contract(db, contract, include_chunks=True)


@router.delete("/contracts/{contract_id}")
def delete_contract(contract_id: int, db: Session = Depends(get_db)):
    contract = db.query(ContractRecord).filter(ContractRecord.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    db.delete(contract)
    db.commit()
    return {"deleted": True, "id": contract_id}


@router.get("/invoices")
def list_invoices(db: Session = Depends(get_db)):
    """List all uploaded Invoices along with their extracted Excel-like fields and latest audit status."""
    rows = db.query(InvoiceRecord).order_by(InvoiceRecord.id.desc()).all()
    return {"invoices": [_serialize_invoice(db, r) for r in rows]}


@router.post("/invoices/upload")
async def upload_invoice(
    file: UploadFile = File(...),
    contract_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Upload an Invoice (.pdf, .docx, image) and extract its Excel-like Key-Value table & Line Items."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        invoice = MatchingService.ingest_invoice(
            db=db,
            filename=file.filename or "invoice.pdf",
            file_bytes=file_bytes,
            mimetype=file.content_type,
            contract_id=contract_id,
        )
        return _serialize_invoice(db, invoice)
    except UserError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.query(InvoiceRecord).filter(InvoiceRecord.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _serialize_invoice(db, invoice)


@router.put("/invoices/{invoice_id}/fields")
def update_invoice_fields(
    invoice_id: int,
    req: UpdateInvoiceFieldsRequest,
    db: Session = Depends(get_db),
):
    """Save user modifications to the Excel-like Key-Value fields and Line Items table."""
    try:
        invoice = MatchingService.update_invoice_fields(
            db=db,
            invoice_id=invoice_id,
            fields=req.fields,
            line_items=req.line_items,
            contract_id=req.contract_id,
        )
        return _serialize_invoice(db, invoice)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/invoices/{invoice_id}/re-extract")
def re_extract_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Re-run AI extraction on the invoice using the configured LLM API key."""
    agent = MatchingService.ensure_default_agent(db)
    if not MatchingService.has_active_api_key(agent.llm_model):
        raise HTTPException(
            status_code=400,
            detail=f"Chưa cấu hình API Key cho model {agent.llm_model}. Vui lòng nhập API Key ở phần Cấu hình AI.",
        )
    try:
        invoice = MatchingService.re_extract_invoice_with_ai(db, invoice_id)
        return _serialize_invoice(db, invoice)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.query(InvoiceRecord).filter(InvoiceRecord.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    db.query(AuditReportRecord).filter(AuditReportRecord.invoice_id == invoice_id).delete()
    db.delete(invoice)
    db.commit()
    return {"deleted": True, "id": invoice_id}


@router.post("/audit/reconcile")
def reconcile_invoice(req: ReconcileRequest, db: Session = Depends(get_db)):
    """Confirm invoice table & execute AI reconciliation against the Contract (Source of Truth)."""
    try:
        report = MatchingService.reconcile_invoice_with_contract(
            db=db,
            invoice_id=req.invoice_id,
            contract_id=req.contract_id,
        )
        invoice = db.query(InvoiceRecord).filter(InvoiceRecord.id == req.invoice_id).first()
        return {
            "report": _serialize_report(report),
            "invoice": _serialize_invoice(db, invoice) if invoice else None,
        }
    except UserError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/audit/reports/{invoice_id}")
def get_invoice_reports(invoice_id: int, db: Session = Depends(get_db)):
    """Get all audit reconciliation reports for a specific invoice."""
    reports = (
        db.query(AuditReportRecord)
        .filter(AuditReportRecord.invoice_id == invoice_id)
        .order_by(AuditReportRecord.id.desc())
        .all()
    )
    return {"reports": [_serialize_report(r) for r in reports]}


@router.post("/agent/chat")
def chat_with_audit_agent(req: AgentChatRequest, db: Session = Depends(get_db)):
    """Interactive Q&A with the refactored Odoo-ET AI Compliance Agent over the Contract & Invoice."""
    agent = MatchingService.ensure_default_agent(db)
    if not MatchingService.has_active_api_key(agent.llm_model):
        raise HTTPException(
            status_code=400,
            detail=f"Vui lòng nhập API Key cho model '{agent.llm_model}' để chat trực tiếp với AI Agent.",
        )

    extra_context: list[str] = []
    sources: list[AIAgentSource] = []
    tools = None

    invoice = None
    if req.invoice_id:
        invoice = db.query(InvoiceRecord).filter(InvoiceRecord.id == req.invoice_id).first()
    contract = None
    target_contract_id = req.contract_id or (invoice.contract_id if invoice else None)
    if target_contract_id:
        contract = db.query(ContractRecord).filter(ContractRecord.id == target_contract_id).first()

    if contract:
        extra_context.append(
            f"## Hợp đồng gốc ({contract.filename}, source_id={contract.source_id}):\n{contract.raw_text}"
        )
        if contract.source_id:
            src = db.query(AIAgentSource).filter(AIAgentSource.id == contract.source_id).first()
            if src:
                sources.append(src)

    if invoice:
        inv_fields = json.loads(invoice.fields_json or "[]")
        inv_items = json.loads(invoice.line_items_json or "[]")
        extra_context.append(
            f"## Hóa đơn đang kiểm tra ({invoice.filename}):\n"
            + invoice._get_ai_context({"fields": inv_fields, "line_items": inv_items})
        )
        tools = AuditToolsService.get_ai_tools(
            db=db,
            agent=agent,
            invoice_fields=inv_fields,
            invoice_items=inv_items,
            sources=sources,
        )

    try:
        responses = AgentService.generate_response(
            db=db,
            agent=agent,
            prompt=req.prompt,
            extra_system_context=extra_context,
            tools=tools,
            sources=sources,
        )
        return {"reply": "\n\n".join(responses), "llm_model": agent.llm_model}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
