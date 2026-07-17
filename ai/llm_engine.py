"""LLM Engine for AI-powered strategy analysis and generation."""

import os
import json
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from abc import ABC, abstractmethod
import requests

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"  # Local
    OPENROUTER = "openrouter"
    MOCK = "mock"  # For testing without API


@dataclass
class LLMResponse:
    """Response from LLM."""
    content: str
    raw: dict
    model: str
    tokens_used: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0


class BaseLLM(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def generate(self, prompt: str, system: str = None, **kwargs) -> LLMResponse:
        """Generate response from LLM."""
        pass

    @abstractmethod
    def name(self) -> str:
        """Get provider name."""
        pass


class MockLLM(BaseLLM):
    """Mock LLM for testing without API."""

    def __init__(self, *args, **kwargs):
        self.call_count = 0

    def generate(self, prompt: str, system: str = None, **kwargs) -> LLMResponse:
        """Generate mock response."""
        self.call_count += 1
        return LLMResponse(
            content=f"Mock response #{self.call_count}: Analyzed and evolved strategy based on prompt.",
            raw={"mock": True},
            model="mock-llm",
            tokens_used=100,
            cost=0.0,
            latency_ms=10.0
        )

    def name(self) -> str:
        return "mock"


class OpenAILLM(BaseLLM):
    """OpenAI GPT-4 integration."""

    def __init__(self, api_key: str = None, model: str = "gpt-4-turbo"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = "https://api.openai.com/v1"

    def generate(self, prompt: str, system: str = None, **kwargs) -> LLMResponse:
        """Generate using OpenAI API."""
        start = time.time()
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2000),
        }
        
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=120
            )
            resp.raise_for_status()
            result = resp.json()
            
            content = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})
            
            return LLMResponse(
                content=content,
                raw=result,
                model=self.model,
                tokens_used=usage.get("total_tokens", 0),
                cost=usage.get("total_tokens", 0) * 0.00001,  # Approximate
                latency_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    def name(self) -> str:
        return f"openai/{self.model}"


class AnthropicLLM(BaseLLM):
    """Anthropic Claude integration."""

    def __init__(self, api_key: str = None, model: str = "claude-3-opus-20240229"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self.base_url = "https://api.anthropic.com/v1"

    def generate(self, prompt: str, system: str = None, **kwargs) -> LLMResponse:
        """Generate using Anthropic API."""
        start = time.time()
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        
        messages = [{"role": "user", "content": prompt}]
        
        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 2000),
            "temperature": kwargs.get("temperature", 0.7),
        }
        
        if system:
            data["system"] = system
        
        try:
            resp = requests.post(
                f"{self.base_url}/messages",
                headers=headers,
                json=data,
                timeout=120
            )
            resp.raise_for_status()
            result = resp.json()
            
            content = result["content"][0]["text"]
            
            return LLMResponse(
                content=content,
                raw=result,
                model=self.model,
                tokens_used=result.get("usage", {}).get("input_tokens", 0),
                cost=result.get("usage", {}).get("input_tokens", 0) * 0.000015,
                latency_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise

    def name(self) -> str:
        return f"anthropic/{self.model}"


class OllamaLLM(BaseLLM):
    """Ollama local LLM integration."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url
        self.model = model

    def generate(self, prompt: str, system: str = None, **kwargs) -> LLMResponse:
        """Generate using Ollama API."""
        start = time.time()
        
        data = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        
        if system:
            data["system"] = system
        
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=data,
                timeout=300
            )
            resp.raise_for_status()
            result = resp.json()
            
            return LLMResponse(
                content=result.get("response", ""),
                raw=result,
                model=self.model,
                tokens_used=result.get("eval_count", 0),
                cost=0.0,  # Free for local
                latency_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            raise

    def name(self) -> str:
        return f"ollama/{self.model}"


class LLMEngine:
    """Main LLM engine with provider routing."""

    SYSTEM_PROMPT = """You are an expert cryptocurrency trading strategy analyst. Your job is to:
1. Analyze backtest results and find winning patterns
2. Suggest improvements to trading strategy parameters
3. Identify market conditions where strategies work best
4. Propose new hybrid strategies based on observed behavior

Be precise, quantitative, and focus on data-driven insights."""

    STRATEGY_ANALYSIS_PROMPT = """Analyze this backtest result and identify key patterns:

{backtest_summary}

Top performers:
{top_strategies}

Worst performers:
{worst_strategies}

Provide:
1. Key insight about what makes top strategies successful
2. Specific parameter adjustments to improve underperforming strategies
3. A proposed new strategy configuration"""

    PARAMETER_EVOLUTION_PROMPT = """Based on the analysis of {num_generations} generations of strategies:

Best parameters found: {best_params}
Best score achieved: {best_score}

Current market conditions summary: {market_summary}

Suggest the next generation of parameters that:
1. Exploits the patterns found in successful strategies
2. Explores new areas not yet tested
3. Maintains diversity to avoid overfitting

Return ONLY a JSON object with the suggested parameters."""

    def __init__(
        self,
        provider: LLMProvider = LLMProvider.MOCK,
        api_key: str = None,
        model: str = None,
        **kwargs
    ):
        """Initialize LLM engine."""
        self.provider = provider
        
        if provider == LLMProvider.OPENAI:
            self.llm = OpenAILLM(api_key=api_key, model=model or "gpt-4-turbo")
        elif provider == LLMProvider.ANTHROPIC:
            self.llm = AnthropicLLM(api_key=api_key, model=model or "claude-3-opus-20240229")
        elif provider == LLMProvider.OLLAMA:
            self.llm = OllamaLLM(model=model or "llama3")
        else:
            self.llm = MockLLM()
        
        self.total_cost = 0.0
        self.total_tokens = 0
        self.total_calls = 0

    def analyze_backtest(
        self,
        backtest_results: list[dict],
        top_n: int = 5
    ) -> dict[str, Any]:
        """Analyze backtest results and generate insights."""
        # Sort by score
        sorted_results = sorted(backtest_results, key=lambda x: x.get("score", 0), reverse=True)
        
        top = sorted_results[:top_n]
        worst = sorted_results[-top_n:] if len(sorted_results) >= top_n else []
        
        # Format for prompt
        top_str = "\n".join([
            f"- {r.get('strategy', 'unknown')}: {r.get('score', 0):.4f} | {r.get('params', {})}"
            for r in top
        ])
        
        worst_str = "\n".join([
            f"- {r.get('strategy', 'unknown')}: {r.get('score', 0):.4f} | {r.get('params', {})}"
            for r in worst
        ])
        
        prompt = self.STRATEGY_ANALYSIS_PROMPT.format(
            backtest_summary=self._summarize_results(backtest_results),
            top_strategies=top_str,
            worst_strategies=worst_str
        )
        
        response = self.llm.generate(prompt, system=self.SYSTEM_PROMPT)
        self._track_usage(response)
        
        return {
            "insights": response.content,
            "top_strategies": top,
            "total_analyzed": len(backtest_results)
        }

    def evolve_parameters(
        self,
        history: list[dict],
        best_params: dict,
        best_score: float,
        market_context: str = "normal volatility"
    ) -> dict[str, Any]:
        """Evolve parameters based on history."""
        prompt = self.PARAMETER_EVOLUTION_PROMPT.format(
            num_generations=len(history),
            best_params=json.dumps(best_params, indent=2),
            best_score=f"{best_score:.6f}",
            market_summary=market_context
        )
        
        response = self.llm.generate(prompt, system=self.SYSTEM_PROMPT, temperature=0.9)
        self._track_usage(response)
        
        # Parse JSON from response
        try:
            # Try to extract JSON from response
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            params = json.loads(content.strip())
            return params
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from LLM, using fallback")
            return self._fallback_evolution(best_params, best_score)

    def generate_strategy_idea(self, context: dict) -> dict[str, Any]:
        """Generate a completely new strategy idea."""
        prompt = f"""Based on this context, propose a novel trading strategy:

{json.dumps(context, indent=2)}

Describe the strategy with specific parameters. Return as JSON."""

        response = self.llm.generate(prompt, system=self.SYSTEM_PROMPT, temperature=1.0)
        self._track_usage(response)
        
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            
            return json.loads(content.strip())
        except:
            return {"strategy": "fallback", "params": {"threshold": 1.05}}

    def _summarize_results(self, results: list[dict]) -> str:
        """Create summary of results."""
        if not results:
            return "No results to analyze"
        
        scores = [r.get("score", 0) for r in results]
        
        return f"""
Total strategies tested: {len(results)}
Score range: {min(scores):.4f} to {max(scores):.4f}
Average score: {sum(scores)/len(scores):.4f}
Median score: {sorted(scores)[len(scores)//2]:.4f}
"""

    def _fallback_evolution(self, best_params: dict, best_score: float) -> dict:
        """Fallback evolution when JSON parsing fails."""
        import random
        evolved = best_params.copy()
        
        # Small random perturbations
        for key, value in evolved.items():
            if isinstance(value, float):
                evolved[key] = value * random.uniform(0.9, 1.1)
            elif isinstance(value, int):
                evolved[key] = max(1, int(value * random.uniform(0.8, 1.2)))
        
        return evolved

    def _track_usage(self, response: LLMResponse) -> None:
        """Track API usage."""
        self.total_calls += 1
        self.total_tokens += response.tokens_used
        self.total_cost += response.cost

    def get_stats(self) -> dict:
        """Get usage statistics."""
        return {
            "provider": self.llm.name(),
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost
        }
