def endpoint_from_settings(settings):
    """The configured endpoint as a plain spec.

    Callers pass an explicit endpoint so a turn already running cannot pick up a model someone
    else switched to halfway through. This is the fallback for callers without one.
    """
    provider = settings.llm_provider
    keys = {"openai": settings.openai_api_key, "anthropic": settings.anthropic_api_key}
    urls = {"openai": settings.openai_base_url, "ollama": settings.ollama_base_url}
    key = keys.get(provider)
    return {
        "provider": provider,
        "model": settings.model_name,
        "base_url": urls.get(provider, ""),
        "api_key": key.get_secret_value() if key else "",
    }


def model_factory(settings, endpoint=None):
    spec = endpoint or endpoint_from_settings(settings)
    provider, model = spec["provider"], spec["model"]
    base_url, api_key = spec.get("base_url") or "", spec.get("api_key") or ""
    common = {"max_tokens": settings.llm_max_output_tokens}
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        # Reasoning models do not accept the same temperature contract as GPT-4o/4.1.
        options = (
            {}
            if model.startswith(("gpt-5", "o1", "o3", "o4"))
            else {"temperature": settings.llm_temperature}
        )
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
            **({"base_url": base_url} if base_url else {}),
            **common,
            **options,
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            api_key=api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
            **common,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            base_url=base_url or settings.ollama_base_url,
            temperature=settings.llm_temperature,
            num_ctx=4096,
            num_predict=settings.llm_max_output_tokens,
            keep_alive="5m",
            client_kwargs={"timeout": settings.llm_timeout_seconds},
        )
    raise ValueError("Unsupported provider")
