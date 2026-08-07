"""Shared OpenRouter client."""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

EXTRACTION_MODEL = "google/gemini-3.1-flash-lite"


def get_client() -> OpenAI:
    """Return an OpenAI SDK client pointed at OpenRouter.

    The key is read from the environment, never hardcoded.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)
