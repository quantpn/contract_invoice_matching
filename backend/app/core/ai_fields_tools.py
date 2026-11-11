"""AI Fields structured extraction logic refactored from et-addons/ai_fields/tools.py.
Uses strict JSON Schema (value, could_not_resolve, unresolved_cause) via LLMApiService._request_llm
to extract any type of Contract or Invoice without hardcoded regexes.
"""
import json
import logging
from typing import Any

from .exceptions import UnresolvedQuery, UserError
from .llm_api_service import LLMApiService
from .llm_providers import get_provider

_logger = logging.getLogger(__name__)

# Refactored directly from et-addons/ai_fields/tools.py
AI_FIELDS_INSTRUCTIONS = """
You are an expert assistant specialized in analyzing business documents (Contracts of all types, VAT Invoices, Sales Invoices, Service Invoices, Construction/Lease/Agency Agreements) and extracting structured data accurately.

Carefully follow the instructions below to return a valid JSON response matching the requested schema.

## Output Schema
Your response must follow the exact JSON schema provided in the request.
For field extraction items:
- `value`: the extracted value from the document (or `""` if the field is blank/missing on the document).
- `could_not_resolve`: boolean (`true` if the field is present as a label on the document or required by context but its value is left blank/missing; `false` otherwise).
- `unresolved_cause`: a short explanation in Vietnamese if `could_not_resolve` is `true`, otherwise `null`.

## Critical Rules
- Extract all information based strictly on what is actually written in the provided document.
- Do NOT auto-correct wrong math or wrong numbers on an invoice during extraction! Keep the exact numbers printed on the invoice so the subsequent Compliance Audit step can detect violations.
- Adapt dynamically to the document type (e.g., Sales Contract, Service Contract, Lease Contract, Construction Contract, National Reserve Invoice, VAT Invoice, etc.).
""".strip()


def get_ai_value(
    model_name: str,
    system_prompt_extra: str,
    user_prompt: str,
    files: list[dict] | None,
    schema: dict,
) -> Any:
    """Refactored from get_ai_value in et-addons/ai_fields/tools.py."""
    provider = get_provider(model_name)
    llm_api = LLMApiService(provider=provider)
    responses, *__ = llm_api._request_llm(
        llm_model=model_name,
        system_prompts=[AI_FIELDS_INSTRUCTIONS, system_prompt_extra],
        user_prompts=[user_prompt],
        files=files,
        schema=schema,
        temperature=0.1,
        web_grounding=False,
    )
    response = json.loads(responses[0], strict=False)
    if response.get("could_not_resolve"):
        raise UnresolvedQuery(
            response.get("unresolved_cause") or "Could not resolve field value."
        )
    return response.get("value")


