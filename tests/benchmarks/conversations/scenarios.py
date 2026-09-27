SCENARIOS = [
    {
        "id": "scenario_1_clarification",
        "name": "Multi-Turn Clarification",
        "conversation": "User: I want a TV.\nAssistant: What size and budget?\nUser: 55 inch, under $500.",
        "expected_intent": "refining_options",
        "expected_constraints": [
            {"attribute": "category", "operator": "include", "value": "TV"},
            {"attribute": "screen_size", "operator": "equal", "value": "55"},
            {"attribute": "price", "operator": "less_than", "value": 500}
        ],
        "expected_ready": True
    },
    {
        "id": "scenario_2_high_detail",
        "name": "High-Detail Upfront",
        "conversation": "User: I need a gaming PC with an RTX 4080, 32GB RAM, and 2TB SSD.\nAssistant: Got it. Do you have a budget?\nUser: Under $2500.",
        "expected_intent": "refining_options",
        "expected_constraints": [
            {"attribute": "category", "operator": "include", "value": "gaming PC"},
            {"attribute": "gpu", "operator": "include", "value": "RTX 4080"},
            {"attribute": "ram", "operator": "equal", "value": "32GB"},
            {"attribute": "storage", "operator": "equal", "value": "2TB"},
            {"attribute": "price", "operator": "less_than", "value": 2500}
        ],
        "expected_ready": True
    },
    {
        "id": "scenario_3_vague",
        "name": "Vague User",
        "conversation": "User: I want something to read books on, maybe outside in the sun.",
        "expected_intent": "initial_search",
        "expected_constraints": [],
        "expected_ready": False
    },
    {
        "id": "scenario_4_off_topic",
        "name": "Out-of-Domain/Off-Topic",
        "conversation": "User: What is the capital of France?",
        "expected_intent": "exploring_domain", # Or change topic, depending on prompt strictness
        "expected_constraints": [],
        "expected_ready": False
    },
    {
        "id": "scenario_5_correction",
        "name": "Preference Change/Correction",
        "conversation": "User: I need running shoes size 10.\nAssistant: Any specific brand?\nUser: Actually, make that size 10.5, and I prefer Nike.",
        "expected_intent": "refining_options",
        "expected_constraints": [
            {"attribute": "category", "operator": "include", "value": "running shoes"},
            {"attribute": "size", "operator": "equal", "value": "10.5"}
        ],
        "expected_ready": True
    }
]
