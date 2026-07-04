import json
import re
from typing import Dict, Optional, Tuple
import streamlit as st
from openai import OpenAI
from utils.prompts import ARTICLE_GENERATION_PROMPT, SOCIAL_TEASER_PROMPT


class ArticleGenerator:
    """Generate blog articles and social media teasers using GPT-4mini"""
    
    def __init__(self):
        """Initialize OpenAI client with API key from Streamlit secrets"""
        self.api_key = st.secrets.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in Streamlit secrets")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4o-mini"  # Cheap model for now
    
    def generate_article(
        self, 
        extracted_content: str, 
        target_point: str, 
        category: str
    ) -> Optional[Dict]:
        """
        Generate a 500-word article based on extracted content
        
        Args:
            extracted_content: Raw content from Jina extraction
            target_point: Keywords/target (e.g., "automation excel outreach")
            category: Article category (e.g., "Excel & Reporting")
        
        Returns:
            Dictionary with title, content, keywords, word_count or None if failed
        """
        try:
            # Prepare the prompt
            prompt_text = ARTICLE_GENERATION_PROMPT.format(
                target_point=target_point,
                category=category,
                extracted_content=extracted_content[:2000]  # Limit input to avoid token issues
            )
            
            # Call GPT-4mini
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                messages=[
                    {
                        "role": "user",
                        "content": prompt_text
                    }
                ]
            )
            
            # Extract response
            response_text = response.content[0].text
            
            # Parse JSON
            article_data = self._parse_json_response(response_text)
            
            if not article_data:
                st.error("Failed to parse article generation response")
                return None
            
            # Validate article length
            if article_data.get("word_count", 0) < 400:
                st.warning(f"Generated article is only {article_data.get('word_count', 0)} words. Retrying...")
                return self.generate_article(extracted_content, target_point, category)
            
            return article_data
            
        except Exception as e:
            st.error(f"Error generating article: {str(e)}")
            return None
    
    def generate_social_teasers(
        self, 
        title: str, 
        category: str, 
        keywords: list
    ) -> Optional[Dict]:
        """
        Generate social media teasers for the article
        
        Args:
            title: Article title
            category: Article category
            keywords: List of keywords
        
        Returns:
            Dictionary with twitter, linkedin, facebook teasers or None if failed
        """
        try:
            # Format keywords for prompt
            keywords_str = ", ".join(keywords) if keywords else ""
            
            # Prepare the prompt
            prompt_text = SOCIAL_TEASER_PROMPT.format(
                title=title,
                category=category,
                keywords=keywords_str
            )
            
            # Call GPT-4mini
            response = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                messages=[
                    {
                        "role": "user",
                        "content": prompt_text
                    }
                ]
            )
            
            # Extract response
            response_text = response.content[0].text
            
            # Parse JSON
            teasers_data = self._parse_json_response(response_text)
            
            if not teasers_data:
                st.error("Failed to parse social teasers response")
                return None
            
            return teasers_data
            
        except Exception as e:
            st.error(f"Error generating social teasers: {str(e)}")
            return None
    
    def _parse_json_response(self, response_text: str) -> Optional[Dict]:
        """
        Extract and parse JSON from LLM response
        
        Args:
            response_text: Raw response text from LLM
        
        Returns:
            Parsed dictionary or None if parsing fails
        """
        try:
            # Try to find JSON block in response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            
            if not json_match:
                st.error("No JSON found in response")
                return None
            
            json_str = json_match.group(0)
            parsed_data = json.loads(json_str)
            
            return parsed_data
            
        except json.JSONDecodeError as e:
            st.error(f"JSON parsing error: {str(e)}")
            return None
        except Exception as e:
            st.error(f"Unexpected error in JSON parsing: {str(e)}")
            return None
    
    def full_pipeline(
        self, 
        extracted_content: str, 
        target_point: str, 
        category: str
    ) -> Optional[Tuple[Dict, Dict]]:
        """
        Run full pipeline: Generate article + Generate teasers
        
        Args:
            extracted_content: Raw content from Jina
            target_point: Target keywords
            category: Article category
        
        Returns:
            Tuple of (article_data, teasers_data) or None if failed
        """
        try:
            # Step 1: Generate article
            with st.spinner("✍️ Generating article..."):
                article = self.generate_article(extracted_content, target_point, category)
            
            if not article:
                return None
            
            # Step 2: Generate social teasers
            with st.spinner("📱 Generating social teasers..."):
                teasers = self.generate_social_teasers(
                    title=article.get("title", ""),
                    category=category,
                    keywords=article.get("keywords", [])
                )
            
            if not teasers:
                return None
            
            return (article, teasers)
            
        except Exception as e:
            st.error(f"Error in full pipeline: {str(e)}")
            return None


# ============================================
# EXPORT FUNCTION
# ============================================
if __name__ == "__main__":
    # Test the generator
    generator = ArticleGenerator()
    result = generator.generate_article(
        extracted_content="Sample content about automation...",
        target_point="automation excel",
        category="Excel & Reporting"
    )
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))