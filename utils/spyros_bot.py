import json
from openai import OpenAI
from .prompts import ANALYZE_PROMPT, CHAT_SYSTEM_PROMPT, FINALIZE_PROMPT


class SpyrosBot:
    """Pre-Sales AI Assistant powered by GPT-4o-mini"""
    
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o-mini"
    
    # ============================================
    # 1. ANALYZE: Classify user input
    # ============================================
    def analyze(self, user_input: str) -> dict:
        """Analyze and classify user input"""
        prompt = ANALYZE_PROMPT.format(user_input=user_input)
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a precise classification engine. Return ONLY JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        
        try:
            return json.loads(response.choices[0].message.content)
        except:
            return {
                "service_category": "Unknown",
                "confidence": 0.0,
                "missing_fields": []
            }
    
    # ============================================
    # 2. CHAT: Focused pre-sales conversation
    # ============================================
    def chat(self, user_message: str) -> str:
        """
        Pre-sales conversation - asks for specific fields sequentially.
        Returns either a question or final JSON report.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            max_tokens=500
        )
        
        return response.choices[0].message.content
    
    # ============================================
    # 3. FINALIZE: Generate structured report
    # ============================================
    def finalize(self, form_data: dict) -> dict:
        """Generate final structured automation report"""
        prompt = FINALIZE_PROMPT.format(form_data=json.dumps(form_data, ensure_ascii=False))
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a strict JSON generator. Return ONLY valid JSON. No markdown, no explanation."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        try:
            content = response.choices[0].message.content.strip()
            # Remove markdown code blocks if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content)
        except:
            return form_data