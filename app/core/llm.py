"""Isolated LLM client service abstraction interface.

Decouples the rest of the application from specific LLM providers (e.g. Google Gemini API).
Prevents LLM logic from scattering across pipeline stages.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.config import get_settings


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
    """Isolated Google Gemini API client implementation."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL

    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Call Gemini API.

        TODO: Implement real Gemini Live/Interactions/Decisions API client calls using httpx or google-genai.
        """
        if not self.api_key:
            return LLMResponse(
                content="[MOCK LLM: Gemini API key not configured. Skeleton response.]",
                model=self.model,
                tokens_used=0,
                finish_reason="mock_completed",
            )

        # Honest placeholder when API is configured but pipeline is not yet implemented
        return LLMResponse(
            content=f"[LLM Service Ready: model={self.model}. Real inference pipeline pending.]",
            model=self.model,
            tokens_used=0,
            finish_reason="skeleton_mock",
        )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Dict[str, Any],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
    ) -> Dict[str, Any]:
        """Call Gemini API with structured JSON output schema."""
        return {
            "status": "skeleton_placeholder",
            "model": self.model,
            "message": "Structured LLM generation interface ready. Production verification logic pending.",
        }


def get_llm_client() -> BaseLLMClient:
    """Dependency provider for the LLM client abstraction."""
    return GeminiLLMClient()

