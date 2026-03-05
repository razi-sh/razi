from typing import Dict, Any

from openai import OpenAI
from .base import Provider

class OllamaProvider(Provider):
    def __init__(self):
        # Ollama provides an OpenAI API-compatible endpoint by default.
        # It doesn't require an API key, but the client requires the param.
        self.client = OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"
        )

    def synthesize(self, prompt: str, schema: Dict[str, Any], model_config: Dict[str, Any]) -> str:
        # Test mode should override the spec's production model.
        # Use explicitly provided --test-model, otherwise default to "llama3.1:8b"
        model = getattr(self, "_test_model", None)
        if not model:
            model = "llama3.1:8b"
            
        temperature = model_config.get("temperature", 0.2)

        ans = self.client.chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system", 
                    "content": "You are a strict data-generation engine. You MUST output a JSON object populated with real data that satisfies the provided schema. DO NOT output the JSON schema itself."
                },
                {"role": "user", "content": prompt}
            ]
        )
        return ans.choices[0].message.content
