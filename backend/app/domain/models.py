"""SQLAlchemy ORM models refactored from et-addons/ai/models/ and adapted for Contract-Invoice Matching."""
from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base
from .field_vector import Vector


class BaseModelMixin:
    """Mixin implementing Odoo's `base` AI extensions from et-addons/ai/models/models.py."""

    @staticmethod
    def _ai_truncate(value: Any, size: int = 60) -> Any:
        if not isinstance(value, str) or len(value) < size:
            return value
        return value[: max(0, size - 3)] + "..."

    def _ai_serialize_fields_data(self) -> str:
        """Serialize model fields into JSON for AI context (refactored from models.py)."""
        result = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name, None)
            if isinstance(val, datetime):
                result[col.name] = val.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(val, str) and col.name in ("name", "display_name"):
                result[col.name] = self._ai_truncate(val)
            else:
                result[col.name] = val
        return json.dumps(result, default=str, ensure_ascii=False)

    def _get_ai_context(self, extra_data: dict | None = None) -> str:
        """Return the JSON-encoded Mini-ORM snapshot for LLM usage (refactored from models.py)."""
        snapshot = {
            self.__tablename__: [
                {
                    "id": getattr(self, "id", None),
                    **(extra_data or json.loads(self._ai_serialize_fields_data())),
                }
            ]
        }
        return json.dumps(snapshot, default=str, ensure_ascii=False)


class AITopic(Base, BaseModelMixin):
    """Refactored from AITopic (ai.topic) in et-addons/ai/models/ai_topic.py."""

    __tablename__ = "ai_topic"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(100), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    instructions = Column(Text, default="")
    tool_names_json = Column(Text, default="[]")  # JSON list of enabled tool names


class AIAgent(Base, BaseModelMixin):
    """Refactored from AIAgent (ai.agent) in et-addons/ai/models/ai_agent.py."""

    __tablename__ = "ai_agent"

    id = Column(Integer, primary_key=True, index=True)
    active = Column(Boolean, default=True)
    name = Column(String(255), nullable=False)
    subtitle = Column(String(500), default="")
    system_prompt = Column(Text, default="You are a RAG assistant.")
    response_style = Column(String(50), default="analytical", nullable=False)
    llm_model = Column(String(100), default="gpt-4.1", nullable=False)
    restrict_to_sources = Column(Boolean, default=True)
    is_system_agent = Column(Boolean, default=True)
    topic_codes_json = Column(Text, default='["contract_invoice_reconciliation"]')

    sources = relationship("AIAgentSource", back_populates="agent", cascade="all, delete-orphan")


class AIAgentSource(Base, BaseModelMixin):
    """Refactored from AIAgentSource (ai.agent.source) in et-addons/ai/models/ai_agent_source.py."""

    __tablename__ = "ai_agent_source"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    agent_id = Column(Integer, ForeignKey("ai_agent.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), default="binary", nullable=False)  # 'binary' or 'url'
    status = Column(String(50), default="indexed", nullable=False)  # 'processing', 'indexed', 'failed'
    is_active = Column(Boolean, default=True)
    error_details = Column(Text, nullable=True)
    checksum = Column(String(64), index=True, nullable=False)
    mimetype = Column(String(128), default="application/octet-stream")
    file_size = Column(Integer, default=0)
    file_path = Column(String(500), nullable=True)
    extracted_content = Column(Text, default="")
    url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    agent = relationship("AIAgent", back_populates="sources")


class AIEmbedding(Base, BaseModelMixin):
    """Refactored from AIEmbedding (ai.embedding) in et-addons/ai/models/ai_embedding.py."""

    __tablename__ = "ai_embedding"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("ai_agent_source.id", ondelete="CASCADE"), nullable=False)
    checksum = Column(String(64), index=True, nullable=False)
    sequence = Column(Integer, default=10)
    content = Column(Text, nullable=False)
    embedding_model = Column(String(100), nullable=False)
    has_embedding_generation_failed = Column(Boolean, default=False)
    embedding_vector = Column(Vector(size=1536), nullable=True)


class ContractRecord(Base, BaseModelMixin):
    """Contract uploaded by user as Source of Truth."""

    __tablename__ = "contract_record"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("ai_agent_source.id", ondelete="SET NULL"), nullable=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    mimetype = Column(String(128), default="application/pdf")
    checksum = Column(String(64), index=True)
    contract_number = Column(String(100), default="")
    contract_type = Column(String(200), default="Hợp đồng mua bán hàng hóa")
    signing_date = Column(String(100), default="")
    buyer_name = Column(String(255), default="")
    buyer_tax_code = Column(String(100), default="")
    seller_name = Column(String(255), default="")
    seller_tax_code = Column(String(100), default="")
    total_amount = Column(Float, default=0.0)
    vat_rate = Column(Float, default=10.0)
    raw_text = Column(Text, default="")
    summary_json = Column(Text, default="{}")
    extraction_mode = Column(String(50), default="ai")  # 'ai' or 'heuristic'
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class InvoiceRecord(Base, BaseModelMixin):
    """Invoice uploaded by user with editable Excel-like Key-Value table & Line Items."""

    __tablename__ = "invoice_record"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contract_record.id", ondelete="SET NULL"), nullable=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    mimetype = Column(String(128), default="application/pdf")
    checksum = Column(String(64), index=True)
    status = Column(String(50), default="extracted")  # 'extracted', 'edited', 'reconciled'
    extraction_mode = Column(String(50), default="ai")  # 'ai' or 'heuristic'
    raw_text = Column(Text, default="")
    fields_json = Column(Text, default="[]")  # Editable Key-Value rows
    line_items_json = Column(Text, default="[]")  # Editable Line Items rows
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditReportRecord(Base, BaseModelMixin):
    """Audit & Compliance Reconciliation Report comparing Invoice against Contract (Source of Truth)."""

    __tablename__ = "audit_report_record"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoice_record.id", ondelete="CASCADE"), nullable=False)
    contract_id = Column(Integer, ForeignKey("contract_record.id", ondelete="SET NULL"), nullable=True)
    overall_status = Column(String(50), nullable=False)  # 'GOOD' or 'VIOLATION'
    is_compliant = Column(Boolean, default=False)
    risk_score = Column(Integer, default=0)
    summary = Column(Text, default="")
    violations_json = Column(Text, default="[]")
    passed_checks_json = Column(Text, default="[]")
    missing_fields_json = Column(Text, default="[]")
    tool_calls_log_json = Column(Text, default="[]")
    rendered_narrative_html = Column(Text, default="")
    audit_mode = Column(String(50), default="ai_agent")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

