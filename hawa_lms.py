import lmstudio as lms
import sys
import asyncio
import argparse
from typing import Optional, List, Tuple
from pathlib import Path

# Full tutorial
# 1. Download and install LM Studio from https://lmstudio.ai/download
# 2. Run LM Studio GUI and Download a specific model, or either run in terminal $lms get qwen/qwen3-4b-2507
# 3. Install LM Studio Python SDK with $pip install lmstudio
# 4. Check this tutorial for further knowledge on the LMS python SDK https://lmstudio.ai/docs/python and run this script

## Usage
# Completion mode (Text to complete)
#python hawa_lms.py --mode complete -p "Once upon a time,"

# Default conversation (History)
#python hawa_lms.py --mode history
# Custom conversation history
#python hawa_lms.py --mode history --history "Hello" "Welcome!" "Do you sell apples?" "No, only eels"

# Prompt mode (Question-Response)

# Async (default)
#python hawa_lms.py -q "What is AI?"
# Sync
#python hawa_lms.py --mode sync -q "What is AI?"
# Convenience
#python hawa_lms.py --mode last -q "What is AI?"
# Specific model
#python hawa_lms.py -m qwen/qwen3-4b-2507 -q "Hello"

# Files Usage

# Ask a question about a text file
#python hawa_lms.py --mode file -f document.txt -q "Summarize this document"
# Use a text file as context for a question
#python hawa_lms.py --mode file -f notes.txt -q "What are the main points?"

# Images Usage
# Prepare an image for use with multimodal models
#python hawa_lms.py --mode prepare_image -i /path/to/your/image.jpg
# Prepare image with specific model
#python hawa_lms.py --mode prepare_image -i photo.png -m qwen/qwen3-4b-2507
# List all models first to see what's available
#python hawa_lms.py --list


class LMChat:
    """LM Studio chat handler"""
    
    def __init__(self, model_key: Optional[str] = None):
        self.model_key = model_key
    
    def list_models(self) -> None:
        """List all downloaded models"""
        print("Downloaded models:")
        downloaded = lms.list_downloaded_models()
        for model in downloaded:
            print(f"  {model}")
        print()
    
    def get_last_model(self) -> str:
        """Get the last downloaded LLM model key"""
        llm_models = lms.list_downloaded_models("llm")
        if not llm_models:
            raise ValueError("No LLM models found. Please download a model first.")
        return llm_models[-1].model_key
    
    def get_model(self):
        """Get model instance"""
        model_key = self.model_key or self.get_last_model()
        print(f"Loading model: {model_key}")
        return lms.llm(model_key)
    
    def read_text_file(self, file_path: str) -> str:
        """Read a text file and return its contents"""
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Text file not found: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"Loaded text file: {file_path} ({len(content)} characters)")
        return content
    
    def complete(self, prompt: str) -> str:
        """Simple completion"""
        model = self.get_model()
        print(f"Prompt: {prompt}")
        print("Thinking...")
        result = model.complete(prompt)
        return result
    
    def sync_chat(self, question: str) -> str:
        """Synchronous chat with the model"""
        with lms.Client() as client:
            model_key = self.model_key or self.get_last_model()
            print(f"Loading model: {model_key}")
            model = client.llm.model(model_key)
            print(f"Question: {question}")
            print("Thinking...")
            result = model.respond(question)
            return result
    
    async def async_chat(self, question: str) -> str:
        """Asynchronous chat with the model"""
        async with lms.AsyncClient() as client:
            model_key = self.model_key or self.get_last_model()
            print(f"Loading model: {model_key}")
            model = await client.llm.model(model_key)
            print(f"Question: {question}")
            print("Thinking...")
            result = await model.respond(question)
            return result
    
    def convenience_chat(self, question: str) -> str:
        """Convenience method using lms.llm()"""
        model = self.get_model()
        print(f"Question: {question}")
        print("Thinking...")
        result = model.respond(question)
        return result
    
    def chat_with_history(self, messages: List[Tuple[str, str]]) -> str:
        """Chat with conversation history"""
        model = self.get_model()
        chat = lms.Chat("You are a helpful shopkeeper assisting a foreign traveller")
        
        for user_msg, assistant_msg in messages:
            chat.add_user_message(user_msg)
            print(f"Customer: {user_msg}")
            response = model.respond(chat)
            chat.add_assistant_response(response)
            print(f"Shopkeeper: {response}")
        
        return "Chat history completed"
    
    def prepare_image(self, image_path: str) -> str:
        """Prepare an image for use in prediction requests"""
        with lms.Client() as client:
            print(f"Preparing image: {image_path}")
            if not Path(image_path).exists():
                raise FileNotFoundError(f"Image file not found: {image_path}")
            
            file_handle = client.prepare_image(image_path)
            print(f"Image prepared successfully. File handle: {file_handle}")
            return str(file_handle)
    
    def chat_with_file(self, file_path: str, question: str) -> str:
        """Chat about a text file's contents"""
        content = self.read_text_file(file_path)
        prompt = f"Here is the content of a file:\n\n{content}\n\nQuestion: {question}"
        return self.convenience_chat(prompt)

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Chat with LM Studio models"
    )
    
    parser.add_argument(
        "-m", "--model",
        type=str,
        help="Model key to use (e.g., 'qwen/qwen3-4b-2507')"
    )
    
    parser.add_argument(
        "-q", "--question",
        type=str,
        default="What is the meaning of life?",
        help="Question to ask the model"
    )
    
    parser.add_argument(
        "--mode",
        choices=["async", "sync", "last", "complete", "history", "prepare_image", "file"],
        default="async",
        help="Mode of operation: async, sync, last (convenience), complete, history, prepare_image, or file"
    )
    
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List all downloaded models and exit"
    )
    
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        help="Prompt for completion mode"
    )
    
    parser.add_argument(
        "--history",
        nargs="*",
        help="Chat history as alternating user/assistant messages (e.g., 'Hello' 'Hi' 'How are you?' 'I am fine')"
    )
    
    parser.add_argument(
        "-i", "--image",
        type=str,
        help="Path to image file for prepare_image mode"
    )
    
    parser.add_argument(
        "-f", "--file",
        type=str,
        help="Path to text file for file mode"
    )
    
    return parser.parse_args()

