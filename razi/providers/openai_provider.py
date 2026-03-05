import os
from typing import Dict, Any

from openai import OpenAI
from .base import Provider

class OpenAIProvider(Provider):
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def synthesize(self, prompt: str, schema: Dict[str, Any], model_config: Dict[str, Any]) -> str:
        model = model_config.get("model", "gpt-4o-mini")
        temperature = model_config.get("temperature", 0.2)

        ans = self.client.chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a precise data extractor. You must always output perfectly formatted JSON matching the provided schema."},
                {"role": "user", "content": prompt}
            ]
        )
        return ans.choices[0].message.content
