DEFAULT_MODELS = {
    "openai": "text-embedding-3-large",
    "asicloud": "WhereIsAI/UAE-Large-V1",
}

DIMENSIONS = {
    "text-embedding-3-large": 3072,
    "WhereIsAI/UAE-Large-V1": 1024,
}


def embedding_model(provider, configured=None):
    configured = str(configured or "").strip()
    if configured:
        return configured
    return DEFAULT_MODELS.get(str(provider).casefold(), DEFAULT_MODELS["openai"])
