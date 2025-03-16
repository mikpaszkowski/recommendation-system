# recommendation_api.py
"""
LLM-Compatible Recommendation API - Core implementation

This module serves as the interface between LLM components and recommendation models.
It provides a structured way to translate natural language queries into recommendation
parameters and format results for LLM consumption.
"""

import json
import numpy as np
from typing import Dict, List, Tuple, Optional, Union
import pandas as pd
from lightfm import LightFM
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class RecommendationAPI:
    """API interface for LLM-compatible recommendations."""
    
    def __init__(
        self,
        product_data_path: str,
        user_data_path: str,
        interactions_data_path: str,
        lightfm_model_path: Optional[str] = None,
        tfidf_model_path: Optional[str] = None
    ):
        """
        Initialize the recommendation API.
        
        Args:
            product_data_path: Path to product catalog data
            user_data_path: Path to user profiles data
            interactions_data_path: Path to user-item interactions data
            lightfm_model_path: Path to pre-trained LightFM model
            tfidf_model_path: Path to pre-trained TF-IDF vectorizer
        """
        # Load data
        self.products_df = pd.read_csv(product_data_path)
        self.users_df = pd.read_csv(user_data_path)
        self.interactions_df = pd.read_csv(interactions_data_path)
        
        # Initialize recommendation models
        self._init_content_based_model(tfidf_model_path)
        self._init_collaborative_model(lightfm_model_path)
        
        # Initialize explanation templates
        self._init_explanation_templates()
    
    def _init_content_based_model(self, model_path: Optional[str] = None):
        """Initialize the content-based filtering model with TF-IDF."""
        if model_path and os.path.exists(model_path):
            # Load pre-trained TF-IDF model
            import pickle
            with open(model_path, 'rb') as f:
                self.tfidf_vectorizer = pickle.load(f)
            self.product_tfidf_matrix = self.tfidf_vectorizer.transform(self.products_df['description'])
        else:
            # Train new TF-IDF model
            self.tfidf_vectorizer = TfidfVectorizer(
                max_features=5000,
                stop_words='english'
            )
            self.product_tfidf_matrix = self.tfidf_vectorizer.fit_transform(self.products_df['description'])
    
    def _init_collaborative_model(self, model_path: Optional[str] = None):
        """Initialize the collaborative filtering model with LightFM."""
        if model_path and os.path.exists(model_path):
            # Load pre-trained LightFM model
            import pickle
            with open(model_path, 'rb') as f:
                self.lightfm_model = pickle.load(f)
        else:
            # Initialize new LightFM model (to be trained later)
            self.lightfm_model = LightFM(
                no_components=64,
                learning_schedule='adagrad',
                loss='warp'
            )
            # Note: You would need to prepare user/item ID mappings and train this model
            # This initialization is just a placeholder
    
    def _init_explanation_templates(self):
        """Initialize explanation templates for recommendations."""
        self.explanation_templates = {
            "content_based": {
                "primary": "This product has similar features to {similar_product} which you've shown interest in.",
                "category": "It belongs to the {category} category which matches your preferences.",
                "features": "It has {key_features} which align with what you're looking for."
            },
            "collaborative": {
                "primary": "Users with similar preferences to yours have enjoyed this product.",
                "popularity": "It's among the most popular choices in {category}.",
                "rating": "It has received positive reviews with an average rating of {rating}."
            },
            "hybrid": {
                "primary": "This matches both your specific preferences and what similar users have enjoyed.",
                "features": "It features {key_features} which you've liked in the past.",
                "social": "It's well-received by users with tastes similar to yours."
            }
        }
    
    def process_llm_query(self, query: Dict) -> Dict:
        """
        Process a structured query from an LLM component.
        
        Args:
            query: A structured query dictionary with the following possible keys:
                - user_id: Optional user ID for personalized recommendations
                - query_type: Type of recommendation query (e.g., 'similar_items', 'user_recommendations')
                - item_id: Optional item ID for item-based recommendations
                - category: Optional category filter
                - keywords: Optional keywords to consider
                - preferences: Dictionary of specific preferences
                - explanation_required: Whether to generate explanations
                - num_recommendations: Number of recommendations to return
        
        Returns:
            Dictionary with recommendation results and optional explanations
        """
        if query.get('query_type') == 'similar_items' and query.get('item_id'):
            return self._get_similar_items(
                item_id=query['item_id'],
                n=query.get('num_recommendations', 5),
                explain=query.get('explanation_required', False)
            )
        
        elif query.get('query_type') == 'category_recommendations' and query.get('category'):
            return self._get_category_recommendations(
                category=query['category'],
                user_id=query.get('user_id'),
                keywords=query.get('keywords', []),
                n=query.get('num_recommendations', 5),
                explain=query.get('explanation_required', False)
            )
        
        elif query.get('query_type') == 'user_recommendations' and query.get('user_id'):
            return self._get_user_recommendations(
                user_id=query['user_id'],
                n=query.get('num_recommendations', 5),
                explain=query.get('explanation_required', False)
            )
        
        elif query.get('query_type') == 'preference_based':
            return self._get_preference_based_recommendations(
                preferences=query.get('preferences', {}),
                user_id=query.get('user_id'),
                n=query.get('num_recommendations', 5),
                explain=query.get('explanation_required', False)
            )
        
        else:
            return {
                'status': 'error',
                'message': 'Invalid query type or missing required parameters',
                'recommendations': []
            }
    
    def _get_similar_items(self, item_id: str, n: int = 5, explain: bool = False) -> Dict:
        """Get items similar to a specific item."""
        try:
            # Get item index
            item_idx = self.products_df[self.products_df['product_id'] == item_id].index[0]
            
            # Calculate similarity
            item_vector = self.product_tfidf_matrix[item_idx]
            similarities = cosine_similarity(item_vector, self.product_tfidf_matrix).flatten()
            
            # Get top N similar items (excluding the query item)
            similar_indices = similarities.argsort()[::-1][1:n+1]
            similar_products = self.products_df.iloc[similar_indices]
            
            # Format recommendations
            recommendations = self._format_recommendations(similar_products, similarities[similar_indices], 'content_based', explain)
            
            return {
                'status': 'success',
                'recommendations': recommendations
            }
        
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error finding similar items: {str(e)}',
                'recommendations': []
            }
    
    def _get_category_recommendations(
        self, 
        category: str, 
        user_id: Optional[str] = None,
        keywords: List[str] = [],
        n: int = 5, 
        explain: bool = False
    ) -> Dict:
        """Get recommendations within a specific category."""
        try:
            # Filter products by category
            category_products = self.products_df[self.products_df['category'] == category]
            
            if len(category_products) == 0:
                return {
                    'status': 'error',
                    'message': f'No products found in category {category}',
                    'recommendations': []
                }
            
            if keywords:
                # If keywords provided, use content-based filtering
                keyword_text = ' '.join(keywords)
                keyword_vector = self.tfidf_vectorizer.transform([keyword_text])
                
                # Get category products TF-IDF matrix
                category_indices = category_products.index
                category_tfidf = self.product_tfidf_matrix[category_indices]
                
                # Calculate similarity
                similarities = cosine_similarity(keyword_vector, category_tfidf).flatten()
                
                # Get top N similar items
                top_indices = similarities.argsort()[::-1][:n]
                recommended_products = category_products.iloc[top_indices]
                
                recommendations = self._format_recommendations(
                    recommended_products, 
                    similarities[top_indices], 
                    'content_based', 
                    explain
                )
            
            elif user_id:
                # If user_id provided, use collaborative filtering
                # This is a simplified implementation
                # In a real system, you would use your LightFM model predictions
                
                # Placeholder for demo purposes - would actually use the model
                user_interactions = self.interactions_df[self.interactions_df['user_id'] == user_id]
                top_categories = user_interactions['category'].value_counts().index[:3]
                
                if category in top_categories:
                    # User has shown interest in this category
                    # Sort by rating and popularity (simplified)
                    recommended_products = category_products.sort_values('rating', ascending=False).head(n)
                    
                    # Placeholder scores
                    scores = np.linspace(0.9, 0.7, len(recommended_products))
                    
                    recommendations = self._format_recommendations(
                        recommended_products,
                        scores,
                        'collaborative',
                        explain
                    )
                else:
                    # New category for user
                    # Recommend popular items
                    recommended_products = category_products.sort_values(['rating', 'popularity'], ascending=False).head(n)
                    
                    # Placeholder scores
                    scores = np.linspace(0.8, 0.6, len(recommended_products))
                    
                    recommendations = self._format_recommendations(
                        recommended_products,
                        scores,
                        'collaborative',
                        explain
                    )
            
            else:
                # No user or keywords - recommend popular items in category
                recommended_products = category_products.sort_values(
                    ['rating', 'popularity'], 
                    ascending=False
                ).head(n)
                
                # Placeholder scores based on popularity
                scores = np.linspace(0.8, 0.6, len(recommended_products))
                
                recommendations = self._format_recommendations(
                    recommended_products,
                    scores,
                    'collaborative',
                    explain
                )
            
            return {
                'status': 'success',
                'recommendations': recommendations
            }
        
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error getting category recommendations: {str(e)}',
                'recommendations': []
            }
    
    def _get_user_recommendations(self, user_id: str, n: int = 5, explain: bool = False) -> Dict:
        """Get personalized recommendations for a user."""
        try:
            # This is a simplified implementation
            # In a real system, you would use your LightFM model predictions
            
            # Get user's past interactions
            user_interactions = self.interactions_df[self.interactions_df['user_id'] == user_id]
            
            if len(user_interactions) == 0:
                # Cold start - no interactions
                # Return popular items
                recommended_products = self.products_df.sort_values(
                    ['rating', 'popularity'], 
                    ascending=False
                ).head(n)
                
                scores = np.linspace(0.7, 0.5, len(recommended_products))
                
                recommendations = self._format_recommendations(
                    recommended_products,
                    scores,
                    'collaborative',
                    explain
                )
            
            else:
                # Get user's preferred categories
                preferred_categories = user_interactions['category'].value_counts().index[:2]
                
                # Filter products by preferred categories
                filtered_products = self.products_df[
                    self.products_df['category'].isin(preferred_categories)
                ]
                
                # Exclude already interacted items
                interacted_items = user_interactions['product_id'].unique()
                recommended_products = filtered_products[
                    ~filtered_products['product_id'].isin(interacted_items)
                ]
                
                # Sort by rating and popularity
                recommended_products = recommended_products.sort_values(
                    ['rating', 'popularity'], 
                    ascending=False
                ).head(n)
                
                scores = np.linspace(0.9, 0.7, len(recommended_products))
                
                recommendations = self._format_recommendations(
                    recommended_products,
                    scores,
                    'hybrid',
                    explain
                )
            
            return {
                'status': 'success',
                'recommendations': recommendations
            }
        
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error getting user recommendations: {str(e)}',
                'recommendations': []
            }
    
    def _get_preference_based_recommendations(
        self,
        preferences: Dict,
        user_id: Optional[str] = None,
        n: int = 5,
        explain: bool = False
    ) -> Dict:
        """Get recommendations based on explicit preferences."""
        try:
            # Start with all products
            filtered_products = self.products_df.copy()
            
            # Apply filters based on preferences
            for pref_key, pref_value in preferences.items():
                if pref_key == 'category':
                    filtered_products = filtered_products[filtered_products['category'] == pref_value]
                elif pref_key == 'min_rating':
                    filtered_products = filtered_products[filtered_products['rating'] >= float(pref_value)]
                elif pref_key == 'price_range':
                    if isinstance(pref_value, list) and len(pref_value) == 2:
                        min_price, max_price = pref_value
                        filtered_products = filtered_products[
                            (filtered_products['price'] >= min_price) & 
                            (filtered_products['price'] <= max_price)
                        ]
                elif pref_key == 'features':
                    if isinstance(pref_value, list):
                        # This is simplified - in a real system you'd use better text matching
                        for feature in pref_value:
                            filtered_products = filtered_products[
                                filtered_products['description'].str.contains(feature, case=False)
                            ]
            
            if len(filtered_products) == 0:
                return {
                    'status': 'warning',
                    'message': 'No products match all preferences. Consider relaxing some constraints.',
                    'recommendations': []
                }
            
            # Sort by rating and relevance
            if user_id and user_id in self.users_df['user_id'].values:
                # Personalize with user history if available
                # This is a placeholder - you would use model predictions
                recommended_products = filtered_products.sort_values(
                    ['rating', 'popularity'],
                    ascending=False
                ).head(n)
                
                scores = np.linspace(0.95, 0.8, len(recommended_products))
                recommendations = self._format_recommendations(
                    recommended_products, 
                    scores, 
                    'hybrid', 
                    explain
                )
            else:
                # Non-personalized but preference-based
                recommended_products = filtered_products.sort_values(
                    ['rating', 'popularity'],
                    ascending=False
                ).head(n)
                
                scores = np.linspace(0.85, 0.7, len(recommended_products))
                recommendations = self._format_recommendations(
                    recommended_products, 
                    scores, 
                    'content_based', 
                    explain
                )
            
            return {
                'status': 'success',
                'recommendations': recommendations,
                'applied_preferences': list(preferences.keys())
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error getting preference-based recommendations: {str(e)}',
                'recommendations': []
            }
    
    def _format_recommendations(
        self, 
        products_df: pd.DataFrame, 
        scores: np.ndarray, 
        rec_type: str, 
        include_explanation: bool
    ) -> List[Dict]:
        """Format recommendations in a structured format for LLM consumption."""
        recommendations = []
        
        for i, (_, product) in enumerate(products_df.iterrows()):
            rec = {
                'product_id': product['product_id'],
                'title': product['title'],
                'category': product['category'],
                'rating': float(product['rating']),
                'price': float(product['price']),
                'confidence_score': float(scores[i])
            }
            
            if include_explanation:
                explanation = self._generate_explanation(product, rec_type)
                rec['explanation'] = explanation
            
            recommendations.append(rec)
        
        return recommendations
    
    def _generate_explanation(self, product, rec_type: str) -> str:
        """Generate explanation for a recommendation."""
        templates = self.explanation_templates[rec_type]
        
        # Extract key features (simplified)
        key_features = product['description'].split()[:3]  # Just get first few words
        
        explanation_parts = []
        
        # Add primary explanation
        if rec_type == 'content_based':
            explanation_parts.append(
                templates['primary'].format(similar_product=product['title'])
            )
        else:
            explanation_parts.append(templates['primary'])
        
        # Add category explanation
        if 'category' in templates:
            explanation_parts.append(
                templates['category'].format(category=product['category'])
            )
        
        # Add features explanation
        if 'features' in templates:
            explanation_parts.append(
                templates['features'].format(key_features=', '.join(key_features))
            )
        
        # Add rating explanation for collaborative
        if rec_type == 'collaborative' and 'rating' in templates:
            explanation_parts.append(
                templates['rating'].format(rating=product['rating'])
            )
        
        return ' '.join(explanation_parts)


