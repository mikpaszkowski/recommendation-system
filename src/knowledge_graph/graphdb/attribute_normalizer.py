import re
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator

class AttributeNormalizer(BaseModel):
    """
    Normalizes specific types of attributes using Pydantic validators.
    """
    original_value: str
    normalized_value: Optional[str] = None
    attribute_name: Optional[str] = None

    @model_validator(mode='after')
    def normalize_based_on_name_or_value(self) -> 'AttributeNormalizer':
        val = self.original_value.lower().strip()
        
        # 1. Dimensions (e.g., 14", 14 inch, 14in, 14.5'')
        # Pattern: number + optional space + (", in, inch, inches)
        # Note: avoid replacing " in " inside a sentence. Focus on end of string or before delimiters like 'x'
        if self._is_dimension(val):
             self.normalized_value = self._normalize_dimension(val)
        
        # 2. Memory/Storage (e.g., 16gb, 16 gb, 512mb)
        elif self._is_storage_memory(val):
            self.normalized_value = self._normalize_storage(val)

        # 3. Weight (e.g. 5lbs, 2.5 kg)
        elif self._is_weight(val):
            self.normalized_value = self._normalize_weight(val)

        else:
            # Fallback: just clean whitespace
            self.normalized_value = val
            
        return self

    def _is_dimension(self, val: str) -> bool:
        # Heuristic: check for inch indicators or 'x' patterns (e.g. 3 x 4 x 5)
        # Regex for "digits" followed by "quote" or "in"
        # 14", 14.5'', 14 in, 14inch
        # 10 x 10 x 10 inches
        return bool(re.search(r'\d+\s*(?:"|\'\'|in\b|inch|cm\b|mm\b)', val) or re.search(r'\d+\s*x\s*\d+', val))

    def _normalize_dimension(self, val: str) -> str:
        # Replace " or '' with " inch"
        val = re.sub(r'(\d+)\s*(?:"|\'\')', r'\1 inch', val)
        # Replace "in" or "inches" with "inch"
        val = re.sub(r'\b(in|inches)\b', 'inch', val)
        # Replace cm, mm (just standardizing spacing)
        val = re.sub(r'(\d+)\s*(cm|mm)\b', r'\1 \2', val)
        # Normalize 'x' spacing
        val = re.sub(r'\s*x\s*', ' x ', val)
        return val.strip()

    def _is_storage_memory(self, val: str) -> bool:
        return bool(re.search(r'\d+\s*(gb|mb|tb|kb)\b', val))

    def _normalize_storage(self, val: str) -> str:
        # 16gb -> 16 GB
        def repl(match):
            return f"{match.group(1)} {match.group(2).upper()}"
        return re.sub(r'(\d+)\s*(gb|mb|tb|kb)\b', repl, val).strip()

    def _is_weight(self, val: str) -> bool:
        return bool(re.search(r'\d+\s*(lbs|lb|kg|g|oz)\b', val))

    def _normalize_weight(self, val: str) -> str:
        # Standardize lbs -> lb
        val = re.sub(r'\b(lbs)\b', 'lb', val)
        return val.strip()

    @classmethod
    def normalize(cls, text: str, attr_name: Optional[str] = None) -> str:
        model = cls(original_value=text, attribute_name=attr_name)
        return model.normalized_value

if __name__ == "__main__":
    # Self-test
    examples = [
        "14\"", 
        "15.6''",
        "16gb",
        "512 SSD",
        "10 x 20 x 5 inches",
        "2.5 lbs",
        "16 GB RAM"
    ]
    for ex in examples:
        print(f"'{ex}' -> '{AttributeNormalizer.normalize(ex)}'")
