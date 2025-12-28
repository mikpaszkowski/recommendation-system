def process_reviews_for_products(self, reviews_path: str, product_asins: Set[str], chunksize: int = 10000) -> None:
    """
    Process reviews file and extract only reviews for specified products.
    Uses set-based lookups for optimal performance (O(1) complexity).
    
    Args:
        reviews_path: Path to the reviews file (JSONL)
        product_asins: Set of product ASINs to include reviews for
        chunksize: Number of reviews to process in each chunk for progress reporting
    """
    logging.info(f"Processing reviews from {reviews_path} for {len(product_asins)} specific products")
    
    # Clear any existing reviews data before we start
    self.reviews = {}
    self.user_reviews = {}
    
    # Initialize counters for tracking progress
    total_lines = self._count_lines(reviews_path)
    processed_lines = 0
    matching_reviews = 0
    
    # Ensure product_asins is a set for O(1) lookups
    if not isinstance(product_asins, set):
        product_asins = set(product_asins)
        logging.info(f"Converted product_asins to a set with {len(product_asins)} items")
    
    # Initialize review containers for filtered products
    for asin in product_asins:
        self.reviews[asin] = []
    
    # Process the reviews file line by line
    with open(reviews_path, 'r') as f:
        for line in f:
            # Update progress periodically
            processed_lines += 1
            if processed_lines % chunksize == 0:
                logging.info(f"Processed {processed_lines:,}/{total_lines:,} reviews " 
                            f"({processed_lines/total_lines:.1%}), found {matching_reviews:,} matching reviews")
            
            # Parse the review JSON
            try:
                review = json.loads(line.strip())
            except json.JSONDecodeError:
                self.errors['review_json'] = self.errors.get('review_json', 0) + 1
                continue
            
            # Check if this review is for one of our target products - O(1) lookup
            product_id = review.get('asin')
            if not product_id or product_id not in product_asins:
                continue
            
            # Process the review since it matches our target products
            try:
                processed_review = self._process_review_record(review)
                if processed_review:
                    matching_reviews += 1
                    
                    # Add to product reviews
                    asin = processed_review['asin']
                    self.reviews[asin].append(processed_review)
                    
                    # Add to user reviews dictionary
                    user_id = processed_review['reviewer_id']
                    if user_id not in self.user_reviews:
                        self.user_reviews[user_id] = []
                    self.user_reviews[user_id].append(processed_review)
            except Exception as e:
                self.errors['review_processing'] = self.errors.get('review_processing', 0) + 1
                logging.error(f"Error processing review: {str(e)}")
                continue
    
    # Log summary statistics
    products_with_reviews = sum(1 for asin, reviews in self.reviews.items() if reviews)
    num_users = len(self.user_reviews)
    total_reviews = matching_reviews
    
    logging.info(f"Review processing complete:")
    logging.info(f"- Found {total_reviews:,} reviews for {products_with_reviews:,}/{len(product_asins):,} products")
    if products_with_reviews > 0:
        logging.info(f"- Average {total_reviews / products_with_reviews:.1f} reviews per product with reviews")
    
    if num_users > 0:
        logging.info(f"- {num_users:,} users contributed reviews, average {total_reviews / num_users:.1f} reviews per user")
    
    # Report any errors
    if self.errors:
        for error_type, count in self.errors.items():
            if error_type.startswith('review_') and count > 0:
                logging.warning(f"- {count:,} {error_type} errors encountered") 