class LLMPreferenceParser:
    """
    Parser for converting natural language preferences to structured format.
    This is a simplified implementation - in a real system, you would use
    an LLM to extract preferences from natural language.
    """
    
    def __init__(self):
        """Initialize the parser with basic patterns."""
        # Category patterns (simplified)
        self.category_patterns = {
            'electronics': ['electronics', 'tech', 'gadgets', 'devices'],
            'books': ['books', 'reading', 'novel', 'textbook'],
            'clothing': ['clothing', 'clothes', 'fashion', 'apparel', 'wear'],
            'home': ['home', 'kitchen', 'furniture', 'decor'],
            'beauty': ['beauty', 'cosmetics', 'makeup', 'skincare']
        }
        
        # Price patterns
        self.price_indicators = [
            'cheap', 'affordable', 'inexpensive', 'budget',
            'expensive', 'luxury', 'high-end', 'premium'
        ]
    
    def parse_natural_language_query(self, query_text: str) -> Dict:
        """
        Parse natural language query into structured format.
        This is a placeholder - in your actual implementation,
        you would use an LLM to perform this parsing.
        
        Args:
            query_text: Natural language query from user
            
        Returns:
            Structured query dictionary
        """
        # This is a very simplified parsing logic
        structured_query = {
            'query_type': None,
            'user_id': None,
            'item_id': None,
            'category': None,
            'keywords': [],
            'preferences': {},
            'num_recommendations': 5,
            'explanation_required': False
        }
        
        # Lower case for easier matching
        query_text = query_text.lower()
        
        # Check for query type indicators
        if any(x in query_text for x in ['similar', 'like this', 'like that']):
            structured_query['query_type'] = 'similar_items'
        elif any(x in query_text for x in ['category', 'department']):
            structured_query['query_type'] = 'category_recommendations'
        elif any(x in query_text for x in ['recommend', 'suggest', 'for me']):
            structured_query['query_type'] = 'user_recommendations'
        else:
            structured_query['query_type'] = 'preference_based'
        
        # Extract specific preferences
        # Category detection
        for category, patterns in self.category_patterns.items():
            if any(pattern in query_text for pattern in patterns):
                structured_query['category'] = category
                break
        
        # Price preferences (simplified)
        if any(indicator in query_text for indicator in ['cheap', 'affordable', 'inexpensive', 'budget']):
            structured_query['preferences']['price_range'] = [0, 50]
        elif any(indicator in query_text for indicator in ['expensive', 'luxury', 'high-end', 'premium']):
            structured_query['preferences']['price_range'] = [100, 1000]
        
        # Rating preferences
        if 'highly rated' in query_text or 'top rated' in query_text or 'best' in query_text:
            structured_query['preferences']['min_rating'] = 4.0
        
        # Extract potential keywords
        # This is very simplified - in a real system you'd use NLP techniques
        important_words = []
        for word in query_text.split():
            if len(word) > 3 and word not in [
                'what', 'where', 'when', 'recommend', 'looking', 'something', 'please',
                'would', 'could', 'should', 'about', 'like', 'want', 'need', 'prefer'
            ]:
                important_words.append(word)
        
        structured_query['keywords'] = important_words[:5]  # Limit to top 5 words
        
        # Explanation detection
        if any(x in query_text for x in ['explain', 'explanation', 'why', 'reason']):
            structured_query['explanation_required'] = True
        
        # Set number of recommendations
        if 'one' in query_text:
            structured_query['num_recommendations'] = 1
        elif any(str(i) in query_text.split() for i in range(1, 11)):
            for i in range(1, 11):
                if str(i) in query_text.split():
                    structured_query['num_recommendations'] = i
                    break
        
        return structured_query