INVOICE_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "description": "Danh sách tất cả các trường thông tin (Key-Value) trích xuất động từ Hóa đơn",
            "items": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Mã kỹ thuật của trường (snake_case, ví dụ: invoice_title, template_code, serial_code, invoice_number, issue_date, contract_reference, seller_name, seller_tax_code, seller_address, buyer_name, buyer_tax_code, buyer_address, subtotal_amount, vat_rate, vat_amount, total_amount, amount_in_words, payment_method, hoặc bất kỳ trường đặc thù nào xuất hiện trên hóa đơn)",
                    },
                    "label": {
                        "type": "string",
                        "description": "Tên hiển thị tiếng Việt của trường đúng theo ngữ cảnh hóa đơn",
                    },
                    "group": {
                        "type": "string",
                        "description": "Nhóm thông tin (ví dụ: I. Thông tin chung, II. Bên bán / Cung cấp, III. Bên mua / Khách hàng, IV. Tổng tiền & Thuế, V. Thanh toán & Ghi chú)",
                    },
                    "field_type": {
                        "type": "string",
                        "enum": ["char", "date", "monetary", "float", "integer", "text"],
                        "description": "Kiểu dữ liệu của trường",
                    },
                    "value": {
                        "type": "string",
                        "description": "Giá trị trích xuất nguyên bản từ hóa đơn (để chuỗi rỗng '' nếu trên hóa đơn bỏ trống)",
                    },
                    "could_not_resolve": {
                        "type": "boolean",
                        "description": "True nếu trường này xuất hiện trên mẫu hóa đơn hoặc là thông tin định danh/pháp lý cần có nhưng bị bỏ trống không ghi giá trị",
                    },
                    "unresolved_cause": {
                        "type": ["string", "null"],
                        "description": "Giải thích ngắn gọn nếu trường bị bỏ trống/thiếu trên hóa đơn, ngược lại để null",
                    },
                },
                "required": [
                    "key",
                    "label",
                    "group",
                    "field_type",
                    "value",
                    "could_not_resolve",
                    "unresolved_cause",
                ],
                "additionalProperties": False,
            },
        },
        "line_items": {
            "type": "array",
            "description": "Bảng kê chi tiết các dòng hàng hóa, dịch vụ, hạng mục nghiệm thu trên hóa đơn",
            "items": {
                "type": "object",
                "properties": {
                    "stt": {"type": "integer", "description": "Số thứ tự dòng"},
                    "name": {"type": "string", "description": "Tên hàng hóa, dịch vụ, nội dung công việc"},
                    "model": {"type": "string", "description": "Model / Ký hiệu / Quy cách (để '' nếu không có)"},
                    "unit": {"type": "string", "description": "Đơn vị tính (ĐVT)"},
                    "quantity": {"type": "number", "description": "Số lượng / Khối lượng"},
                    "unit_price": {"type": "number", "description": "Đơn giá nguyên bản trên hóa đơn"},
                    "amount": {"type": "number", "description": "Thành tiền ghi trên hóa đơn"},
                    "currency": {"type": "string", "description": "Đơn vị tiền tệ (VND, USD...)"},
                    "note": {"type": "string", "description": "Ghi chú dòng (nếu có)"},
                },
                "required": [
                    "stt",
                    "name",
                    "model",
                    "unit",
                    "quantity",
                    "unit_price",
                    "amount",
                    "currency",
                    "note",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["fields", "line_items"],
    "additionalProperties": False,
}


CONTRACT_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "contract_number": {"type": "string", "description": "Số hợp đồng / Mã hợp đồng"},
        "contract_type": {
            "type": "string",
            "description": "Loại hợp đồng (ví dụ: Hợp đồng mua bán hàng hóa, Hợp đồng dịch vụ, Hợp đồng thuê mặt bằng, Hợp đồng xây dựng, Hợp đồng nguyên tắc...)",
        },
        "signing_date": {"type": "string", "description": "Ngày ký hợp đồng / Ngày hiệu lực"},
        "buyer_name": {"type": "string", "description": "Tên Bên Mua / Bên Thuê / Chủ đầu tư (Bên A)"},
        "buyer_tax_code": {"type": "string", "description": "Mã số thuế Bên A"},
        "buyer_address": {"type": "string", "description": "Địa chỉ Bên A"},
        "buyer_representative": {"type": "string", "description": "Đại diện Bên A"},
        "seller_name": {"type": "string", "description": "Tên Bên Bán / Bên Cung cấp dịch vụ / Nhà thầu (Bên B)"},
        "seller_tax_code": {"type": "string", "description": "Mã số thuế Bên B"},
        "seller_address": {"type": "string", "description": "Địa chỉ Bên B"},
        "seller_representative": {"type": "string", "description": "Đại diện Bên B"},
        "subtotal_amount": {"type": "number", "description": "Giá trị hợp đồng trước thuế (0 nếu hợp đồng theo đơn giá cố định chưa chốt tổng)"},
        "vat_rate": {"type": "number", "description": "Thuế suất GTGT / VAT thỏa thuận trong hợp đồng (%)"},
        "vat_amount": {"type": "number", "description": "Tiền thuế VAT trong hợp đồng"},
        "total_amount": {"type": "number", "description": "Tổng giá trị hợp đồng sau thuế"},
        "payment_terms": {
            "type": "string",
            "description": "Điều khoản thanh toán, các đợt thanh toán, phương thức thanh toán và bộ hồ sơ chứng từ bắt buộc",
        },
        "key_clauses_summary": {
            "type": "string",
            "description": "Tóm tắt toàn bộ các điều khoản quan trọng đặc thù của loại hợp đồng này (phạm vi công việc/hàng hóa, tiến độ, bảo hành, phạt vi phạm, điều kiện xuất hóa đơn)",
        },
        "items": {
            "type": "array",
            "description": "Danh mục hàng hóa, dịch vụ, hạng mục công việc hoặc biểu phí quy định trong hợp đồng",
            "items": {
                "type": "object",
                "properties": {
                    "stt": {"type": "integer"},
                    "name": {"type": "string"},
                    "model": {"type": "string"},
                    "unit": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "amount": {"type": "number"},
                },
                "required": ["stt", "name", "model", "unit", "quantity", "unit_price", "amount"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "contract_number",
        "contract_type",
        "signing_date",
        "buyer_name",
        "buyer_tax_code",
        "buyer_address",
        "buyer_representative",
        "seller_name",
        "seller_tax_code",
        "seller_address",
        "seller_representative",
        "subtotal_amount",
        "vat_rate",
        "vat_amount",
        "total_amount",
        "payment_terms",
        "key_clauses_summary",
        "items",
    ],
    "additionalProperties": False,
}


AUDIT_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_status": {
            "type": "string",
            "enum": ["GOOD", "VIOLATION"],
            "description": "GOOD nếu hóa đơn hoàn toàn hợp lệ và khớp hợp đồng; VIOLATION nếu có bất kỳ lỗi pháp lý, toán học hoặc sai lệch hợp đồng nào",
        },
        "is_compliant": {
            "type": "boolean",
            "description": "True nếu không có vi phạm (GOOD), False nếu có vi phạm (VIOLATION)",
        },
        "risk_score": {
            "type": "integer",
            "description": "Điểm rủi ro từ 0 (an toàn tuyệt đối) đến 100 (vi phạm nghiêm trọng)",
        },
        "summary": {
            "type": "string",
            "description": "Tóm tắt kết luận kiểm toán ngắn gọn, rõ ràng bằng tiếng Việt",
        },
        "violations": {
            "type": "array",
            "description": "Danh sách chi tiết từng lỗi vi phạm (để mảng rỗng [] nếu hóa đơn GOOD)",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                    },
                    "category": {
                        "type": "string",
                        "description": "Phân loại lỗi (ví dụ: THIẾU TRƯỜNG BẮT BUỘC / VI PHẠM LUẬT, SAI SỐ HỌC TRÊN HÓA ĐƠN, VI PHẠM ĐIỀU KHOẢN HỢP ĐỒNG, SAI LỆCH CHỦ THỂ / MÃ SỐ THUẾ...)",
                    },
                    "field_key": {
                        "type": "string",
                        "description": "Mã trường bị vi phạm trên bảng hóa đơn",
                    },
                    "field_label": {
                        "type": "string",
                        "description": "Tên trường hiển thị tiếng Việt",
                    },
                    "invoice_value": {
                        "type": "string",
                        "description": "Giá trị hiện tại đang ghi trên Hóa đơn (hoặc '(Bỏ trống / Thiếu)' nếu bị khuyết)",
                    },
                    "expected_value": {
                        "type": "string",
                        "description": "Giá trị đúng theo quy định của Hợp đồng gốc hoặc Luật Thuế/Hóa đơn",
                    },
                    "location": {
                        "type": "string",
                        "description": "Vị trí điều khoản trong Hợp đồng (kèm [SOURCE:id]) hoặc điều luật áp dụng (ví dụ: Điều 1 Hợp đồng [SOURCE:1], Điều 10 Nghị định 123/2020/NĐ-CP)",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Giải thích chi tiết vì sao trường này vi phạm và dẫn chiếu [SOURCE:id] nếu đối chiếu với hợp đồng",
                    },
                },
                "required": [
                    "severity",
                    "category",
                    "field_key",
                    "field_label",
                    "invoice_value",
                    "expected_value",
                    "location",
                    "explanation",
                ],
                "additionalProperties": False,
            },
        },
        "passed_checks": {
            "type": "array",
            "description": "Danh sách các hạng mục đã kiểm tra và đạt chuẩn hợp lệ",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["key", "label", "detail"],
                "additionalProperties": False,
            },
        },
        "missing_fields": {
            "type": "array",
            "description": "Danh sách tên các trường bắt buộc bị bỏ trống trên hóa đơn",
            "items": {"type": "string"},
        },
        "narrative_markdown": {
            "type": "string",
            "description": "Báo cáo phân tích chuyên sâu của AI Compliance Agent, có gắn thẻ trích dẫn [SOURCE:id] tới nguồn Hợp đồng RAG",
        },
    },
    "required": [
        "overall_status",
        "is_compliant",
        "risk_score",
        "summary",
        "violations",
        "passed_checks",
        "missing_fields",
        "narrative_markdown",
    ],
    "additionalProperties": False,
}


