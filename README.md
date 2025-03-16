# Conversational Recommendation System

This repository contains the implementation of a conversational recommendation system for a master's thesis. The system integrates traditional recommendation techniques (content-based filtering and collaborative filtering) with large language models (LLMs) to provide personalized recommendations through natural language conversation.

## Project Structure

- `src/`: Contains the core implementation of the system
  - `recommendation_engine/`: Recommendation engine implementations
  - `llm_interface/`: LLM integration components
  - `utils/`: Utility functions
  - `examples/`: Example scripts
- `data_processing_and_cleaning.ipynb`: Jupyter notebook for data processing
- `training.py`: Script for training the recommendation model
- `recommendation_api.py`: FastAPI implementation of the recommendation API
- `ConversationalAgent.py`: Implementation of the conversational agent

## Key Features

- **LLM-Compatible Recommendation API**: Bridge between natural language and structured recommendation systems
- **Hybrid Recommendation Engine**: Combines content-based and collaborative filtering using LightFM
- **Preference Extraction**: Extracts structured preferences from natural language
- **Chain-of-Thought Prompting**: Structured reasoning for explainable recommendations
- **Personalization**: Maintains user profiles and adapts recommendations

## Getting Started

### Prerequisites

- Python 3.8+
- Dependencies listed in `requirements.txt`

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/recommendation-system.git
cd recommendation-system

# Install dependencies
pip install -r requirements.txt
```

### Data Preparation

The system uses the Online Retail dataset, which is included in the repository as `online_retail_dataset.xlsx`. You can preprocess the data and train the model using:

```bash
python src/examples/train_model.py
```

### Running the Examples

```bash
# Run the recommendation API example
python src/examples/recommendation_api_example.py

# Start the API server
python src/examples/api_server.py

# Test the LLM integration
python src/examples/llm_integration.py
```

## Research Focus

This implementation focuses on two key research areas:

1. **LLM Prompting Strategies**: Developing specialized prompting techniques for recommendation tasks
2. **Personalization Techniques**: Creating methods to build and update user profiles during conversation

## License

This project is licensed under the MIT License - see the LICENSE file for details.