class LLMIntegrationLayer:
    """
    Integration layer that connects LLMs with the recommendation API.
    This handles the translation between natural language and structured queries.
    """
    
    def __init__(self, recommendation_api):
        """
        Initialize the LLM integration layer.
        
        Args:
            recommendation_api: Instance of RecommendationAPI
        """
        self.recommendation_api = recommendation_api
        self.preference_parser = LLMPreferenceParser()
    
    def process_llm_message(self, user_message: str, user_id: Optional[str] = None) -> Dict:
        """
        Process a natural language message from an LLM and return recommendation results.
        
        Args:
            user_message: Natural language message from the user
            user_id: Optional user ID for personalized recommendations
            
        Returns:
            Dictionary with processed results ready for LLM consumption
        """
        # Parse natural language to structured query
        structured_query = self.preference_parser.parse_natural_language_query(user_message)
        
        # Add user ID if provided
        if user_id:
            structured_query['user_id'] = user_id
        
        # Process the structured query
        api_response = self.recommendation_api.process_llm_query(structured_query)
        
        # Format response for LLM consumption
        llm_response = self._format_for_llm(api_response, structured_query)
        
        return llm_response
    
    def _format_for_llm(self, api_response: Dict, query: Dict) -> Dict:
        """
        Format API response for LLM consumption.
        
        Args:
            api_response: Response from recommendation API
            query: Original structured query
            
        Returns:
            Formatted response for LLM
        """
        if api_response['status'] == 'error':
            return {
                'response_type': 'error',
                'message': api_response['message'],
                'llm_prompt': f"I encountered an error while searching for recommendations: {api_response['message']}. Could you provide more specific information about what you're looking for?"
            }
        
        if api_response['status'] == 'warning':
            return {
                'response_type': 'warning',
                'message': api_response['message'],
                'llm_prompt': f"I found a potential issue: {api_response['message']}. Would you like to adjust your preferences to find more options?"
            }
        
        recommendations = api_response['recommendations']
        
        if not recommendations:
            return {
                'response_type': 'no_results',
                'llm_prompt': "I couldn't find any recommendations matching your criteria. Could you try with different preferences or a broader search?"
            }
        
        # Create formatted response with both structured data and natural language templates
        response = {
            'response_type': 'success',
            'recommendations': recommendations,
            'recommendation_count': len(recommendations),
            'query_type': query['query_type'],
            'applied_preferences': query.get('preferences', {}),
            'category': query.get('category'),
            'keywords': query.get('keywords', []),
        }
        
        # Add templates for natural language generation
        response['llm_templates'] = self._generate_llm_templates(recommendations, query)
        
        return response
    
    def _generate_llm_templates(self, recommendations: List[Dict], query: Dict) -> Dict:
        """
        Generate natural language templates for LLM to use.
        
        Args:
            recommendations: List of recommendation objects
            query: Original structured query
            
        Returns:
            Dictionary of templates
        """
        templates = {}
        
        # Introduction template based on query type
        if query['query_type'] == 'similar_items':
            templates['introduction'] = "Here are some items similar to what you're looking for:"
        elif query['query_type'] == 'category_recommendations':
            templates['introduction'] = f"I found these recommendations in the {query['category']} category:"
        elif query['query_type'] == 'user_recommendations':
            templates['introduction'] = "Based on your preferences, you might like these items:"
        else:
            templates['introduction'] = "Based on what you're looking for, here are some recommendations:"
        
        # Item description templates
        templates['item_descriptions'] = []
        for item in recommendations:
            if 'explanation' in item:
                desc = f"{item['title']} - ${item['price']:.2f}. {item['explanation']}"
            else:
                desc = f"{item['title']} - ${item['price']:.2f}, rated {item['rating']:.1f}/5.0"
            templates['item_descriptions'].append(desc)
        
        # Follow-up question templates
        templates['follow_up_questions'] = [
            "Would you like more details about any of these items?",
            "Would you like to refine these recommendations further?",
            "Do you have any specific preferences I should consider?",
            "Are these recommendations what you were looking for?"
        ]
        
        return templates