def extract_invoice_table_with_ai(
    llm_model: str,
    files: list[dict],
    extracted_text: str = "",
) -> dict[str, Any]:
    """Use LLMApiService + INVOICE_EXTRACTION_SCHEMA (ai_fields pattern) to dynamically extract editable Excel key-value table & line items."""
    provider = get_provider(llm_model)
    llm_api = LLMApiService(provider=provider)

    user_prompt = (
        "Hãy đọc kỹ chứng từ Hóa đơn đính kèm và trích xuất ĐẦY ĐỦ tất cả các trường thông tin có trên hóa đơn "
        "thành bảng Key-Value (`fields`) và bảng chi tiết hàng hóa/dịch vụ (`line_items`).\n\n"
        "Yêu cầu:\n"
        "1. Tự động nhận diện mọi trường thông tin xuất hiện trên hóa đơn (Số hóa đơn, Ký hiệu, Mẫu số, Ngày lập, Căn cứ hợp đồng, "
        "Thông tin Bên bán/Bên cung cấp, Mã số thuế, Địa chỉ, Số tài khoản, Thông tin Bên mua/Khách hàng, Mã số thuế người mua, "
        "Cộng tiền hàng/dịch vụ, Thuế suất GTGT, Tiền thuế GTGT, Tổng cộng tiền thanh toán, Số tiền bằng chữ, Hình thức/điều kiện thanh toán, Hồ sơ kèm theo, và các trường đặc thù khác nếu có).\n"
        "2. Giữ nguyên chính xác con số/chữ thực tế đang in trên hóa đơn (kể cả khi hóa đơn tính sai thuế hay ghi sai số tiền) để phục vụ bước đối soát phát hiện vi phạm.\n"
        "3. Nếu một trường trên hóa đơn bị bỏ trống (ví dụ có nhãn `Mã số thuế:` hoặc `Địa chỉ:` nhưng để trống không điền, hoặc thiếu thông tin bắt buộc trên hóa đơn), "
        "BẮT BUỘC đặt `value: \"\"`, `could_not_resolve: true` và ghi rõ `unresolved_cause`."
    )

    responses, *__ = llm_api._request_llm(
        llm_model=llm_model,
        system_prompts=[AI_FIELDS_INSTRUCTIONS],
        user_prompts=[user_prompt],
        files=files,
        schema=INVOICE_EXTRACTION_SCHEMA,
        temperature=0.1,
        web_grounding=False,
    )
    if not responses:
        raise UserError("Không nhận được phản hồi từ mô hình AI khi trích xuất hóa đơn.")
    return json.loads(responses[0], strict=False)


