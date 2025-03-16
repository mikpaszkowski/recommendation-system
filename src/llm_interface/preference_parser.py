from typing import Dict, Any, List, Optional
import re
import json

class PreferenceParser:
    """
    Extracts structured preferences from natural language user inputs.
    """
    
    def __init__(self, domain_specific_patterns: Optional[Dict[str, List[str]]] = None):
        """
        Initialize the preference parser.
        
        Args:
            domain_specific_patterns: Optional dictionary mapping preference types to regex patterns
        """
        self.domain_patterns = domain_specific_patterns or {}
        
        # Default patterns for common preference types
        self.default_patterns = {
            "category": [
                r"(?:looking for|interested in|want|like|prefer)(?:\s+\w+){0,3}\s+([\w\s&'-]+)(?:\s+products?|items?|things?)?",
                r"(?:category|department|section)(?:\s+\w+){0,3}\s+([\w\s&'-]+)"
            ],
            "brand": [
                r"(?:brand|make|manufacturer)(?:\s+\w+){0,3}\s+([\w\s&'-]+)",
                r"(?:from|by|made by)(?:\s+\w+){0,3}\s+([\w\s&'-]+)"
            ],
            "price_range": [
                r"(?:under|less than|below|not more than|maximum|max)(?:\s+\w+){0,3}\s+\$?(\d+(?:\.\d{2})?)",
                r"(?:between|from)(?:\s+\w+){0,3}\s+\$?(\d+(?:\.\d{2})?)(?:\s+\w+){0,3}\s+\$?(\d+(?:\.\d{2})?)",
                r"(?:over|more than|above|at least|minimum|min)(?:\s+\w+){0,3}\s+\$?(\d+(?:\.\d{2})?)"
            ],
            "rating": [
                r"(?:rating|rated|stars|score)(?:\s+\w+){0,3}\s+(\d+(?:\.\d+)?)",
                r"(?:at least|minimum|min)(?:\s+\w+){0,3}\s+(\d+(?:\.\d+)?)(?:\s+\w+){0,3}\s+(?:stars|rating)"
            ],
            "features": [
                r"(?:with|has|having|include|includes|containing)(?:\s+\w+){0,3}\s+([\w\s&'-]+)",
                r"(?:feature|features|functionality|capabilities)(?:\s+\w+){0,3}\s+([\w\s&'-]+)"
            ]
        }
        
    def extract_preferences(self, text: str) -> Dict[str, Any]:
        """
        Extract structured preferences from natural language text.
        
        Args:
            text: Natural language text from user
            
        Returns:
            Dictionary of extracted preferences
        """
        preferences = {}
        
        # Combine default and domain-specific patterns
        all_patterns = {**self.default_patterns, **self.domain_patterns}
        
        # Extract preferences using patterns
        for pref_type, patterns in all_patterns.items():
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    if pref_type == "price_range" and isinstance(matches[0], tuple) and len(matches[0]) > 1:
                        # Handle price range with min and max
                        min_price, max_price = matches[0]
                        preferences[pref_type] = {
                            "min": float(min_price),
                            "max": float(max_price)
                        }
                    elif pref_type == "price_range" and ("under" in text or "less than" in text or "below" in text):
                        # Handle max price
                        preferences[pref_type] = {
                            "max": float(matches[0])
                        }
                    elif pref_type == "price_range" and ("over" in text or "more than" in text or "above" in text):
                        # Handle min price
                        preferences[pref_type] = {
                            "min": float(matches[0])
                        }
                    else:
                        # Handle other preference types
                        preferences[pref_type] = matches[0]
                    break
        
        return preferences
    
    def format_for_recommender(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format extracted preferences for the recommendation engine.
        
        Args:
            preferences: Dictionary of extracted preferences
            
        Returns:
            Formatted preferences for the recommendation engine
        """
        formatted = {}
        
        # Format each preference type
        for pref_type, value in preferences.items():
            if pref_type == "category":
                formatted["category"] = value
            elif pref_type == "brand":
                formatted["brand"] = value
            elif pref_type == "price_range":
                if isinstance(value, dict):
                    if "min" in value:
                        formatted["min_price"] = value["min"]
                    if "max" in value:
                        formatted["max_price"] = value["max"]
                else:
                    formatted["max_price"] = float(value)
            elif pref_type == "rating":
                formatted["min_rating"] = float(value)
            elif pref_type == "features":
                formatted["features"] = value
            else:
                # Pass through other preference types
                formatted[pref_type] = value
                
        return formatted 