# chain_of_thought_prompt.py
"""
Chain-of-Thought prompt templates for recommendation reasoning.
These templates guide the LLM through a structured reasoning process.
"""

class ChainOfThoughtPrompts:
    """Collection of prompt templates for recommendation reasoning."""
    
    @staticmethod
    def get_reasoning_template():
        """Get the basic reasoning template for recommendations."""
        return """
        To provide the best recommendations, I'll follow these steps:
        
        Step 1: Analyze the user's request
        - Identify explicit preferences mentioned in the request
        - Extract any constraints or requirements
        
        Step 2: Consider the user's profile and history
        - Take into account the user's past interactions
        - Consider their known preferences and tastes
        
        Step 3: Evaluate candidate recommendations
        - Match candidates against the user's preferences
        - Consider product attributes, ratings, and popularity
        - Check if candidates satisfy all constraints
        
        Step 4: Rank recommendations
        - Prioritize items that best match user preferences
        - Consider both explicit and implicit preferences
        - Ensure diversity in recommendations
        
        Step 5: Generate explanations
        - Provide clear reasons for each recommendation
        - Connect recommendations to user preferences
        - Offer additional context when relevant
        """
    
    @staticmethod
    def get_item_evaluation_template():
        """Get template for evaluating individual items."""
        return """
        Item Evaluation for {product_title}:
        
        1. Preference matching:
        {preference_matching_analysis}
        
        2. User history relevance:
        {user_history_relevance}
        
        3. Item attributes:
        - Category: {category}
        - Rating: {rating}/5.0
        - Price: ${price}
        - Key features: {key_features}
        
        4. Constraints check:
        {constraints_check}
        
        5. Overall assessment:
        {overall_assessment}
        
        Final score: {score}/10
        """
    
    @staticmethod
    def get_recommendation_summary_template():
        """Get template for summarizing recommendations."""
        return """
        Recommendation Summary:
        
        User request: "{user_request}"
        
        Identified preferences:
        {identified_preferences}
        
        Top recommendations:
        {top_recommendations}
        
        Reasoning for selection:
        {selection_reasoning}
        
        Additional considerations:
        {additional_considerations}
        """


