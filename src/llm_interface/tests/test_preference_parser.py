import sys
import os
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from src.llm_interface.preference_parser import PreferenceParser


class TestPreferenceParser(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.parser = PreferenceParser()

    def test_extract_category_preferences(self):
        """Test extracting category preferences."""
        test_cases = [
            ("I'm looking for laptops", {"category": "laptops"}),
            ("interested in gaming accessories", {"category": "gaming accessories"}),
            ("show me items from the electronics category", {"category": "electronics"}),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = self.parser.extract_preferences(input_text)
                self.assertEqual(result.get("category"), expected.get("category"))

    def test_extract_price_range(self):
        """Test extracting price range preferences."""
        test_cases = [
            ("under $500", {"price_range": {"max": 500.0}}),
            ("between $100 and $200", {"price_range": {"min": 100.0, "max": 200.0}}),
            ("more than $1000", {"price_range": {"min": 1000.0}}),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = self.parser.extract_preferences(input_text)
                self.assertEqual(result.get("price_range"), expected.get("price_range"))

    def test_extract_rating_preferences(self):
        """Test extracting rating preferences."""
        test_cases = [
            ("at least 4 stars", {"rating": "4"}),
            ("minimum rating of 3.5", {"rating": "3.5"}),
            ("rated above 4.5 stars", {"rating": "4.5"}),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = self.parser.extract_preferences(input_text)
                self.assertEqual(result.get("rating"), expected.get("rating"))

    def test_extract_brand_preferences(self):
        """Test extracting brand preferences."""
        test_cases = [
            ("made by Apple", {"brand": "Apple"}),
            ("looking for Samsung products", {"brand": "Samsung"}),
            ("from Microsoft", {"brand": "Microsoft"}),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = self.parser.extract_preferences(input_text)
                self.assertEqual(result.get("brand"), expected.get("brand"))

    def test_extract_feature_preferences(self):
        """Test extracting feature preferences."""
        test_cases = [
            ("with long battery life", {"features": "long battery life"}),
            ("includes touchscreen", {"features": "touchscreen"}),
            ("having wireless charging", {"features": "wireless charging"}),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = self.parser.extract_preferences(input_text)
                self.assertEqual(result.get("features"), expected.get("features"))

    def test_format_for_recommender(self):
        """Test formatting preferences for the recommender."""
        preferences = {
            "category": "laptops",
            "price_range": {"min": 500.0, "max": 1000.0},
            "rating": "4.5",
            "features": "backlit keyboard"
        }
        
        expected = {
            "category": "laptops",
            "min_price": 500.0,
            "max_price": 1000.0,
            "min_rating": 4.5,
            "features": "backlit keyboard"
        }
        
        result = self.parser.format_for_recommender(preferences)
        self.assertEqual(result, expected)

    def test_multiple_preferences(self):
        """Test extracting multiple preferences from a single input."""
        input_text = "looking for laptops under $1000 with at least 4 stars made by Dell"
        expected = {
            "category": "laptops",
            "price_range": {"max": 1000.0},
            "rating": "4",
            "brand": "Dell"
        }
        
        result = self.parser.extract_preferences(input_text)
        self.assertEqual(result, expected)

    def test_custom_domain_patterns(self):
        """Test parser with custom domain-specific patterns."""
        custom_patterns = {
            "warranty": [
                r"(?:warranty|guarantee)(?:\s+\w+){0,3}\s+(\d+)(?:\s+\w+){0,3}\s+(?:year|yr)"
            ]
        }
        
        parser = PreferenceParser(domain_specific_patterns=custom_patterns)
        input_text = "laptops with 3 year warranty"
        result = parser.extract_preferences(input_text)
        self.assertEqual(result.get("warranty"), "3")

    def test_invalid_inputs(self):
        """Test handling of invalid or empty inputs."""
        test_cases = [
            "",  # Empty string
            "   ",  # Whitespace only
            "show me everything",  # No specific preferences
            "xyz123",  # Random text
        ]
        
        for input_text in test_cases:
            with self.subTest(input_text=input_text):
                result = self.parser.extract_preferences(input_text)
                self.assertEqual(result, {})

if __name__ == '__main__':
    unittest.main() 