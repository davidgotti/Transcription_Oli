import transformers
import torch

# Paste your Hugging Face token here.
# Get your token from https://huggingface.co/settings/tokens
hugging_face_token = "YOUR_HUGGING_FACE_TOKEN" 

# Switched to the much smaller and more manageable 8 Billion parameter model
model_id = "meta-llama/Meta-Llama-3.1-8B-Instruct"

# The 'token' argument is used to authenticate with Hugging Face Hub
pipeline = transformers.pipeline(
    "text-generation", 
    model=model_id, 
    model_kwargs={"torch_dtype": torch.bfloat16}, 
    device_map="auto",
    token=hugging_face_token
)

# You'll need to accept the terms for this model on its Hugging Face page too.
# The prompt is now structured for an instruct model.
messages = [
    {"role": "system", "content": "You are a friendly chatbot."},
    {"role": "user", "content": "Hey how are you doing today?"},
]

# The pipeline's __call__ method handles the tokenization and generation
try:
    # Use a high max_length to avoid cutting off the response
    outputs = pipeline(messages, max_new_tokens=256)
    print(outputs[0]["generated_text"][-1]) # Print just the assistant's response
except Exception as e:
    print(f"An error occurred: {e}")