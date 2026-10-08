import os
import time
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key=os.getenv("GEMINI_API_KEY")

if not api_key:
    print("GEMINI_API_KEY not found in .env")
    exit()

client=genai.Client(
    api_key=api_key
)

print("Gemini AI Chat")
print("Type 'exit' to stop")
print("-" * 40)

while True:

    question=input("You: ")

    if question.lower()=="exit":
        print("Chat ended.")
        break

    if not question.strip():
        continue

    for attempt in range(3):

        try:

            response=client.models.generate_content(
                model="gemini-3.8-flash",
                contents=question
            )

            print("AI:",response.text)
            print()
            break

        except Exception as e:

            error=str(e)

            if "503" in error or "UNAVAILABLE" in error:

                if attempt<2:
                    print("Gemini is temporarily busy. Retrying...")
                    time.sleep(5)
                else:
                    print("Gemini is currently busy. Please try again later.")
                    print()

            else:

                print("Error:",e)
                print()
                break