from gradio_client import Client
import json

client = Client("https://harvesthealth-xxg-backup.hf.space/")

print("--- Testing /get_repo_branches ---")
try:
    result = client.predict(
            repo_full_name="JsonLord/tiny_web",
            api_name="/get_repo_branches"
    )
    print(f"Result: {result}")
except Exception as e:
    print(f"Error: {e}")

print("\n--- Testing /handle_generate ---")
try:
    # Using small values for quick test
    result = client.predict(
            theme="Education",
            customer_profile="Student looking for online courses",
            num_personas=1,
            api_name="/handle_generate"
    )
    print(f"Result: {result}")
except Exception as e:
    print(f"Error: {e}")