# llm_prompt_constructor.py
"""
Prompt constructor for LLM integration with the recommendation system.
Builds prompts that connect the recommendation API with LLM responses.
"""

class LLMPromptConstructor:
    """Constructs prompts for LLM integration with recommendations."""
    
    @staticmethod
    def build_response_prompt(llm_response_data):
        """
        Build a prompt to guide the LLM in generating a response to user requests.
        
        Args:
            llm_response_data: Formatted data from LLMIntegrationLayer
            
        Returns:
            Prompt string for the LLM
        """
        if llm_response_data['response_type'] in ['error', 'warning', 'no_results']:
            # Just return the pre-formatted prompt for errors and warnings
            return llm_response_data.get('llm_prompt', 'I couldn\'t find appropriate recommendations.')
        
        # For successful responses, build a more complex prompt
        templates = llm_response_data['llm_templates']
        recommendations = llm_response_data['recommendations']
        
        prompt = f"""
        The user asked for recommendations. Based on their request, I have found {len(recommendations)} 
        recommendations that match their criteria.
        
        I should respond with:
        
        1. An introduction: "{templates['introduction']}"
        
        2. A list of recommended items with descriptions:
        """
        
        # Add item descriptions
        for i, desc in enumerate(templates['item_descriptions'], 1):
            prompt += f"\n   {i}. {desc}"
        
        # Add follow-up
        prompt += f"\n\n3. A follow-up question such as: \"{templates['follow_up_questions'][0]}\""
        
        # Add instructions for the LLM
        prompt += """
        
        I should make my response conversational and natural, not just copying this format exactly.
        I should maintain a helpful, friendly tone and emphasize the aspects of the recommendations 
        that best match the user's preferences.
        """
        
        return prompt
    
    @staticmethod
    def build_reasoning_prompt(user_message, user_profile=None, conversation_history=None):
        """
        Build a prompt for chain-of-thought reasoning.
        
        Args:
            user_message: Current user message
            user_profile: Optional user profile information
            conversation_history: Optional conversation history
            
        Returns:
            Prompt string for reasoning about recommendations
        """
        prompt = """
        I need to provide personalized product recommendations based on the user's request.
        I'll think through this step-by-step to ensure I provide relevant recommendations.
        """
        
        # Add reasoning template
        prompt += "\n" + ChainOfThoughtPrompts.get_reasoning_template()
        
        # Add user message
        prompt += f"\n\nUser request: \"{user_message}\"\n"
        
        # Add user profile if available
        if user_profile:
            prompt += "\nUser profile information:\n"
            for key, value in user_profile.items():
                prompt += f"- {key}: {value}\n"
        
        # Add conversation history if available
        if conversation_history:
            prompt += "\nRelevant conversation history:\n"
            for turn in conversation_history[-3:]:  # Only include last 3 turns
                prompt += f"- {turn['role']}: {turn['content']}\n"
        
        # Add final instruction
        prompt += """
        Now, I'll analyze this information and determine the best recommendations:
        
        Step 1: Analyze the user's request
        """
        
        return prompt


