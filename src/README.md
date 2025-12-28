# LLM-Compatible Recommendation System

This directory contains the implementation of the LLM-Compatible Recommendation System, which integrates traditional recommendation techniques with large language models (LLMs) to provide personalized recommendations through natural language conversation.

## Directory Structure

- `recommendation_engine/`: Contains the recommendation engine implementations
  - `base.py`: Base class for recommendation engines
  - `lightfm_recommender.py`: LightFM-based collaborative filtering recommender
- `llm_interface/`: Contains the LLM integration components
  - `preference_parser.py`: Extracts structured preferences from natural language
  - `prompt_constructor.py`: Constructs prompts for LLM integration
  - `recommendation_api.py`: API for integrating LLMs with recommendation engines
- `utils/`: Utility functions
  - `data_preprocess.py`: Data preprocessing utilities
- `examples/`: Example scripts demonstrating the system
  - `train_model.py`: Script to preprocess data and train the model
  - `recommendation_api_example.py`: Example usage of the recommendation API
  - `api_server.py`: FastAPI server for the recommendation API
  - `llm_integration.py`: Integration with an LLM service

## Getting Started

1. Preprocess the data and train the model:

   ```bash
   python src/examples/train_model.py
   ```

2. Run the example script to test the recommendation API:

   ```bash
   python src/examples/recommendation_api_example.py
   ```

3. Start the API server:

   ```bash
   python src/examples/api_server.py
   ```

4. Test the LLM integration:
   ```bash
   python src/examples/llm_integration.py
   ```

## Key Components

### Recommendation Engine

The recommendation engine is based on the LightFM library, which provides a hybrid recommendation algorithm that combines collaborative filtering and content-based filtering. The engine is implemented in the `LightFMRecommender` class, which adapts the existing LightFM implementation from the project.

### LLM Interface

The LLM interface consists of three main components:

1. **Preference Parser**: Extracts structured preferences from natural language user inputs using regular expressions.
2. **Prompt Constructor**: Constructs prompts for LLM integration, including chain-of-thought reasoning.
3. **Recommendation API**: Provides an API for integrating LLMs with recommendation engines, serving as the bridge between natural language and structured recommendation systems.

### API Server

The API server provides a RESTful API for the recommendation system, allowing clients to:

1. Get recommendations based on natural language queries
2. Get explanations for recommendations
3. Update conversation history

### LLM Integration

The LLM integration demonstrates how to integrate the recommendation API with an LLM service, such as OpenAI's GPT models. It handles:

1. Sending user messages to the recommendation API
2. Generating responses using the LLM
3. Updating conversation history in the recommendation API
