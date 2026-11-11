"""AI Tools service refactored from et-addons/ai/models/ir_actions_server.py.
Provides general-purpose, contract-type-agnostic tools (RAG Clause Search & Exact Arithmetic Calculator)
for the AI Agent tool-calling loop, validated via Odoo-ET's tools_schema validators.
"""
from functools import partial
import json
import logging
import re
from typing import Any, Callable
from sqlalchemy.orm import Session

from ..core.llm_api_service import LLMApiService
from ..core.llm_providers import get_embedding_model, get_provider
from ..core.tools_schema.validators import (
    validate_params_llm_values_with_schema,
    validate_schema,
)
from ..domain.models import AIAgent, AIAgentSource
from .embedding_service import EmbeddingService

_logger = logging.getLogger(__name__)


def _to_number(val: Any) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = re.sub(r"[^\d,.-]", "", str(val)).strip()
    if not cleaned:
        return None
    if cleaned.count(".") >= 1 and "," not in cleaned:
        parts = cleaned.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            cleaned = "".join(parts)
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


class AuditToolsService:
    """Refactored from IrActionsServer._get_ai_tools and _ai_tool_run in et-addons/ai/models/ir_actions_server.py."""

    @classmethod
    def compute_arithmetic_sheet(
        cls,
        invoice_fields: list[dict],
        invoice_items: list[dict],
    ) -> dict[str, Any]:
        """Pure arithmetic calculator over dynamic invoice rows so the LLM has exact numbers without hardcoding contract rules."""
        line_calculations = []
        sum_of_line_amounts = 0.0
        sum_of_computed_lines = 0.0

        for idx, item in enumerate(invoice_items, start=1):
            qty = _to_number(item.get("quantity")) or 0.0
            price = _to_number(item.get("unit_price")) or 0.0
            stated_amt = _to_number(item.get("amount")) or 0.0
            computed_amt = round(qty * price, 2)
            sum_of_line_amounts += stated_amt
            sum_of_computed_lines += computed_amt
            line_calculations.append(
                {
                    "row": item.get("stt") or idx,
                    "name": item.get("name", ""),
                    "quantity": qty,
                    "unit_price": price,
                    "stated_amount": stated_amt,
                    "computed_qty_x_price": computed_amt,
                    "difference": round(stated_amt - computed_amt, 2),
                    "is_math_exact": abs(stated_amt - computed_amt) <= 1.0,
                }
            )

        numeric_fields = {}
        blank_fields = []
        for f in invoice_fields:
            k = f.get("key", "")
            val_str = str(f.get("value") or "").strip()
            if not val_str or f.get("could_not_resolve"):
                blank_fields.append(
                    {
                        "key": k,
                        "label": f.get("label", k),
                        "unresolved_cause": f.get("unresolved_cause"),
                    }
                )
            num_val = _to_number(val_str)
            if num_val is not None and f.get("field_type") in ("monetary", "float", "integer"):
                numeric_fields[k] = {
                    "label": f.get("label", k),
                    "raw_value": val_str,
                    "numeric_value": num_val,
                }

        return {
            "line_item_calculations": line_calculations,
            "sum_of_stated_line_amounts": sum_of_line_amounts,
            "sum_of_computed_line_amounts": sum_of_computed_lines,
            "numeric_fields_parsed": numeric_fields,
            "blank_or_unresolved_fields": blank_fields,
        }

    @classmethod
    def get_ai_tools(
        cls,
        db: Session,
        agent: AIAgent,
        invoice_fields: list[dict],
        invoice_items: list[dict],
        sources: list[AIAgentSource] | None = None,
        tool_calls_history: list[dict] | None = None,
    ) -> dict[str, tuple[str, bool, Callable, dict]]:
        """Build general-purpose tool specifications dictionary matching Odoo-ET IrActionsServer._get_ai_tools."""

        # Tool 1: Semantic RAG search across any Contract type
        search_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Câu truy vấn tìm kiếm điều khoản trong Hợp đồng gốc (ví dụ: 'điều khoản giá trị, thuế suất, điều kiện thanh toán, phạt vi phạm, chủ thể hợp đồng')",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }
        validate_schema(search_schema)

        # Tool 2: Exact Arithmetic Calculator for Invoice numbers
        calc_schema = {
            "type": "object",
            "properties": {
                "focus_note": {
                    "type": "string",
                    "description": "Ghi chú phạm vi cần máy tính kiểm tra số học (ví dụ: 'kiểm tra nhân dòng hàng hóa, cộng tổng tiền hàng, tiền thuế và tổng thanh toán')",
                },
            },
            "required": ["focus_note"],
            "additionalProperties": False,
        }
        validate_schema(calc_schema)

        def _exec_search_contract(arguments: dict[str, Any]):
            validate_params_llm_values_with_schema(arguments, search_schema)
            query_str = arguments["query"]
            target_sources = sources if sources is not None else list(agent.sources)
            if not target_sources:
                res = {"message": "Không có Hợp đồng gốc nào trong kho nguồn của Agent."}
            else:
                provider = get_provider(agent.llm_model)
                emb_model = get_embedding_model(provider)
                llm_service = LLMApiService(provider=provider)
                emb_resp = llm_service.get_embedding(
                    input=llm_service._format_for_embedding(content=query_str, mode="query"),
                    dimensions=EmbeddingService.get_dimensions(),
                    model=emb_model,
                )
                query_embedding = emb_resp["data"][0]["embedding"]
                chunks = EmbeddingService.get_similar_chunks(
                    db=db,
                    query_embedding=query_embedding,
                    sources=target_sources,
                    embedding_model=emb_model,
                    top_n=5,
                )
                res = {
                    "query": query_str,
                    "matched_contract_chunks": [
                        {
                            "source_id": c.source_id,
                            "citation_tag": f"[SOURCE:{c.source_id}]",
                            "content": c.content,
                        }
                        for c in chunks
                    ],
                }
            if tool_calls_history is not None:
                tool_calls_history.append(
                    {"tool": "search_contract_clauses", "arguments": arguments, "result": res}
                )
            return json.dumps(res, ensure_ascii=False), None

        def _exec_verify_math(arguments: dict[str, Any]):
            validate_params_llm_values_with_schema(arguments, calc_schema)
            res = cls.compute_arithmetic_sheet(invoice_fields, invoice_items)
            if tool_calls_history is not None:
                tool_calls_history.append(
                    {"tool": "verify_invoice_arithmetic", "arguments": arguments, "result": res}
                )
            return json.dumps(res, ensure_ascii=False), None

        return {
            "search_contract_clauses": (
                "Tìm kiếm ngữ nghĩa (Vector RAG) các điều khoản trong Hợp đồng gốc (bất kể loại hợp đồng nào) để lấy căn cứ đối chiếu và gắn trích dẫn [SOURCE:id].",
                False,
                partial(_exec_search_contract),
                search_schema,
            ),
            "verify_invoice_arithmetic": (
                "Máy tính kiểm tra độ chính xác số học (nhân số lượng x đơn giá, tổng các dòng, danh sách các trường số và các trường đang bỏ trống) trên Hóa đơn.",
                False,
                partial(_exec_verify_math),
                calc_schema,
            ),
        }
