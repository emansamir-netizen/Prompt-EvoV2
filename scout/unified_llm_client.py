#!/usr/bin/env python3
"""
Unified LLM Client for SEED Framework
Supports multiple providers: Ollama, OpenAI, Anthropic, Azure, Groq,
OpenRouter, Finnhub, etc.

Usage:
    from unified_llm_client import UnifiedLLMClient, get_target, get_helper, get_embeddings

    # Create from config.yaml (recommended)
    target = get_target()
    helper = get_helper()
    embeddings = get_embeddings()

    # Or create manually
    client = UnifiedLLMClient.create_chat(
        provider="ollama",
        model="llama3:latest",
        temperature=0.7
    )
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional, Union
from abc import ABC, abstractmethod

# Default Ollama endpoint — overridable via env so the scout and runtime
# stay in sync when the user runs a non-default Ollama server.
_DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_DEFAULT_OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL",
                                          "https://openrouter.ai/api/v1")

# === LANGCHAIN IMPORTS ===
try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.embeddings import Embeddings
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    HAS_LANGCHAIN_CORE = True
except ImportError:
    HAS_LANGCHAIN_CORE = False
    print("Error: langchain-core not installed. Run: pip install langchain-core")

# Provider-specific imports
try:
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

try:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings, AzureChatOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    from langchain_anthropic import ChatAnthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

# Import config loader
try:
    from config_loader import get_config
except ImportError:
    get_config = None


class UnifiedLLMClient:
    """
    Factory class for creating LLM clients from any provider.
    All clients share a common interface via LangChain.
    """
    
    # Supported providers and their requirements
    PROVIDERS = {
        "ollama": {
            "chat_class": "ChatOllama",
            "embed_class": "OllamaEmbeddings",
            "available": HAS_OLLAMA,
            "requires_key": False
        },
        "openai": {
            "chat_class": "ChatOpenAI",
            "embed_class": "OpenAIEmbeddings",
            "available": HAS_OPENAI,
            "requires_key": True
        },
        "anthropic": {
            "chat_class": "ChatAnthropic",
            "embed_class": None,
            "available": HAS_ANTHROPIC,
            "requires_key": True
        },
        "azure": {
            "chat_class": "AzureChatOpenAI",
            "embed_class": "OpenAIEmbeddings",
            "available": HAS_OPENAI,
            "requires_key": True
        },
        "deepseek_cloud": {
            "chat_class": "ChatOpenAI",
            "embed_class": None,
            "available": HAS_OPENAI,
            "requires_key": True
        },
        "groq": {
            "chat_class": "ChatOpenAI",
            "embed_class": None,
            "available": HAS_OPENAI,
            "requires_key": True
        },
        "openrouter": {
            "chat_class": "ChatOpenAI",
            "embed_class": None,
            "available": HAS_OPENAI,
            "requires_key": True
        },
        "finnhub": {
            "chat_class": "FinnhubLLM",
            "embed_class": None,
            "available": True,
            "requires_key": True
        },
        "gemini": {
            "chat_class": "ChatGoogleGenerativeAI",
            "embed_class": None,
            "available": HAS_GOOGLE,
            "requires_key": True
        }
    }
    
    @classmethod
    def list_available_providers(cls) -> List[str]:
        """List all available (installed) providers."""
        return [p for p, info in cls.PROVIDERS.items() if info["available"]]
    
    @classmethod
    def create_chat(
        cls,
        provider: str = "ollama",
        model: Optional[str] = None,
        temperature: float = 0.7,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ) -> BaseChatModel:
        """
        Create a chat model client for any provider.
        
        Args:
            provider: Provider name (ollama, openai, anthropic, azure, groq, deepseek_cloud, finnhub)
            model: Model name
            temperature: Creativity level (0.0-1.0)
            api_key: API key (required for cloud providers)
            base_url: Custom API endpoint (optional)
            **kwargs: Additional provider-specific arguments
            
        Returns:
            LangChain BaseChatModel instance or FinnhubLLM
        """
        provider = provider.lower()

        if provider not in cls.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(cls.PROVIDERS.keys())}")

        # Validate model presence BEFORE checking backend availability so the
        # "no silent default" contract holds regardless of which LC packages
        # happen to be installed in the caller's environment.  Providers that
        # have a known-safe auto-fallback (e.g. Finnhub) are exempt.
        _requires_explicit_model = {"ollama", "groq", "openrouter",
                                    "deepseek_cloud", "anthropic", "openai",
                                    "azure"}
        if provider in _requires_explicit_model and not model:
            raise ValueError(
                f"{provider} requires an explicit model name — "
                "no hardcoded default so dynamic model switching is "
                "authoritative."
            )

        provider_info = cls.PROVIDERS[provider]

        if not provider_info["available"]:
            raise ImportError(
                f"Provider '{provider}' is not available. "
                f"Install the required package (e.g., pip install langchain-{provider})"
            )
        
        # === FINNHUB ===
        if provider == "finnhub":
            try:
                from finnhub_llm import FinnhubLLM
                return FinnhubLLM(api_key=api_key, use_config=(api_key is None))
            except ImportError:
                raise ImportError("finnhub_llm.py not found. Make sure it's in the same directory.")
        
        # === OLLAMA ===
        elif provider == "ollama":
            if not model:
                raise ValueError(
                    "Ollama requires an explicit model name (no hardcoded "
                    "default so dynamic model switching cannot be silently "
                    "overridden)."
                )
            return ChatOllama(
                model=model,
                temperature=temperature,
                base_url=base_url or _DEFAULT_OLLAMA_BASE_URL,
                **kwargs
            )
        
        # === OPENAI ===
        elif provider == "openai":
            if not api_key:
                raise ValueError("OpenAI requires an API key")
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url,
                **kwargs
            )
        
        # === ANTHROPIC ===
        elif provider == "anthropic":
            if not api_key:
                raise ValueError("Anthropic requires an API key")
            return ChatAnthropic(
                model=model,
                temperature=temperature,
                api_key=api_key,
                **kwargs
            )
        
        # === AZURE ===
        elif provider == "azure":
            if not api_key or not base_url:
                raise ValueError("Azure requires api_key and base_url (endpoint)")
            return AzureChatOpenAI(
                azure_deployment=model,
                temperature=temperature,
                api_key=api_key,
                azure_endpoint=base_url,
                api_version=kwargs.get("api_version", "2024-02-15-preview"),
                **{k: v for k, v in kwargs.items() if k != "api_version"}
            )
        
        # === DEEPSEEK CLOUD ===
        elif provider == "deepseek_cloud":
            if not api_key:
                raise ValueError("DeepSeek Cloud requires an API key")
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url or "https://api.deepseek.com/v1",
                **kwargs
            )
        
        # === GROQ ===
        elif provider == "groq":
            if not api_key:
                raise ValueError("Groq requires an API key")
            if not model:
                raise ValueError("Groq requires an explicit model name")
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url or "https://api.groq.com/openai/v1",
                **kwargs
            )

        # === GEMINI ===
        elif provider == "gemini":
            if not api_key:
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    raise ValueError("Gemini requires an API key (GEMINI_API_KEY)")
            if not model:
                model = "gemini-1.5-pro"
            return ChatGoogleGenerativeAI(
                model=model,
                temperature=temperature,
                api_key=api_key,
                **kwargs
            )

        # === OPENROUTER ===
        # OpenRouter is OpenAI-API compatible; it proxies to dozens of
        # hosted models via slugs like "openai/gpt-4o-mini" or
        # "anthropic/claude-haiku".  Single branch via ChatOpenAI + base_url.
        elif provider == "openrouter":
            if not api_key:
                raise ValueError("OpenRouter requires an API key")
            if not model:
                raise ValueError(
                    "OpenRouter requires an explicit model slug "
                    "(e.g. 'openai/gpt-4o-mini')"
                )
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url or _DEFAULT_OPENROUTER_BASE_URL,
                **kwargs
            )

        else:
            raise ValueError(f"Provider '{provider}' is not implemented")
    
    @classmethod
    def create_embeddings(
        cls,
        provider: str = "ollama",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ) -> Embeddings:
        """
        Create an embeddings client for any provider.
        """
        provider = provider.lower().strip()
        
        # 1. OpenAI / Azure (Native support)
        if provider in ["openai", "azure"]:
            if not api_key:
                from config import settings
                api_key = api_key or settings.openai_api_key
            if not api_key:
                raise ValueError(f"{provider} embeddings require an API key")
            return OpenAIEmbeddings(
                model=model or "text-embedding-3-small",
                api_key=api_key,
                base_url=base_url,
                **kwargs
            )
        
        # 2. Ollama (Native support)
        if provider == "ollama" or (provider in cls.PROVIDERS and cls.PROVIDERS[provider].get("embed_class") == "OllamaEmbeddings"):
            return OllamaEmbeddings(
                model=model or "llama3.2:1b",
                base_url=base_url or _DEFAULT_OLLAMA_BASE_URL,
                **kwargs
            )
            
        # 3. Fallback for others (Groq, Anthropic, etc. do NOT support embeddings via Chat class)
        print(f"[WARN] Provider '{provider}' does not support native embeddings. Falling back to local Ollama.")
        return OllamaEmbeddings(
            model=model or "llama3.2:1b",
            base_url=base_url or _DEFAULT_OLLAMA_BASE_URL,
        )


class TargetLLM:
    """
    High-level wrapper for the target LLM (the one being tested/inquiryed).
    Provides a simple interface for asking questions.
    """
    
    def __init__(
        self,
        provider: str = "ollama",
        model: Optional[str] = None,
        temperature: float = 0.7,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        """Initialize the target LLM.

        ``model`` is now required (no hardcoded silent default) so dynamic
        target-model switching actually works — the framework will never
        quietly fall back to a stale ``deepseek-r1:1.5b`` default when the
        caller asked for something else.
        """
        if not model:
            raise ValueError(
                "TargetLLM requires an explicit model name; pass "
                "`model=...` or configure `target_model` in config.yaml."
            )
        self.provider = provider
        self.model = model
        self.temperature = temperature
        
        print(f"[INIT] Initializing Target LLM: {provider}/{model}")
        
        self.llm = UnifiedLLMClient.create_chat(
            provider=provider,
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            **kwargs
        )
        
        print(f"[OK] Target ready: {self}")
    
    def ask(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        Send a prompt to the target and get a response.
        
        Args:
            prompt: The user's question/prompt
            system_prompt: Optional system context
            temperature: Override temperature for this request
            
        Returns:
            The model's response as a string
        """
        max_retries = 3
        retry_delay = 2.0  # seconds
        
        for attempt in range(max_retries + 1):
            try:
                # Check if this is FinnhubLLM (doesn't use LangChain messages)
                if self.provider == "finnhub":
                    return self.llm.ask(prompt, system_prompt, temperature)
                
                # Build messages for standard LLMs
                messages = []
                if system_prompt:
                    messages.append(SystemMessage(content=system_prompt))
                messages.append(HumanMessage(content=prompt))
                
                # Update temperature if specified
                if temperature is not None:
                    # Some LangChain models use .temperature, others use .model_kwargs
                    if hasattr(self.llm, 'temperature'):
                        self.llm.temperature = temperature
                
                # Invoke
                response = self.llm.invoke(messages)
                return response.content.strip()
                
            except Exception as e:
                error_str = str(e).lower()
                
                # Check for rate limit (429) errors
                if "429" in error_str or "rate limit" in error_str:
                    if attempt < max_retries:
                        wait_time = retry_delay * (2 ** attempt)
                        print(f"⚠️ [RATE LIMIT] 429 Error. Retrying in {wait_time:.1f}s... (Attempt {attempt+1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"❌ [ERROR] Max retries reached for Rate Limit. Moving on.")
                
                print(f"[ERROR] Target error: {e}")
                return f"Error: {str(e)}"
        
        return "Error: Max retries exceeded"
    
    # Alias for backward compatibility
    def answer_question(self, prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.7) -> str:
        """Backward-compatible alias for ask()."""
        return self.ask(prompt, system_prompt, temperature)
    
    def __repr__(self) -> str:
        return f"TargetLLM(provider={self.provider}, model={self.model})"


# === CONVENIENCE FUNCTIONS ===

def get_target(config_path: Optional[str] = None) -> TargetLLM:
    """
    Create a TargetLLM from config.yaml.
    
    Usage:
        target = get_target()
        response = target.ask("Hello, who are you?")
    """
    if get_config is None:
        # No config loader — require the caller to have set env vars.
        # We intentionally do NOT inject a hardcoded model default, so
        # dynamic model switching is authoritative.
        env_model = os.getenv("TARGET_MODEL") or os.getenv("OLLAMA_MODEL")
        if not env_model:
            raise RuntimeError(
                "scout.get_target: no config loader and no TARGET_MODEL/"
                "OLLAMA_MODEL env var set.  Cannot choose a target model."
            )
        return TargetLLM(
            provider = os.getenv("TARGET_PROVIDER", "ollama"),
            model    = env_model,
        )
    
    config = get_config(config_path)
    provider_settings = config.get_provider_settings(config.target_provider)
    
    return TargetLLM(
        provider=config.target_provider,
        model=config.target_model,
        temperature=config.target_temperature,
        api_key=provider_settings.get("api_key"),
        base_url=provider_settings.get("base_url")
    )


def get_helper(config_path: Optional[str] = None) -> BaseChatModel:
    """
    Create a helper LLM from config.yaml.
    
    Usage:
        helper = get_helper()
        response = helper.invoke([HumanMessage(content="Generate a question")])
    """
    if get_config is None:
        return UnifiedLLMClient.create_chat()
    
    config = get_config(config_path)
    provider_settings = config.get_provider_settings(config.helper_provider)
    
    return UnifiedLLMClient.create_chat(
        provider=config.helper_provider,
        model=config.helper_model,
        temperature=config.helper_temperature,
        api_key=provider_settings.get("api_key"),
        base_url=provider_settings.get("base_url")
    )


def get_embeddings(config_path: Optional[str] = None) -> Embeddings:
    """
    Create an embeddings client from config.yaml.
    
    Usage:
        embeddings = get_embeddings()
        vector = embeddings.embed_query("Hello world")
    """
    if get_config is None:
        return UnifiedLLMClient.create_embeddings()
    
    config = get_config(config_path)
    provider_settings = config.get_provider_settings(config.embedding_provider)
    
    return UnifiedLLMClient.create_embeddings(
        provider=config.embedding_provider,
        model=config.embedding_model,
        api_key=provider_settings.get("api_key"),
        base_url=provider_settings.get("base_url")
    )


# === CLI TEST ===
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Unified LLM Client")
    parser.add_argument("--provider", default="ollama", help="Provider name")
    parser.add_argument("--model", default=None, help="Model name (optional)")
    parser.add_argument("--prompt", default="Hello! Who are you?", help="Test prompt")
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("UNIFIED LLM CLIENT TEST")
    print("=" * 60)
    
    print(f"\n📋 Available providers: {UnifiedLLMClient.list_available_providers()}")
    
    # Test with config
    print("\n--- Testing from config.yaml ---")
    try:
        target = get_target()
        response = target.ask(args.prompt)
        print(f"\n[TARGET] {target}")
        print(f"📝 Prompt: {args.prompt}")
        print(f"🤖 Response: {response[:200]}...")
    except Exception as e:
        print(f"[ERROR] Error: {e}")
    
    # Test embeddings
    print("\n--- Testing Embeddings ---")
    try:
        embeddings = get_embeddings()
        test_vec = embeddings.embed_query("test embedding")
        print(f"[OK] Embedding dimension: {len(test_vec)}")
    except Exception as e:
        print(f"[ERROR] Embedding error: {e}")
    
    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