def run():
    """Main entry point"""
    args = parse_args()
    
    chat = LMChat(model_key=args.model)
    
    if args.list:
        chat.list_models()
        return
    
    try:
        if args.mode == "prepare_image":
            print("\nRunning in PREPARE_IMAGE mode")
            if not args.image:
                raise ValueError("Please provide an image path using -i/--image")
            result = chat.prepare_image(args.image)
            print(f"\nImage prepared. Handle: {result}")
            
        elif args.mode == "file":
            print("\nRunning in FILE mode")
            if not args.file:
                raise ValueError("Please provide a text file path using -f/--file")
            if not args.question:
                raise ValueError("Please provide a question using -q/--question")
            result = chat.chat_with_file(args.file, args.question)
            print("\n" + "="*50)
            print("Response:")
            print("="*50)
            print(result)
            print("="*50)
            
        elif args.mode == "complete":
            print("\nRunning in COMPLETION mode")
            prompt = args.prompt or "Once upon a time,"
            result = chat.complete(prompt)
            print("\n" + "="*50)
            print("Response:")
            print("="*50)
            print(result)
            print("="*50)
            
        elif args.mode == "history":
            print("\nRunning in HISTORY mode")
            if args.history:
                messages = list(zip(args.history[::2], args.history[1::2]))
            else:
                messages = [
                    ("My hovercraft is full of eels!", "I will not buy this record, it is scratched."),
                    ("Do you have any cheese?", "This shop only sells eels and records.")
                ]
            result = chat.chat_with_history(messages)
            
        elif args.mode == "async":
            print("\nRunning in ASYNC mode")
            result = asyncio.run(chat.async_chat(args.question))
            print("\n" + "="*50)
            print("Response:")
            print("="*50)
            print(result)
            print("="*50)
            
        elif args.mode == "sync":
            print("\nRunning in SYNC mode")
            result = chat.sync_chat(args.question)
            print("\n" + "="*50)
            print("Response:")
            print("="*50)
            print(result)
            print("="*50)
            
        elif args.mode == "last":
            print("\nRunning in CONVENIENCE mode")
            result = chat.convenience_chat(args.question)
            print("\n" + "="*50)
            print("Response:")
            print("="*50)
            print(result)
            print("="*50)
        
        sys.stdout.flush()
        
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    run()
