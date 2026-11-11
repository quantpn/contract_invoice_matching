"""LLM Providers configuration and model resolution.
Refactored from et-addons/ai/utils/llm_providers.py.
"""
import re
from typing import NamedTuple

from .exceptions import UserError


class Provider(NamedTuple):
    name: str
    display_name: str
    embedding_model: str
    embedding_config: dict
    llms: list[tuple[str, str]]
    deprecated_models: list[str]
    response_style_to_llm_model_and_reasoning: dict[str, tuple[str, str]]


PROVIDERS = [
    Provider(
        "openai",
        "OpenAI",
        "text-embedding-3-small",
        {
            "max_batch_size": 2048,
            "max_tokens_per_request": 200000,
        },
        [
            ("gpt-4o", "GPT-4o"),
            ("gpt-4.1", "GPT-4.1"),
            ("gpt-4.1-mini", "GPT-4.1 Mini"),
            ("gpt-5", "GPT-5"),
            ("gpt-5-mini", "GPT-5 Mini"),
            ("gpt-4", "ChatGPT (Auto)"),
        ],
        ["gpt-3.5-turbo", "gpt-4"],
        {
            "analytical": ("gpt-4.1", "medium"),
            "balanced": ("gpt-4.1", "low"),
            "creative": ("gpt-4o", "low"),
        },
    ),
    Provider(
        "google",
        "Google",
        "text-embedding-004",
        {
            "max_batch_size": 100,
            "max_tokens_per_request": 10000,
        },
        [
            ("gemini-2.5-flash", "Gemini 2.5 Flash"),
            ("gemini-2.5-pro", "Gemini 2.5 Pro"),
            ("gemini-2.0-flash", "Gemini 2.0 Flash"),
            ("gemini-1.5-flash", "Gemini (Auto)"),
        ],
        [
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-embedding-001",
            "gemini-embedding-2",
        ],
        {
            "analytical": ("gemini-2.5-flash", "medium"),
            "balanced": ("gemini-2.5-flash", "low"),
            "creative": ("gemini-2.0-flash", "minimal"),
        },
    ),
]

DEPRECATED_MODELS = [model for provider in PROVIDERS for model in provider.deprecated_models]

EMBEDDING_MODELS_SELECTION = [
    (provider.embedding_model, provider.display_name) for provider in PROVIDERS
]

TEMPERATURE_MAP = {
    "analytical": 0.2,
    "balanced": 0.5,
    "creative": 0.8,
}


def get_provider_for_embedding_model(embedding_model: str) -> str:
    for p in PROVIDERS:
        if p.embedding_model == embedding_model or embedding_model in p.deprecated_models:
            return p.name
    raise UserError("No provider found for the embedding model")


def get_provider(llm_model: str) -> str:
    for p in PROVIDERS:
        if llm_model in [m[0] for m in p.llms] + p.deprecated_models:
            return p.name
    if llm_model.startswith("gemini"):
        return "google"
    if llm_model.startswith("gpt") or llm_model.startswith("o"):
        return "openai"
    raise UserError(f"No provider found for the selected model: {llm_model}")


def get_embedding_config(provider: str) -> dict:
    for p in PROVIDERS:
        if p.name == provider:
            return p.embedding_config
    raise UserError("No embedding configuration found for the provider")


def get_llm_model_and_reasoning(llm_model: str, temperature: float) -> tuple[str, str | None]:
    response_style = next(
        (style for style, temp in TEMPERATURE_MAP.items() if temp == temperature),
        "balanced",
    )

    for provider in PROVIDERS:
        if llm_model in provider.deprecated_models:
            return provider.response_style_to_llm_model_and_reasoning[response_style]

    reasoning = None
    if llm_model in ("gpt-5", "gpt-5-mini"):
        response_style_to_reasoning = {
            "analytical": "medium",
            "balanced": "low",
            "creative": "minimal",
        }
        reasoning = response_style_to_reasoning[response_style]
    return llm_model, reasoning


def get_deprecated_model_replacement_label(llm_model: str, response_style: str) -> str | None:
    def format_model_name(model_name: str) -> str:
        suffixes_to_remove = ["-preview"]
        name_parts = re.sub(rf"(?:{'|'.join(suffixes_to_remove)})$", "", model_name).split("-")
        return " ".join(p.upper() if p.lower() == "gpt" else p.capitalize() for p in name_parts)

    for provider in PROVIDERS:
        if llm_model in provider.deprecated_models:
            model_replacing_deprecated, reasoning = provider.response_style_to_llm_model_and_reasoning[response_style]
            return f"{format_model_name(model_replacing_deprecated)} {reasoning} thinking"
    return None


def check_model_depreciation(model: str) -> None:
    if model in DEPRECATED_MODELS:
        raise UserError(f"{model} is no longer available. Please select a newer model.")


def get_embedding_model(provider_name: str) -> str:
    for provider in PROVIDERS:
        if provider.name == provider_name:
            return provider.embedding_model
    raise UserError(f"No embedding model found for provider {provider_name}")

