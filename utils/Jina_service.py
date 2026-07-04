import requests
import json
from typing import Dict, Optional
import streamlit as st


class JinaService:
    """Service to extract content from web using Jina AI"""
    
    def __init__(self):
        """Initialize Jina service with API key from Streamlit secrets"""
        self.api_key = st.secrets.get("JINA_API_KEY")
        if not self.api_key:
            raise ValueError("JINA_API_KEY not found in Streamlit secrets")
        
        self.base_url = "https://api.jina.ai/v1/extract"
        self.search_url = "https://api.jina.ai/v1/search"
    
    def search_and_extract(self, target_point: str, max_results: int = 1) -> Optional[Dict]:
        """
        Search for content related to target_point and extract it
        
        Args:
            target_point: Keywords to search for (e.g., "automation excel outreach")
            max_results: Number of results to try (default: 1)
        
        Returns:
            Dictionary with extracted content or None if failed
        """
        try:
            # Step 1: Search for the target point
            search_payload = {
                "query": target_point,
                "limit": max_results
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Make search request
            search_response = requests.post(
                self.search_url,
                json=search_payload,
                headers=headers,
                timeout=30
            )
            
            if search_response.status_code != 200:
                st.error(f"Search failed: {search_response.text}")
                return None
            
            search_results = search_response.json()
            
            if not search_results.get("results"):
                st.warning("No search results found for this target point")
                return None
            
            # Step 2: Extract content from the first result
            source_url = search_results["results"][0].get("url")
            
            if not source_url:
                st.error("No URL found in search results")
                return None
            
            # Extract content from the URL
            extracted_data = self.extract_from_url(source_url)
            
            if extracted_data:
                # Add the search query as metadata
                extracted_data["target_point"] = target_point
            
            return extracted_data
            
        except requests.exceptions.Timeout:
            st.error("Request timeout - Jina service took too long to respond")
            return None
        except requests.exceptions.RequestException as e:
            st.error(f"Request error: {str(e)}")
            return None
        except json.JSONDecodeError:
            st.error("Failed to parse response from Jina")
            return None
        except Exception as e:
            st.error(f"Unexpected error in search_and_extract: {str(e)}")
            return None
    
    def extract_from_url(self, url: str) -> Optional[Dict]:
        """
        Extract content directly from a given URL
        
        Args:
            url: The URL to extract content from
        
        Returns:
            Dictionary with title, content, and metadata
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json"
            }
            
            # Use Jina's extraction endpoint with the URL
            extraction_url = f"{self.base_url}?url={url}"
            
            response = requests.get(
                extraction_url,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                st.error(f"Extraction failed: {response.text}")
                return None
            
            data = response.json()
            
            # Extract relevant information
            extracted = {
                "title": data.get("title", "Untitled"),
                "content": data.get("content", ""),
                "source_url": url,
                "description": data.get("description", ""),
                "images": data.get("images", []),
                "links": data.get("links", [])
            }
            
            # Validate that we got some content
            if not extracted["content"] or len(extracted["content"].strip()) < 100:
                st.warning("Extracted content is too short. Try a different target point.")
                return None
            
            return extracted
            
        except requests.exceptions.Timeout:
            st.error("Request timeout - Jina service took too long to respond")
            return None
        except requests.exceptions.RequestException as e:
            st.error(f"Request error: {str(e)}")
            return None
        except json.JSONDecodeError:
            st.error("Failed to parse response from Jina")
            return None
        except Exception as e:
            st.error(f"Unexpected error in extract_from_url: {str(e)}")
            return None


# ============================================
# EXPORT FUNCTION
# ============================================
if __name__ == "__main__":
    # Test the service
    service = JinaService()
    result = service.search_and_extract("Python automation Excel")
    if result:
        print(json.dumps(result, indent=2))