"""Minimal client for a local Ollama server (free, CPU-friendly open models)."""

import requests

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:1.5b"


class OllamaClient:
    def __init__(self, url: str = DEFAULT_URL, model: str = DEFAULT_MODEL, timeout: float = 120.0, session=None):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout
        self.session = session or requests.Session()

    def available(self) -> bool:
        try:
            tags = self.session.get(f"{self.url}/api/tags", timeout=5).json()
        except (requests.RequestException, ValueError):
            return False
        return any(m.get("name", "").startswith(self.model) for m in tags.get("models", []))

    def generate(self, prompt: str) -> str:
        resp = self.session.post(
            f"{self.url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 160, "seed": 7},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["response"]