def extract_contract_summary_with_ai(
    llm_model: str,
    files: list[dict],
) -> dict[str, Any]:
    """Use LLMApiService + CONTRACT_SUMMARY_SCHEMA to extract structured Source-of-Truth summary from any Contract type."""
    provider = get_provider(llm_model)
    llm_api = LLMApiService(provider=provider)

    user_prompt = (
        "Hãy đọc kỹ toàn bộ văn bản Hợp đồng đính kèm (Source of Truth) — bất kể đây là Hợp đồng mua bán hàng hóa, "
        "Hợp đồng dịch vụ, Hợp đồng xây dựng, Hợp đồng thuê tài sản hay loại hợp đồng nào khác — và trích xuất chính xác "
        "thông tin định danh hợp đồng, loại hợp đồng, chủ thể các bên (Bên A / Bên B, Mã số thuế, Địa chỉ, Đại diện), "
        "danh mục hàng hóa/dịch vụ/hạng mục thanh toán, đơn giá, số lượng, thuế suất VAT, tổng giá trị hợp đồng "
        "và tóm tắt toàn bộ các điều khoản thanh toán, hồ sơ nghiệm thu, điều kiện xuất hóa đơn."
    )

    responses, *__ = llm_api._request_llm(
        llm_model=llm_model,
        system_prompts=[AI_FIELDS_INSTRUCTIONS],
        user_prompts=[user_prompt],
        files=files,
        schema=CONTRACT_SUMMARY_SCHEMA,
        temperature=0.1,
        web_grounding=False,
    )
    if not responses:
        raise UserError("Không nhận được phản hồi từ mô hình AI khi trích xuất hợp đồng.")
    return json.loads(responses[0], strict=False)
