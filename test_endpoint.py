from gradio_client import Client
import json

try:
    client = Client("THzva/deeppersona-experience")
    result = client.predict(
            age=25,
            gender="Male",
            occupation="UX Researcher",
            city="Berlin",
            country="Germany",
            custom_values="Efficiency, Transparency",
            custom_life_attitude="Optimistic, Tech-savvy",
            life_story="Born in Germany, studied Psychology, fascinated by Human-Computer Interaction.",
            interests_hobbies="Coding, Photography, Hiking",
            attribute_count=200,
            api_name="/generate_persona"
    )
    print("SUCCESS")
    print(result)
except Exception as e:
    print(f"FAILED: {e}")
