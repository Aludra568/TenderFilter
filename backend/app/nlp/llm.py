"""Тонкий клиент LLM: Ollama (локально, по умолчанию в docker-compose) или OpenAI-совместимый API.

LLM дополняет алгоритм в двух местах: доразбирает фразы критериев, которые не поняли правила,
и перепроверяет готовую оценку (app.scoring.review). Процент оценки всегда считает алгоритм.
Любая ошибка (нет модели, таймаут, невалидный JSON) возвращает None, и система работает без LLM.
"""

import json
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


def provider_status(timeout: float = 1.5) -> dict:
    s = get_settings()
    if s.llm_provider == "ollama":
        try:
            resp = httpx.get(f"{s.ollama_url}/api/tags", timeout=timeout)
            names = [m.get("name", "") for m in resp.json().get("models", [])]
            ready = any(n == s.llm_model or n.startswith(s.llm_model + ":") or n.split(":")[0] == s.llm_model for n in names)
            return {"provider": "ollama", "model": s.llm_model, "ready": ready,
                    "detail": None if ready else "Модель ещё скачивается или не найдена — работает разбор правилами"}
        except (httpx.HTTPError, ValueError):
            return {"provider": "ollama", "model": s.llm_model, "ready": False, "detail": "Ollama недоступна — работает разбор правилами"}
    if s.llm_provider == "openai":
        return {"provider": "openai", "model": s.llm_model, "ready": bool(s.openai_api_key), "detail": None}
    return {"provider": "none", "model": None, "ready": False, "detail": "LLM отключена — работает разбор правилами"}


def complete_json(system: str, user: str, schema: dict | None = None, timeout: float | None = None) -> dict | None:
    s = get_settings()
    timeout = timeout or s.llm_timeout_seconds
    try:
        if s.llm_provider == "ollama":
            body = {
                "model": s.llm_model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "stream": False,
                "format": schema or "json",
                "options": {"temperature": 0, "num_ctx": 4096},
            }
            resp = httpx.post(f"{s.ollama_url}/api/chat", json=body, timeout=timeout)
            resp.raise_for_status()
            return json.loads(resp.json()["message"]["content"])
        if s.llm_provider == "openai" and s.openai_api_key:
            body = {
                "model": s.llm_model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
            resp = httpx.post(
                f"{s.openai_base_url.rstrip('/')}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                timeout=timeout,
            )
            resp.raise_for_status()
            return json.loads(resp.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("LLM недоступна или вернула не JSON: %s", exc)
    return None