# recommendation_demo.py
"""
Demo script showing how to use the Recommendation API with LLM integration.
"""

def run_demo():
    """Run a demonstration of the recommendation system."""
    import os
    
    # Check if data files exist (placeholder paths)
    product_data_path = "data/products.csv"
    user_data_path = "data/users.csv"
    interactions_data_path = "data/interactions.csv"
    
    if not all(os.path.exists(path) for path in [product_data_path, user_data_path, interactions_data_path]):
        print("Error: Required data files not found.")
        print("This is a demo script. In a real implementation, you would need to:")
        print("1. Prepare your product catalog, user data, and interaction data")
        print("2. Train your recommendation models")
        print("3. Set up the integration with your LLM system")
        return
    
    # Initialize the recommendation API
    recommendation_api = RecommendationAPI(
        product_data_path=product_data_path,
        user_data_path=user_data_path,
        interactions_data_path=interactions_data_path
    )
    
    # Initialize the LLM integration layer
    llm_integration = LLMIntegrationLayer(recommendation_api)
    
    # Example user message
    user_message = "Can you recommend some affordable electronics products for me?"
    user_id = "user123"  # Example user ID
    
    print(f"User message: {user_message}")
    print(f"User ID: {user_id}")
    print("-" * 50)
    
    # Process the message
    llm_response = llm_integration.process_llm_message(
        user_message=user_message,
        user_id=user_id
    )
    
    # Build LLM prompt
    prompt = LLMPromptConstructor.build_response_prompt(llm_response)
    
    print("Generated LLM Prompt:")
    print("-" * 50)
    print(prompt)
    print("-" * 50)
    
    # In a real implementation, you would send this prompt to your LLM
    print("In a real implementation, this prompt would be sent to your LLM")
    print("The LLM would generate a natural language response based on the prompt")
    print("This response would be returned to the user")


if __name__ == "__main__":
    run_demo()