"""Isolated LLM client service abstraction interface.

Decouples the rest of the application from specific LLM providers (e.g. Google Gemini API).
Provides production-grade async calls with bounded retries, exponential backoff,
structured output validation, model fallback, and auditable error classification.
"""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger("citeverify.core.llm")


class LLMMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    tokens_used: Optional[int] = None
    finish_reason: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class BaseLLMClient(ABC):
    """Abstract interface for LLM interactions."""

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate text completion from a prompt."""
        pass

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_schema: Dict[str, Any],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
    ) -> Dict[str, Any]:
        """Generate structured JSON conforming to a specific schema."""
        pass


class GeminiLLMClient(BaseLLMClient):
    """Production Google Gemini API client implementation using official REST endpoints."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 25.0,
        max_retries: int = 2,
    ):
        settings = get_settings()
        self.api_key = settings.GEMINI_API_KEY if api_key is None else api_key
        raw_model = model or settings.GEMINI_MODEL
        # Normalize model string (strip 'models/' prefix if present)
        self.model = raw_model.replace("models/", "") if raw_model else "gemini-2.5-flash-lite"
        self.timeout = timeout_seconds
        self.max_retries = max_retries

        # Candidate fallback models in case primary model is unavailable or rate-limited
        self.candidate_models = [self.model]
        for fallback in ("gemini-2.5-flash-lite", "gemini-3.8-flash"):
            if fallback not in self.candidate_models:
                self.candidate_models.append(fallback)

    def is_configured(self) -> bool:
        """Check whether a non-empty API key is configured."""
        return bool(self.api_key and len(self.api_key.strip()) >= 10)

    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate plain text from Gemini API."""
        if not self.is_configured():
            logger.warning("Gemini API key is not configured or too short.")
            return LLMResponse(
                content="[Gemini API key not configured. Inference unavailable.]",
                model=self.model,
                tokens_used=0,
                finish_reason="missing_config",
            )

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        result_dict = await self._post_generate(payload)
        status = result_dict.get("_status")

        if status == "success":
            return LLMResponse(
                content=result_dict.get("_text", ""),
                model=result_dict.get("_model", self.model),
                tokens_used=result_dict.get("_tokens", 0),
                finish_reason="STOP",
                raw_response=result_dict.get("_raw"),
            )
        else:
            return LLMResponse(
                content=f"[Gemini invocation failed: {result_dict.get('error', 'unknown')}]",
                model=self.model,
                tokens_used=0,
                finish_reason=status or "error",
                raw_response=result_dict,
            )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Dict[str, Any],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
    ) -> Dict[str, Any]:
        """Call Gemini API with structured JSON output schema."""
        if not self.is_configured():
            logger.info("Gemini API key not configured; structured generation returning missing_config.")
            return {
                "_status": "missing_config",
                "error": "Gemini API key not configured",
                "model": self.model,
            }

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        res = await self._post_generate(payload)
        status = res.get("_status")

        if status != "success":
            return res

        raw_text = res.get("_text", "").strip()
        # Clean any accidental markdown code fences
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                parsed["_status"] = "success"
                parsed["_model"] = res.get("_model", self.model)
                parsed["_tokens"] = res.get("_tokens", 0)
                return parsed
            else:
                logger.warning(f"Gemini returned valid JSON but not a dictionary: {type(parsed)}")
                return {
                    "_status": "invalid_response",
                    "error": "Model response was not a JSON object",
                    "raw_text": raw_text[:300],
                }
        except json.JSONDecodeError as exc:
            logger.warning(f"Failed to decode Gemini JSON response: {exc}")
            return {
                "_status": "invalid_response",
                "error": f"JSON parse error: {exc}",
                "raw_text": raw_text[:300],
            }

    async def _post_generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute POST to Gemini with bounded retries, exponential backoff, and model fallback."""
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        last_error = "Unknown error"
        last_status_code = None

        for model_candidate in self.candidate_models:
            url = f"{self.BASE_URL}/{model_candidate}:generateContent"

            for attempt in range(self.max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        resp = await client.post(url, headers=headers, json=payload)
                        last_status_code = resp.status_code

                        if resp.status_code == 200:
                            data = resp.json()
                            candidates = data.get("candidates", [])
                            if not candidates:
                                return {
                                    "_status": "invalid_response",
                                    "error": "No candidates returned by Gemini",
                                    "_model": model_candidate,
                                }
                            content_parts = candidates[0].get("content", {}).get("parts", [])
                            text_out = content_parts[0].get("text", "") if content_parts else ""
                            usage = data.get("usageMetadata", {})
                            tokens = usage.get("totalTokenCount", 0)
                            logger.info(
                                f"Gemini invocation succeeded via model '{model_candidate}' "
                                f"({tokens} tokens)"
                            )
                            return {
                                "_status": "success",
                                "_text": text_out,
                                "_model": model_candidate,
                                "_tokens": tokens,
                                "_raw": data,
                            }
                        elif resp.status_code == 404:
                            # Model not found or deprecated; break to next candidate model
                            logger.warning(f"Model '{model_candidate}' returned 404 Not Found; trying fallback.")
                            last_error = f"Model {model_candidate} not found (HTTP 404)"
                            break
                        elif resp.status_code in (429, 500, 502, 503, 504):
                            last_error = f"HTTP {resp.status_code} ({resp.text[:120]})"
                            if attempt < self.max_retries:
                                backoff = 0.5 * (2 ** attempt)
                                logger.info(
                                    f"Gemini {resp.status_code} on attempt {attempt + 1}; "
                                    f"retrying in {backoff:.1f}s..."
                                )
                                await asyncio.sleep(backoff)
                                continue
                            else:
                                logger.warning(
                                    f"Model '{model_candidate}' failed after {self.max_retries + 1} attempts ({last_error})"
                                )
                                break
                        else:
                            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
                            logger.warning(f"Gemini unexpected status {resp.status_code}: {last_error}")
                            break

                except httpx.TimeoutException as exc:
                    last_error = f"Timeout ({type(exc).__name__})"
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    break
                except httpx.RequestError as exc:
                    last_error = f"RequestError ({type(exc).__name__})"
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    break

        if "Timeout" in last_error:
            return {"_status": "timeout", "error": last_error, "model": self.model}
        return {
            "_status": "provider_failure",
            "error": last_error,
            "status_code": last_status_code,
            "model": self.model,
        }


def get_llm_client() -> BaseLLMClient:
    """Dependency provider for the LLM client abstraction."""
    return GeminiLLMClient()
