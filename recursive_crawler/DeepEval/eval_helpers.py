# eval_helpers.py

import re
from openai import OpenAI, AsyncOpenAI
from deepeval.models.base_model import DeepEvalBaseLLM

# Setup the client we will use for the Pairwise Judge
vllm_client = AsyncOpenAI(
    api_key="no-key",
    base_url="http://localhost:5000/v1"
)

def sanitize_text_for_json(text):
    """Removes invalid control characters that cause JSONDecodeErrors in DeepEval."""
    if not text:
        return ""
    if isinstance(text, list):
        return [sanitize_text_for_json(t) for t in text]
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', str(text))

class LocalVLLMJudge(DeepEvalBaseLLM):
    def __init__(self, model_name="qwen35", base_url="http://localhost:5000/v1"):
        self.model_name = model_name
        self.base_url = base_url
        self.sync_client = OpenAI(api_key="no-key", base_url=self.base_url)
        self.async_client = AsyncOpenAI(api_key="no-key", base_url=self.base_url)

    def load_model(self):
        return self.model_name

    def generate(self, prompt: str) -> str:
        response = self.sync_client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0 
        )
        return response.choices[0].message.content

    async def a_generate(self, prompt: str) -> str:
        response = await self.async_client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        return response.choices[0].message.content

    def get_model_name(self):
        return "Local-vLLM-" + self.model_name

async def judge_systems_head_to_head(query: str, ans_a: str, ans_b: str) -> str:
    """Asks the local vLLM to compare both answers and declare a winner."""
    if "Agent Loop Error" in ans_a and "Agent Loop Error" in ans_b:
        return "Tie (Both Failed)"
        
    prompt = f"""
    You are an impartial, expert AI judge evaluating two government assistant systems.
    
    User Query: "{query}"
    System A Answer: "{ans_a}"
    System B Answer: "{ans_b}"
    
    Evaluate which system provided a better, more accurate, and more formal Bengali response.
    Penalize any response that contains system errors (like "Agent Loop Error") or hallucinations.
    
    You must respond STRICTLY with exactly one of these three options and absolutely nothing else:
    System A
    System B
    Tie
    """
    try:
        response = await vllm_client.chat.completions.create(
            model="qwen35",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Judge Error: {str(e)}"