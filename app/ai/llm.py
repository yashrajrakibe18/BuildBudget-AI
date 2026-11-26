"""Configurable LLM providers. Never fabricates a fallback answer.

Supported: Groq, Google Gemini, OpenAI, OpenRouter (OpenAI-compatible).
A missing key or model raises `LLMNotConfigured` so the UI can say the assistant
is unavailable instead of pretending to answer.
"""
from __future__ import annotations

from app.core.config import settings


class LLMNotConfigured(RuntimeError):
    pass


PROVIDERS = ("groq", "google", "gemini", "openai", "openrouter")


def availability() -> dict:
    status = settings.llm_status()
    if settings.llm_provider not in PROVIDERS:
        return {"available": False, "provider": settings.llm_provider,
                "reason": f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use one of {', '.join(PROVIDERS)}."}
    if not status["key_present"]:
        return {"available": False, "provider": settings.llm_provider,
                "reason": f"No API key for {settings.llm_provider}. Set the matching key in .env."}
    if not status["model"]:
        return {"available": False, "provider": settings.llm_provider,
                "reason": "No LLM_MODEL configured. Set a tool-calling model in .env."}
    return {"available": True, "provider": settings.llm_provider, "model": status["model"], "reason": ""}


def get_chat_model(temperature: float | None = None):
    p, model = settings.llm_provider, settings.llm_model
    key = settings.api_keys.get("google" if p in ("google", "gemini") else p, "")
    if p not in PROVIDERS:
        raise LLMNotConfigured(f"Unknown LLM_PROVIDER '{p}'")
    if not key or not model:
        raise LLMNotConfigured(
            "The AI assistant is not configured. Set LLM_PROVIDER, LLM_MODEL (a tool-calling model) "
            "and the matching API key in .env. Everything else in BuildBudget AI works without it."
        )
    temp = settings.llm_temperature if temperature is None else temperature
    if p == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, api_key=key, temperature=temp, timeout=90, max_retries=1)
    if p in ("google", "gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=key, temperature=temp, timeout=90)
    from langchain_openai import ChatOpenAI
    if p == "openrouter":
        return ChatOpenAI(model=model, api_key=key, base_url="https://openrouter.ai/api/v1",
                          temperature=temp, timeout=90, max_retries=1)
    return ChatOpenAI(model=model, api_key=key, temperature=temp, timeout=90, max_retries=1)


def usage_from(message) -> dict:
    """Best-effort token accounting; providers differ, so every field is optional."""
    meta = getattr(message, "usage_metadata", None) or {}
    if isinstance(meta, dict) and meta:
        return {"input_tokens": meta.get("input_tokens"), "output_tokens": meta.get("output_tokens"),
                "total_tokens": meta.get("total_tokens")}
    resp = getattr(message, "response_metadata", None) or {}
    usage = resp.get("token_usage") or resp.get("usage") or {}
    if usage:
        return {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens")}
    return {}
