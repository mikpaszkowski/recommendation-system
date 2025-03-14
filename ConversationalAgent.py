import os
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

os.environ["OPENAI_API_KEY"] = ""

# Inicjalizacja modelu językowego
llm = OpenAI(temperature=0.3)

# Szablon prompta dla rekomendacji
recommendation_template = """
Jesteś asystentem zakupowym, który pomaga użytkownikom znaleźć produkty elektroniczne.
Użytkownik pyta: {user_query}

Na podstawie ich zapytania, polecasz następujące produkty:
{recommendations}

Odpowiedz w formie naturalnej konwersacji, wyjaśniając dlaczego te produkty mogą być odpowiednie dla użytkownika.
Odpowiedź:
"""

recommendation_prompt = PromptTemplate(
    input_variables=["user_query", "recommendations"],
    template=recommendation_template
)

recommendation_chain = LLMChain(llm=llm, prompt=recommendation_prompt)

# Funkcja do ekstrakcji intencji z zapytania użytkownika
def extract_intent(query):
    """Analizuje zapytanie użytkownika, aby zrozumieć jego intencje zakupowe"""
    intent_template = """
    Przeanalizuj poniższe zapytanie użytkownika i wypisz kluczowe cechy produktu, którego szuka użytkownik:
    Zapytanie: {query}
    
    Wymień cechy w formacie JSON:
    """
    
    intent_prompt = PromptTemplate(
        input_variables=["query"],
        template=intent_template
    )
    
    intent_chain = LLMChain(llm=llm, prompt=intent_prompt)
    
    response = intent_chain.run(query=query)
    # W rzeczywistej implementacji należałoby przetworzyć odpowiedź JSON
    
    return {
        "category": "Electronics",  # Uproszczone dla przykładu
        "features": ["dobra jakość", "przystępna cena"]
    }

# Funkcja do generowania odpowiedzi na zapytanie użytkownika
def generate_response(query):
    """Generuje odpowiedź na zapytanie użytkownika wykorzystując model językowy i silnik rekomendacji"""
    # Ekstrakcja intencji
    intent = extract_intent(query)
    
    # Wyszukiwanie produktów które pasują do intencji
    # Tu należałoby zaimplementować bardziej zaawansowane filtrowanie
    sample_products = product_info.head(5)
    
    # Formatowanie rekomendacji
    recommendations_text = ""
    for idx, (prod_id, product) in enumerate(sample_products.iterrows(), 1):
        recommendations_text += f"{idx}. {product['title']} (Kategoria: {product['main_category']}, Ocena: {product['average_rating']})\n"
    
    # Generowanie odpowiedzi
    response = recommendation_chain.run(
        user_query=query,
        recommendations=recommendations_text
    )
    
    return response

# Przykładowe użycie
user_query = "Szukam dobrego aparatu cyfrowego do zdjęć przyrodniczych, najlepiej wodoodpornego."
response = generate_response(user_query)
print(response)