def model_factory(settings):
    common = {"max_tokens": settings.llm_max_output_tokens}
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI

        # Reasoning models do not accept the same temperature contract as GPT-4o/4.1.
        options = (
            {}
            if settings.openai_model.startswith(("gpt-5", "o1", "o3", "o4"))
            else {"temperature": settings.llm_temperature}
        )
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
            **({"base_url": settings.openai_base_url} if settings.openai_base_url else {}),
            **common,
            **options,
        )
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key.get_secret_value(),
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
            **common,
        )
    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
            num_ctx=4096,
            num_predict=settings.llm_max_output_tokens,
            keep_alive="5m",
            client_kwargs={"timeout": settings.llm_timeout_seconds},
        )
    raise ValueError("Unsupported provider")
