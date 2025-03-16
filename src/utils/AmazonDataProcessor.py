import json
import os
import logging
import time
from typing import Dict, List, Optional, Set, Tuple, Any
from collections import defaultdict, Counter
import pandas as pd
import numpy as np
from tqdm import tqdm
from pathlib import Path
# Get project root and data directory paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = PROJECT_ROOT / "datasets"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AmazonDataProcessor:
    """
    Processes Amazon review and metadata files for use in recommendation systems.
    Uses DataFrames for efficient data manipulation and filters based on user and product
    review counts.
    """
    
    def __init__(
        self,
        max_reviews_per_item: int = 20,
        min_reviews_per_item: int = 5,  # Changed to 5 per requirements
        min_reviews_per_user: int = 2,  # Added per requirements
        include_low_ratings: bool = True,
        metadata_weight: float = 1.5,
        reviews_weight: float = 1.0
    ):
        """
        Initialize the Amazon data processor.
        
        Args:
            max_reviews_per_item: Maximum number of reviews to process per item
            min_reviews_per_item: Minimum number of reviews required to include an item (default: 5)
            min_reviews_per_user: Minimum number of reviews a user must have to include their reviews (default: 2)
            include_low_ratings: Whether to include reviews with low ratings
            metadata_weight: Weight for metadata text (higher means more importance)
            reviews_weight: Weight for reviews text
        """
        self.max_reviews_per_item = max_reviews_per_item
        self.min_reviews_per_item = min_reviews_per_item
        self.min_reviews_per_user = min_reviews_per_user
        self.include_low_ratings = include_low_ratings
        self.metadata_weight = metadata_weight
        self.reviews_weight = reviews_weight
        
        # DataFrames for processed data
        self.metadata_df = None
        self.reviews_df = None
        self.combined_product_df = None
    
    def process_metadata_file(self, metadata_path: str, chunksize: int = 10000, frac: float = 1.0) -> None:
        """
        Process an Amazon metadata JSONL file into a DataFrame.
        
        Args:
            metadata_path: Path to the metadata JSONL file
            chunksize: Number of lines to process at once
            frac: Fraction of file to process (0.0 to 1.0), useful for faster development and testing
        """
        start_time = time.time()
        metadata_records = []
        total_lines = self._count_lines(metadata_path)
        
        # Apply sampling if frac < 1.0
        if frac < 1.0:
            processed_lines = int(total_lines * frac)
            logger.info(f"Processing {frac:.2%} of metadata file: {metadata_path} ({processed_lines} of {total_lines} lines)")
        else:
            processed_lines = total_lines
            logger.info(f"Processing metadata file: {metadata_path} with {total_lines} lines")
        
        # Add debug to log the first record's structure
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f_debug:
                first_line = f_debug.readline().strip()
                try:
                    first_record = json.loads(first_line)
                    logger.info(f"First metadata record keys: {list(first_record.keys())}")
                    # Check if product ID is under a different name
                    potential_id_fields = ['asin', 'ASIN', 'productId', 'id', 'product_id', 'parent_asin']
                    available_ids = [field for field in potential_id_fields if field in first_record]
                    if available_ids:
                        logger.info(f"Available ID fields in metadata: {available_ids}")
                    else:
                        logger.warning("No identifiable ID field found in metadata")
                except Exception as e:
                    logger.warning(f"Could not parse first line for debugging: {e}")
        except Exception as e:
            logger.warning(f"Could not open file for debug read: {e}")
        
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                # Process file in chunks with tqdm for progress tracking
                for chunk_start in tqdm(range(0, processed_lines, chunksize), desc="Processing metadata chunks"):
                    chunk_end = min(chunk_start + chunksize, processed_lines)
                    chunk_records = []
                    
                    # Reset file position if not at the beginning
                    if chunk_start > 0:
                        f.seek(0)
                        for _ in range(chunk_start):
                            next(f)
                    
                    # Process lines in this chunk
                    for _ in range(chunk_end - chunk_start):
                        try:
                            line = next(f)
                            metadata = json.loads(line.strip())
                            
                            # Extract ASIN (product ID) - now more flexible
                            asin = None
                            for field in ['asin', 'ASIN', 'productId', 'id', 'product_id', 'parent_asin']:
                                if field in metadata:
                                    asin = metadata[field]
                                    if field != 'asin':
                                        # Normalize the field name to 'asin'
                                        metadata['asin'] = asin
                                    break
                                    
                            if not asin:
                                continue
                            
                            # Process metadata into a flattened dictionary
                            processed_metadata = self._process_metadata_record(metadata)
                            chunk_records.append(processed_metadata)
                            
                        except StopIteration:
                            break
                        except json.JSONDecodeError:
                            logger.warning(f"Skipping invalid JSON line in metadata file")
                        except Exception as e:
                            logger.warning(f"Error processing metadata record: {e}")
                    
                    # Add chunk records to main list
                    metadata_records.extend(chunk_records)
        
        except Exception as e:
            logger.error(f"Error reading metadata file {metadata_path}: {e}")
            raise
        
        # Convert to DataFrame
        self.metadata_df = pd.DataFrame(metadata_records)
        
        # Log the DataFrame columns for debugging
        logger.info(f"Metadata DataFrame columns: {list(self.metadata_df.columns)}")
        logger.info(f"Finished processing metadata file. {len(self.metadata_df)} records loaded in {time.time() - start_time:.2f} seconds.")
    
    def _process_metadata_record(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a metadata record into a flattened dictionary for DataFrame creation.
        
        Args:
            metadata: Raw metadata dictionary
            
        Returns:
            Processed metadata dictionary
        """
        # Basic fields
        processed = {
            'asin': metadata.get('asin'),
            'title': metadata.get('title', ''),
            'main_category': metadata.get('main_category', ''),
            'average_rating': metadata.get('average_rating', 0.0),
            'rating_number': metadata.get('rating_number', 0),
            'price': metadata.get('price', 0.0),
            'store': metadata.get('store', ''),
            'parent_asin': metadata.get('parent_asin', '')
        }
        
        # Handle complex fields
        processed['description_text'] = ' '.join(metadata.get('description', [])) if isinstance(metadata.get('description', []), list) else str(metadata.get('description', ''))
        processed['features_text'] = ' '.join(metadata.get('features', [])) if isinstance(metadata.get('features', []), list) else str(metadata.get('features', ''))
        processed['categories_text'] = ' '.join(metadata.get('categories', [])) if isinstance(metadata.get('categories', []), list) else str(metadata.get('categories', ''))
        
        # Handle details
        details = metadata.get('details', {})
        if details and isinstance(details, dict):
            # Extract most relevant details
            for key in ['Brand', 'Material', 'Color', 'Size', 'Style']:
                if key in details:
                    processed[f'detail_{key.lower()}'] = details[key]
        
        # Generate combined text for recommendation engine
        processed['metadata_text'] = self._extract_metadata_text(metadata)
        
        return processed
    
    def process_reviews_file(self, reviews_path: str, chunksize: int = 10000, frac: float = 1.0) -> None:
        """
        Process an Amazon reviews JSONL file into a DataFrame.
        
        Args:
            reviews_path: Path to the reviews JSONL file
            chunksize: Number of lines to process at once
            frac: Fraction of file to process (0.0 to 1.0), useful for faster development and testing
        """
        start_time = time.time()
        reviews_records = []
        total_lines = self._count_lines(reviews_path)
        
        # Add debug to log the first record's structure
        try:
            with open(reviews_path, 'r', encoding='utf-8') as f_debug:
                first_line = f_debug.readline().strip()
                try:
                    first_record = json.loads(first_line)
                    logger.info(f"First review record keys: {list(first_record.keys())}")
                    # Check if product ID and user ID are under different names
                    potential_product_id_fields = ['asin', 'ASIN', 'productId', 'item_id', 'parent_asin']
                    potential_user_id_fields = ['user_id', 'userId', 'reviewer_id', 'customerId']
                    
                    available_product_ids = [field for field in potential_product_id_fields if field in first_record]
                    available_user_ids = [field for field in potential_user_id_fields if field in first_record]
                    
                    if available_product_ids:
                        logger.info(f"Available product ID fields in reviews: {available_product_ids}")
                    else:
                        logger.warning("No identifiable product ID field found in reviews")
                        
                    if available_user_ids:
                        logger.info(f"Available user ID fields in reviews: {available_user_ids}")
                    else:
                        logger.warning("No identifiable user ID field found in reviews")
                        
                except Exception as e:
                    logger.warning(f"Could not parse first line for debugging: {e}")
        except Exception as e:
            logger.warning(f"Could not open file for debug read: {e}")
        
        # Apply sampling if frac < 1.0
        if frac < 1.0:
            processed_lines = int(total_lines * frac)
            logger.info(f"Processing {frac:.2%} of reviews file: {reviews_path} ({processed_lines} of {total_lines} lines)")
        else:
            processed_lines = total_lines
            logger.info(f"Processing reviews file: {reviews_path} with {total_lines} lines")
        
        try:
            with open(reviews_path, 'r', encoding='utf-8') as f:
                # Process file in chunks with tqdm for progress tracking
                for chunk_start in tqdm(range(0, processed_lines, chunksize), desc="Processing reviews chunks"):
                    chunk_end = min(chunk_start + chunksize, processed_lines)
                    chunk_records = []
                    
                    # Reset file position if not at the beginning
                    if chunk_start > 0:
                        f.seek(0)
                        for _ in range(chunk_start):
                            next(f)
                    
                    # Process lines in this chunk
                    for _ in range(chunk_end - chunk_start):
                        try:
                            line = next(f)
                            review = json.loads(line.strip())
                            
                            # Get the item ID (ASIN) - more flexible now
                            asin = None
                            for field in ['asin', 'ASIN', 'productId', 'item_id', 'parent_asin']:
                                if field in review:
                                    asin = review[field]
                                    break
                            
                            # Get the user ID - more flexible now
                            user_id = None
                            for field in ['user_id', 'userId', 'reviewer_id', 'customerId']:
                                if field in review:
                                    user_id = review[field]
                                    break
                                
                            if not asin or not user_id:
                                continue
                            
                            # Skip low ratings if configured
                            if not self.include_low_ratings and review.get('rating', 0) < 3:
                                continue
                            
                            # Process review record
                            processed_review = {
                                'user_id': user_id,
                                'asin': asin,
                                'rating': review.get('rating', 0),
                                'helpful_votes': review.get('helpful_votes', 0),
                                'verified_purchase': review.get('verified_purchase', False),
                                'title': review.get('title', ''),
                                'text': review.get('text', ''),
                                'parent_asin': review.get('parent_asin', ''),
                                'sort_timestamp': review.get('sort_timestamp', 0)
                            }
                            
                            chunk_records.append(processed_review)
                            
                        except StopIteration:
                            break
                        except json.JSONDecodeError:
                            logger.warning(f"Skipping invalid JSON line in reviews file")
                        except Exception as e:
                            logger.warning(f"Error processing review: {e}")
                    
                    # Add chunk records to main list
                    reviews_records.extend(chunk_records)
        
        except Exception as e:
            logger.error(f"Error reading reviews file {reviews_path}: {e}")
            raise
        
        # Convert to DataFrame
        self.reviews_df = pd.DataFrame(reviews_records)
        
        # Log DataFrame columns for debugging
        logger.info(f"Reviews DataFrame columns: {list(self.reviews_df.columns)}")
        logger.info(f"Finished processing reviews file. {len(self.reviews_df)} reviews loaded in {time.time() - start_time:.2f} seconds.")

        # Apply filters
        self._filter_reviews()
    
    def _filter_reviews(self) -> None:
        """
        Filter reviews based on minimum counts per user and per item.
        """
        if self.reviews_df is None or len(self.reviews_df) == 0:
            logger.warning("No reviews to filter.")
            return
        
        original_count = len(self.reviews_df)
        
        # Count reviews per user
        user_review_counts = self.reviews_df['user_id'].value_counts()
        valid_users = user_review_counts[user_review_counts >= self.min_reviews_per_user].index
        
        # Count reviews per item
        item_review_counts = self.reviews_df['asin'].value_counts()
        valid_items = item_review_counts[item_review_counts >= self.min_reviews_per_item].index
        
        # Filter reviews
        self.reviews_df = self.reviews_df[
            (self.reviews_df['user_id'].isin(valid_users)) & 
            (self.reviews_df['asin'].isin(valid_items))
        ]
        
        # Limit max reviews per item
        if self.max_reviews_per_item > 0:
            # Group by asin and take top N reviews per group
            # Sort by helpful_votes and verified_purchase for quality
            self.reviews_df = self.reviews_df.sort_values(
                ['asin', 'helpful_votes', 'verified_purchase'], 
                ascending=[True, False, False]
            )
            
            self.reviews_df = self.reviews_df.groupby('asin').head(self.max_reviews_per_item).reset_index(drop=True)
        
        filtered_count = len(self.reviews_df)
        logger.info(f"Filtered reviews from {original_count} to {filtered_count} " +
                   f"based on minimum counts (user: {self.min_reviews_per_user}, item: {self.min_reviews_per_item}) " +
                   f"and max reviews per item ({self.max_reviews_per_item})")
    
    def _count_lines(self, file_path: str) -> int:
        """
        Count the number of lines in a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Number of lines in the file
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    
    def combine_product_data(self) -> None:
        """
        Combine metadata and reviews to create rich content representation for each product.
        This merges information from both sources with appropriate weighting.
        """
        if self.metadata_df is None or self.reviews_df is None:
            logger.error("Metadata or reviews not loaded. Call process_metadata_file() and process_reviews_file() first.")
            return
        
        start_time = time.time()
        logger.info("Combining metadata and reviews into product representations...")
        
        # First, check and map column names if needed
        self._check_and_map_columns()
        
        # Get valid ASINs (products with metadata and reviews)
        if 'asin' not in self.metadata_df.columns or 'asin' not in self.reviews_df.columns:
            logger.error(f"Required column 'asin' not found in data. Available metadata columns: {list(self.metadata_df.columns)}")
            logger.error(f"Available reviews columns: {list(self.reviews_df.columns)}")
            raise KeyError("Required column 'asin' not found in data")
            
        valid_asins = set(self.metadata_df['asin']).intersection(set(self.reviews_df['asin'].unique()))
        logger.info(f"Found {len(valid_asins)} products with both metadata and sufficient reviews")
        
        # Filter metadata to valid ASINs
        valid_metadata_df = self.metadata_df[self.metadata_df['asin'].isin(valid_asins)].copy()
        
        # Group reviews by ASIN and aggregate review text
        reviews_by_asin = {}
        for asin, group in tqdm(self.reviews_df.groupby('asin'), desc="Processing reviews by product"):
            if asin in valid_asins:
                reviews_by_asin[asin] = self._extract_reviews_text(group.to_dict('records'))
        
        # Add combined text to metadata DataFrame
        product_texts = {}
        for _, row in tqdm(valid_metadata_df.iterrows(), total=len(valid_metadata_df), desc="Creating combined text"):
            asin = row['asin']
            if asin in reviews_by_asin:
                # Ensure metadata_text column exists
                metadata_text = row.get('metadata_text', '')
                if not metadata_text and 'metadata_text' not in row:
                    # If no metadata_text column, create text from available data
                    metadata_text = self._extract_metadata_text_from_row(row)
                
                reviews_text = reviews_by_asin[asin]
                
                # Combine with weighting
                combined_text = self._combine_text_with_weights(
                    metadata_text, 
                    reviews_text, 
                    self.metadata_weight, 
                    self.reviews_weight
                )
                
                product_texts[asin] = combined_text
        
        # Create combined DataFrame
        combined_data = []
        for asin, combined_text in product_texts.items():
            metadata_row = valid_metadata_df[valid_metadata_df['asin'] == asin].iloc[0]
            combined_data.append({
                'asin': asin,
                'title': metadata_row.get('title', ''),
                'main_category': metadata_row.get('main_category', ''),
                'average_rating': metadata_row.get('average_rating', 0.0),
                'price': metadata_row.get('price', 0.0),
                'review_count': self.reviews_df[self.reviews_df['asin'] == asin].shape[0],
                'combined_text': combined_text
            })
        
        self.combined_product_df = pd.DataFrame(combined_data)
        logger.info(f"Combined data for {len(self.combined_product_df)} products in {time.time() - start_time:.2f} seconds")
    
    def _extract_metadata_text(self, metadata: Dict[str, Any]) -> str:
        """
        Extract relevant text from product metadata.
        
        Args:
            metadata: Product metadata dictionary
            
        Returns:
            Formatted text representation of metadata
        """
        text_parts = []
        
        # Add title (with higher importance by repeating)
        title = metadata.get('title', '')
        if title:
            text_parts.append(title)
            text_parts.append(title)  # Repeated for higher weight
        
        # Add description
        description = metadata.get('description', [])
        if isinstance(description, list):
            description = ' '.join(description)
        if description:
            text_parts.append(description)
        
        # Add features
        features = metadata.get('features', [])
        if features:
            if isinstance(features, list):
                features_text = ' '.join(features)
            else:
                features_text = str(features)
            text_parts.append(features_text)
        
        # Add categories
        categories = metadata.get('categories', [])
        if categories:
            if isinstance(categories, list):
                categories_text = ' '.join(categories)
            else:
                categories_text = str(categories)
            text_parts.append(categories_text)
        
        # Add main category
        main_category = metadata.get('main_category', '')
        if main_category:
            text_parts.append(main_category)
        
        # Add store/brand
        store = metadata.get('store', '')
        if store:
            text_parts.append(f"Brand: {store}")
        
        # Add details
        details = metadata.get('details', {})
        if details and isinstance(details, dict):
            # Filter for most relevant details
            relevant_keys = ['Material', 'Color', 'Size', 'Style', 'Brand']
            details_text = ' '.join([f"{k}: {v}" for k, v in details.items() 
                                   if k in relevant_keys and v])
            if details_text:
                text_parts.append(details_text)
        
        return ' '.join(text_parts)
    
    def _extract_reviews_text(self, reviews: List[Dict[str, Any]]) -> str:
        """
        Extract relevant text from product reviews.
        
        Args:
            reviews: List of review dictionaries
            
        Returns:
            Formatted text representation of reviews
        """
        text_parts = []
        
        # Process each review
        for review in reviews:
            review_parts = []
            
            # Add title (with higher importance)
            title = review.get('title', '')
            if title:
                review_parts.append(title)
            
            # Add text
            text = review.get('text', '')
            if text:
                review_parts.append(text)
            
            # Skip if no content
            if not review_parts:
                continue
            
            # Get review weight based on helpfulness and verification
            weight = 1.0
            
            # Increase weight for helpful reviews
            helpful_votes = review.get('helpful_votes', 0)
            if helpful_votes > 5:
                weight += 0.5
            elif helpful_votes > 0:
                weight += 0.2
            
            # Increase weight for verified purchases
            if review.get('verified_purchase', False):
                weight += 0.3
            
            # Add review text with appropriate weight
            review_text = ' '.join(review_parts)
            for _ in range(int(weight)):
                text_parts.append(review_text)
        
        return ' '.join(text_parts)
    
    def _combine_text_with_weights(
        self, 
        metadata_text: str, 
        reviews_text: str, 
        metadata_weight: float, 
        reviews_weight: float
    ) -> str:
        """
        Combine metadata and reviews text with appropriate weighting.
        
        Args:
            metadata_text: Text extracted from metadata
            reviews_text: Text extracted from reviews
            metadata_weight: Weight for metadata text
            reviews_weight: Weight for reviews text
            
        Returns:
            Combined weighted text
        """
        # Simple weighting by repeating text based on weight ratio
        metadata_repeats = max(1, int(metadata_weight))
        reviews_repeats = max(1, int(reviews_weight))
        
        # Handle fractional weights
        if metadata_weight % 1 > 0:
            metadata_fraction = metadata_text if metadata_weight % 1 >= 0.5 else ""
        else:
            metadata_fraction = ""
            
        if reviews_weight % 1 > 0:
            reviews_fraction = reviews_text if reviews_weight % 1 >= 0.5 else ""
        else:
            reviews_fraction = ""
        
        # Combine repeats and fractions
        weighted_metadata = ' '.join([metadata_text] * metadata_repeats + [metadata_fraction]).strip()
        weighted_reviews = ' '.join([reviews_text] * reviews_repeats + [reviews_fraction]).strip()
        
        # Join everything
        combined_text = ' '.join([weighted_metadata, weighted_reviews]).strip()
        return combined_text
    
    def get_processed_data(self) -> Tuple[Dict[str, str], List[str], Dict[str, Dict[str, Any]]]:
        """
        Get the processed data for use in a recommendation system.
        
        Returns:
            Tuple of (product_texts, product_asins, item_details)
        """
        if self.combined_product_df is None:
            logger.warning("No combined product data available")
            return {}, [], {}
        
        # Convert DataFrame to dictionary format
        product_texts = dict(zip(self.combined_product_df['asin'], self.combined_product_df['combined_text']))
        product_asins = self.combined_product_df['asin'].tolist()
        
        # Create item details dictionary
        item_details = {}
        for _, row in tqdm(self.combined_product_df.iterrows(), total=len(self.combined_product_df), desc="Processing item details"):
            asin = row['asin']
            item_details[asin] = {
                'title': row.get('title', ''),
                'main_category': row.get('main_category', ''),
                'average_rating': row.get('average_rating', 0.0),
                'price': row.get('price', 0.0),
                'review_count': row.get('review_count', 0),
                # Add any other relevant fields
            }
            
            # Add reviews if available
            if self.reviews_df is not None:
                item_reviews = self.reviews_df[self.reviews_df['asin'] == asin]
                item_details[asin]['reviews'] = item_reviews[['user_id', 'rating', 'text', 'helpful_votes']].to_dict('records')
        
        return product_texts, product_asins, item_details
    
    def save_to_csv(self, output_dir: str) -> None:
        """
        Save processed data to CSV files.
        
        Args:
            output_dir: Directory to save CSV files
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Save metadata
        if self.metadata_df is not None:
            metadata_path = os.path.join(output_dir, 'processed_metadata.csv')
            self.metadata_df.to_csv(metadata_path, index=False)
            logger.info(f"Saved processed metadata to {metadata_path}")
        
        # Save reviews
        if self.reviews_df is not None:
            reviews_path = os.path.join(output_dir, 'processed_reviews.csv')
            self.reviews_df.to_csv(reviews_path, index=False)
            logger.info(f"Saved processed reviews to {reviews_path}")
        
        # Save combined data
        if self.combined_product_df is not None:
            combined_path = os.path.join(output_dir, 'combined_product_data.csv')
            self.combined_product_df.to_csv(combined_path, index=False)
            logger.info(f"Saved combined product data to {combined_path}")
        
        # Save data for recommender in specific format
        if self.combined_product_df is not None:
            recommender_data_path = os.path.join(output_dir, 'recommender_data.csv')
            recommender_df = self.combined_product_df[['asin', 'title', 'main_category', 'average_rating', 'combined_text']]
            recommender_df.to_csv(recommender_data_path, index=False)
            logger.info(f"Saved recommender data to {recommender_data_path}")

    def load_processed_data_from_csv(self, input_dir: str) -> None:
        """
        Load pre-processed data from CSV files instead of processing from JSONL files.
        This is useful for faster loading when data has already been processed.
        
        Args:
            input_dir: Directory containing processed CSV files
        """
        input_dir = Path(input_dir)
        start_time = time.time()
        
        # Check if the required files exist
        metadata_path = input_dir / 'processed_metadata.csv'
        reviews_path = input_dir / 'processed_reviews.csv'
        combined_path = input_dir / 'combined_product_data.csv'
        
        if not os.path.exists(metadata_path) or not os.path.exists(reviews_path):
            logger.error(f"Processed files not found in {input_dir}")
            raise FileNotFoundError(f"Required CSV files not found in {input_dir}")
        
        # Load the DataFrames
        logger.info(f"Loading pre-processed data from {input_dir}")
        
        try:
            # Load metadata with low_memory=False to prevent dtype warnings
            self.metadata_df = pd.read_csv(metadata_path, low_memory=False)
            logger.info(f"Loaded {len(self.metadata_df)} metadata records")
            
            # Load reviews with low_memory=False
            self.reviews_df = pd.read_csv(reviews_path, low_memory=False)
            logger.info(f"Loaded {len(self.reviews_df)} review records")
            
            if os.path.exists(combined_path):
                self.combined_product_df = pd.read_csv(combined_path, low_memory=False)
                logger.info(f"Loaded {len(self.combined_product_df)} combined product records")
            else:
                logger.warning(f"Combined product data file not found at {combined_path}")
                logger.info("Will generate combined data from metadata and reviews")
                self.combine_product_data()
            
            logger.info(f"Loaded all data in {time.time() - start_time:.2f} seconds")
            
        except Exception as e:
            logger.error(f"Error loading data from CSV: {e}")
            raise

    def _extract_metadata_text_from_row(self, row: pd.Series) -> str:
        """
        Extract metadata text from a DataFrame row when the processed metadata_text is not available.
        
        Args:
            row: Row from the metadata DataFrame
            
        Returns:
            Extracted text from available columns
        """
        text_parts = []
        
        # Add title (with higher importance)
        if 'title' in row and row['title']:
            text_parts.append(row['title'])
            text_parts.append(row['title'])  # Repeat for emphasis
        
        # Add description if available
        if 'description_text' in row and row['description_text']:
            text_parts.append(row['description_text'])
        
        # Add features if available
        if 'features_text' in row and row['features_text']:
            text_parts.append(row['features_text'])
        
        # Add category information
        if 'main_category' in row and row['main_category']:
            text_parts.append(row['main_category'])
        
        if 'categories_text' in row and row['categories_text']:
            text_parts.append(row['categories_text'])
        
        # Add any detail fields that might be available
        for col in row.index:
            if col.startswith('detail_') and row[col]:
                text_parts.append(f"{col.replace('detail_', '')}: {row[col]}")
        
        return ' '.join(text_parts)
    
    def _check_and_map_columns(self) -> None:
        """
        Check for required columns and map alternative column names if needed.
        """
        # Log the available columns
        logger.info(f"Metadata columns: {list(self.metadata_df.columns)}")
        logger.info(f"Reviews columns: {list(self.reviews_df.columns)}")
        
        # Check for alternative 'asin' column names in metadata
        if 'asin' not in self.metadata_df.columns:
            alternatives = ['ASIN', 'product_id', 'id', 'item_id', 'product_asin']
            for alt in alternatives:
                if alt in self.metadata_df.columns:
                    logger.info(f"Mapping metadata column '{alt}' to 'asin'")
                    self.metadata_df['asin'] = self.metadata_df[alt]
                    break
        
        # Check for alternative 'asin' column names in reviews
        if 'asin' not in self.reviews_df.columns:
            alternatives = ['ASIN', 'product_id', 'id', 'item_id', 'product_asin']
            for alt in alternatives:
                if alt in self.reviews_df.columns:
                    logger.info(f"Mapping reviews column '{alt}' to 'asin'")
                    self.reviews_df['asin'] = self.reviews_df[alt]
                    break


# Function to integrate with HybridContentRecommender
def process_and_save_data(
    metadata_file: str,
    reviews_file: str,
    output_dir: str = "processed_data",
    max_reviews_per_item: int = 20,
    min_reviews_per_item: int = 5,
    min_reviews_per_user: int = 2,
    metadata_weight: float = 1.5,
    reviews_weight: float = 1.0,
    frac: float = 1.0
) -> Tuple[Dict[str, str], List[str], Dict[str, Dict[str, Any]]]:
    """
    Load and process Amazon data files for use with HybridContentRecommender.
    
    Args:
        metadata_file: Path to metadata JSONL file
        reviews_file: Path to reviews JSONL file
        output_dir: Directory to save processed data as CSV
        max_reviews_per_item: Maximum reviews per item to process
        min_reviews_per_item: Minimum reviews required for item inclusion
        min_reviews_per_user: Minimum reviews required for user inclusion
        metadata_weight: Weight for metadata text
        reviews_weight: Weight for reviews text
        frac: Fraction of data to process (0.0-1.0) for faster development
        
    Returns:
        Tuple of (product_texts, product_asins, item_details) ready for HybridContentRecommender
    """
    processor = AmazonDataProcessor(
        max_reviews_per_item=max_reviews_per_item,
        min_reviews_per_item=min_reviews_per_item,
        min_reviews_per_user=min_reviews_per_user,
        metadata_weight=metadata_weight,
        reviews_weight=reviews_weight
    )
    
    # Process files
    processor.process_metadata_file(metadata_file, frac=frac)
    processor.process_reviews_file(reviews_file, frac=frac)
    processor.combine_product_data()
    
    # Save processed data
    processor.save_to_csv(output_dir)
    
    # Return processed data
    return processor.get_processed_data()


# Function to load already processed data for recommender
def load_processed_data_for_recommender(
        input_dir: str
) -> Tuple[Dict[str, str], List[str], Dict[str, Dict[str, Any]]]:
    """
    Load already processed Amazon data from CSV files for use with HybridContentRecommender.
    This is much faster than processing raw JSONL files again.
    
    Args:
        input_dir: Directory containing processed CSV files (from a previous run of load_amazon_data_for_recommender)
        
    Returns:
        Tuple of (product_texts, product_asins, item_details) ready for HybridContentRecommender
    """
    processor = AmazonDataProcessor()
    
    # Load pre-processed data
    processor.load_processed_data_from_csv(input_dir)
    
    # Return processed data
    return processor.get_processed_data()


# Example usage with HybridContentRecommender
def example_usage():
    from hybrid_content_recommender import HybridContentRecommender
    
    # Define file paths
    metadata_file = "path/to/amazon_metadata.json"
    reviews_file = "path/to/amazon_reviews.json"
    output_dir = "processed_data"
    
    # Process Amazon data
    product_texts, product_asins, item_details = process_and_save_data(
        metadata_file=metadata_file,
        reviews_file=reviews_file,
        output_dir=output_dir,
        max_reviews_per_item=20,
        min_reviews_per_item=5,
        min_reviews_per_user=2
    )
    
    # Initialize recommender
    recommender = HybridContentRecommender()
    
    # Instead of calling load_reviews_jsonl, inject the processed data
    recommender.product_texts = product_texts
    recommender.product_asins = product_asins
    
    # Build matrices with the processed data
    recommender._build_tfidf_matrix()
    recommender._build_sbert_embeddings()
    
    # Now the recommender is ready for use
    return recommender


if __name__ == "__main__":
    # Example usage
    metadata_file = DATASET_DIR / "meta_Electronics.jsonl"
    reviews_file = DATASET_DIR / "Electronics.jsonl"
    processed_dir = DATASET_DIR / "processed_data"
    
    # Create processed directory if it doesn't exist
    if not os.path.exists(processed_dir):
        os.makedirs(processed_dir)
    
    # Check if we have already processed data
    csv_files_exist = all(os.path.exists(processed_dir / f) for f in [
        'processed_metadata.csv', 
        'processed_reviews.csv', 
        'combined_product_data.csv'
    ])
    
    if csv_files_exist:
        print("Found existing processed data. Loading from CSV files...")
        product_texts, product_asins, item_details = load_processed_data_for_recommender(processed_dir)
        print(f"Loaded {len(product_asins)} products from processed CSV files")
    elif os.path.exists(metadata_file) and os.path.exists(reviews_file):
        print("Processing raw JSONL files...")
        # Process only a portion of the data for faster testing
        product_texts, product_asins, item_details = process_and_save_data(
            metadata_file=metadata_file,
            reviews_file=reviews_file,
            output_dir=processed_dir,
            frac=0.1  # Process only 20% of the data for faster testing
        )
        print(f"Processed {len(product_asins)} products from raw JSONL files")
    else:
        print("Neither processed data nor raw files found. Please check your paths.")
        exit(1)
    
    # Sample output to verify
    if product_asins:
        sample_asin = product_asins[0]
        print(f"Sample text for {sample_asin}: {product_texts[sample_asin][:200]}...")