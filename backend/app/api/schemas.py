"""Pydantic Request & Response Schemas for the Contract-Invoice Matching API."""
from typing import Any
from pydantic import BaseModel, Field


class LLMConfigUpdateRequest(BaseModel):
    openai_key: str | None = Field(default=None, description="OpenAI API Key (sk-...)")
    google_key: str | None = Field(default=None, description="Google Gemini API Key (AIza...)")
    llm_model: str = Field(default="gpt-4.1", description="Selected LLM model")
    response_style: str = Field(
        default="analytical",
        description="Response style: analytical, balanced, or creative",
    )


class UpdateInvoiceFieldsRequest(BaseModel):
    fields: list[dict[str, Any]]
    line_items: list[dict[str, Any]]
    contract_id: int | None = None


class ReconcileRequest(BaseModel):
    invoice_id: int
    contract_id: int | None = None


class LoadSampleFileRequest(BaseModel):
    filename: str
    doc_type: str = Field(
        default="auto",
        description="'contract', 'invoice', or 'auto'",
    )
    contract_id: int | None = None


class AgentChatRequest(BaseModel):
    prompt: str
    invoice_id: int | None = None
    contract_id: int | None = None
