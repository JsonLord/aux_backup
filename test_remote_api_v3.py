from gradio_client import Client
import json

client = Client("https://harvesthealth-xxg-backup.hf.space/")

print("\n--- Testing /handle_generate with Persona Pool logic ---")
try:
    result = client.predict(
            theme="Education",
            customer_profile="Student",
            num_personas=1,
            api_name="/handle_generate"
    )
    print(f"Result: {result}")
except Exception as e:
    print(f"Error: {e}")
