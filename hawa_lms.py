# Full tutorial
# 1. Download and install LM Studio from https://lmstudio.ai/download
# 2. Run LM Studio GUI and Download a specific model, or either run in terminal $lms get qwen/qwen3-4b-2507
# 3. Install LM Studio Python SDK with $pip install lmstudio
# 4. Check this tutorial for further knowledge on the LMS python SDK https://lmstudio.ai/docs/python and run this script

## Overall Usage (streaming responses on the go)
# python hawa_lms.py --mode sync_stream -q "What is AI?"
# Hide reasoning for models with reasoning (only wait and show final answer)
# python hawa_lms.py --mode sync_stream -q "What is AI?" --no-reasoning

## With system prompts (context/system instructions)
#python hawa_lms.py --mode sync_stream --system-prompt "You are a helpful assistant. Answer concisely." -q "What is AI?"

## Completion mode (Text to complete)
#python hawa_lms.py --mode complete -p "Once upon a time,"

## Default conversation (History)
#python hawa_lms.py --mode history
# Custom conversation history
#python hawa_lms.py --mode history --history "Hello" "Welcome!" "Do you sell apples?" "No, only eels"

## Prompt mode (Question-Response)
# Async (default)
#python hawa_lms.py -q "What is AI?"
# Sync
#python hawa_lms.py --mode sync -q "What is AI?"
# Convenience
#python hawa_lms.py --mode last -q "What is AI?"
# Specific model
#python hawa_lms.py -m qwen/qwen3-4b-2507 -q "Hello"

## Files Usage
# Ask a question about a text file
#python hawa_lms.py --mode file -f document.txt -q "Summarize this document"
# Use a text file as context for a question
#python hawa_lms.py --mode file -f notes.txt -q "What are the main points?"

## Images Usage
# Prepare an image for use with multimodal models
#python hawa_lms.py --mode prepare_image -i /path/to/your/image.jpg
# Prepare image with specific model
#python hawa_lms.py --mode prepare_image -i photo.png -m qwen/qwen3-4b-2507
# List all models first to see what's available
#python hawa_lms.py --list

## Inference Parametization
# Control creativity with temperature
#python hawa_lms.py --mode sync -q "Write a poem" --temperature 0.9
# Limit response length
#python hawa_lms.py --mode sync_stream -q "Explain quantum physics" --max-tokens 200
# Use top-p sampling
#python hawa_lms.py --mode sync -q "Tell a joke" --top-p 0.9
# Combine multiple parameters
#python hawa_lms.py --mode sync_stream -q "Write a story" --temperature 0.8 --max-tokens 500 --top-p 0.95
# Reproducible results with seed
#python hawa_lms.py --mode sync -q "Hello" --seed 42
# Stop sequences
#python hawa_lms.py --mode complete -p "The recipe is" --stop "The" "and"

## Load parameters
# Set context length
#python hawa_lms.py --mode sync -q "Long document" --context-length 8192
# GPU offload ratio
#python hawa_lms.py --mode sync_stream -q "Explain AI" --gpu-offload 0.5
# Cache type
#python hawa_lms.py --mode sync -q "Hello" --cache-type f16
# Combine load parameters
#python hawa_lms.py --mode sync -m deepseek/deepseek-r1-0528-qwen3-8b --context-length 4096 --gpu-offload 0.8 --cache-type q4_0

import lmstudio as lms
import sys
import asyncio
import argparse
from typing import Optional, List, Tuple
from pathlib import Path

class LMChat:
    """LM Studio chat handler"""
    
    def __init__(self, model_key: Optional[str] = None, load_config: Optional[dict] = None):
        self.model_key = model_key
        self.load_config = load_config
    
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
        """Get model instance with load configuration"""
        model_key = self.model_key or self.get_last_model()
        print(f"Loading model: {model_key}")
        
        # Load with configuration if provided
        if self.load_config:
            print(f"Load config: {self.load_config}")
            return lms.llm(model_key, config=self.load_config)
        return lms.llm(model_key)
    
    def read_text_file(self, file_path: str) -> str:
        """Read a text file and return its contents"""
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Text file not found: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"Loaded text file: {file_path} ({len(content)} characters)")
        return content
    
    def complete(self, prompt: str, predict_config: Optional[dict] = None) -> str:
        """Simple completion (non-streaming)"""
        model = self.get_model()
        print(f"Prompt: {prompt}")
        print("Thinking...")
        if predict_config:
            print(f"Prediction config: {predict_config}")
        result = model.complete(prompt, config=predict_config)
        return result
    
    def stream_complete(self, prompt: str, predict_config: Optional[dict] = None) -> None:
        """Stream a completion in real-time"""
        model = self.get_model()
        print(f"Prompt: {prompt}")
        print("Response: ", end="", flush=True)
        
        for fragment in model.complete_stream(prompt, config=predict_config):
            print(fragment, end="", flush=True)
        
        print("\n")  # New line after completion
    
    def sync_chat(self, question: str, system_prompt: Optional[str] = None, predict_config: Optional[dict] = None) -> str:
        """Synchronous chat with the model (non-streaming)"""
        with lms.Client() as client:
            model_key = self.model_key or self.get_last_model()
            print(f"Loading model: {model_key}")
            if self.load_config:
                print(f"Load config: {self.load_config}")
            model = client.llm.model(model_key, config=self.load_config)
            print(f"Question: {question}")
            
            # Create chat with system prompt if provided
            if system_prompt:
                print(f"System prompt: {system_prompt}")
                chat = lms.Chat(system_prompt)
            else:
                chat = lms.Chat()
            
            chat.add_user_message(question)
            print("Thinking...")
            if predict_config:
                print(f"Prediction config: {predict_config}")
            result = model.respond(chat, config=predict_config)
            return result
    
    def sync_stream_chat(self, question: str, show_reasoning: bool = True, system_prompt: Optional[str] = None, predict_config: Optional[dict] = None) -> None:
        """Synchronous chat with streaming response - handles DeepSeek reasoning properly"""
        with lms.Client() as client:
            model_key = self.model_key or self.get_last_model()
            print(f"Loading model: {model_key}")
            if self.load_config:
                print(f"Load config: {self.load_config}")
            model = client.llm.model(model_key, config=self.load_config)
            print(f"Question: {question}")
            
            # Create chat with system prompt if provided
            if system_prompt:
                print(f"System prompt: {system_prompt}")
                chat = lms.Chat(system_prompt)
            else:
                chat = lms.Chat()
            
            chat.add_user_message(question)
            
            if predict_config:
                print(f"Prediction config: {predict_config}")
            
            # Track state for handling reasoning
            in_reasoning = False
            is_first_content = True
            
            for fragment in model.respond_stream(chat, config=predict_config):
                # If fragment is a string or has content attribute
                if isinstance(fragment, str):
                    content = fragment
                elif hasattr(fragment, 'content'):
                    content = fragment.content
                else:
                    content = str(fragment)
                
                # Check if this is a reasoning fragment (DeepSeek uses reasoning_type)
                is_reasoning_fragment = (
                    hasattr(fragment, 'reasoning_type') and 
                    fragment.reasoning_type
                )
                
                # Handle reasoning content
                if is_reasoning_fragment or (isinstance(content, str) and '<think>' in content):
                    if not show_reasoning:
                        # Skip reasoning entirely
                        if '<think>' in content:
                            in_reasoning = True
                        elif '</think>' in content:
                            in_reasoning = False
                        continue
                    
                    # Show reasoning
                    if not in_reasoning and '<think>' in content:
                        print("\n[Reasoning]: ", end="", flush=True)
                        in_reasoning = True
                        content = content.replace('<think>', '')
                    
                    if '</think>' in content:
                        in_reasoning = False
                        content = content.replace('</think>', '')
                        if content:
                            print(content, end="", flush=True)
                        print("\n\n[Answer]: ", end="", flush=True)
                        continue
                    
                    if in_reasoning:
                        print(content, end="", flush=True)
                        continue
                
                # This is final answer content
                if is_first_content and not show_reasoning:
                    print("[Answer]: ", end="", flush=True)
                    is_first_content = False
                
                print(content, end="", flush=True)
            
            print("\n")  # New line after response
    
    async def async_chat(self, question: str, system_prompt: Optional[str] = None, predict_config: Optional[dict] = None) -> str:
        """Asynchronous chat with the model (non-streaming)"""
        async with lms.AsyncClient() as client:
            model_key = self.model_key or self.get_last_model()
            print(f"Loading model: {model_key}")
            if self.load_config:
                print(f"Load config: {self.load_config}")
            model = await client.llm.model(model_key, config=self.load_config)
            print(f"Question: {question}")
            
            # Create chat with system prompt if provided
            if system_prompt:
                print(f"System prompt: {system_prompt}")
                chat = lms.Chat(system_prompt)
            else:
                chat = lms.Chat()
            
            chat.add_user_message(question)
            print("Thinking...")
            if predict_config:
                print(f"Prediction config: {predict_config}")
            result = await model.respond(chat, config=predict_config)
            return result
    
    async def async_stream_chat(self, question: str, show_reasoning: bool = True, system_prompt: Optional[str] = None, predict_config: Optional[dict] = None) -> None:
        """Asynchronous chat with streaming response - handles DeepSeek reasoning properly"""
        async with lms.AsyncClient() as client:
            model_key = self.model_key or self.get_last_model()
            print(f"Loading model: {model_key}")
            if self.load_config:
                print(f"Load config: {self.load_config}")
            model = await client.llm.model(model_key, config=self.load_config)
            print(f"Question: {question}")
            
            # Create chat with system prompt if provided
            if system_prompt:
                print(f"System prompt: {system_prompt}")
                chat = lms.Chat(system_prompt)
            else:
                chat = lms.Chat()
            
            chat.add_user_message(question)
            
            if predict_config:
                print(f"Prediction config: {predict_config}")
            
            # Track state for handling reasoning
            in_reasoning = False
            is_first_content = True
            
            async for fragment in model.respond_stream(chat, config=predict_config):
                # If fragment is a string or has content attribute
                if isinstance(fragment, str):
                    content = fragment
                elif hasattr(fragment, 'content'):
                    content = fragment.content
                else:
                    content = str(fragment)
                
                # Check if this is a reasoning fragment (DeepSeek uses reasoning_type)
                is_reasoning_fragment = (
                    hasattr(fragment, 'reasoning_type') and 
                    fragment.reasoning_type
                )
                
                # Handle reasoning content
                if is_reasoning_fragment or (isinstance(content, str) and '<think>' in content):
                    if not show_reasoning:
                        # Skip reasoning entirely
                        if '<think>' in content:
                            in_reasoning = True
                        elif '</think>' in content:
                            in_reasoning = False
                        continue
                    
                    # Show reasoning
                    if not in_reasoning and '<think>' in content:
                        print("\n[Reasoning]: ", end="", flush=True)
                        in_reasoning = True
                        content = content.replace('<think>', '')
                    
                    if '</think>' in content:
                        in_reasoning = False
                        content = content.replace('</think>', '')
                        if content:
                            print(content, end="", flush=True)
                        print("\n\n[Answer]: ", end="", flush=True)
                        continue
                    
                    if in_reasoning:
                        print(content, end="", flush=True)
                        continue
                
                # This is final answer content
                if is_first_content and not show_reasoning:
                    print("[Answer]: ", end="", flush=True)
                    is_first_content = False
                
                print(content, end="", flush=True)
            
            print("\n")  # New line after response
    
    def convenience_chat(self, question: str, system_prompt: Optional[str] = None, predict_config: Optional[dict] = None) -> str:
        """Convenience method using lms.llm() (non-streaming)"""
        model = self.get_model()
        print(f"Question: {question}")
        
        # Create chat with system prompt if provided
        if system_prompt:
            print(f"System prompt: {system_prompt}")
            chat = lms.Chat(system_prompt)
        else:
            chat = lms.Chat()
        
        chat.add_user_message(question)
        print("Thinking...")
        if predict_config:
            print(f"Prediction config: {predict_config}")
        result = model.respond(chat, config=predict_config)
        return result
    
    def convenience_stream_chat(self, question: str, show_reasoning: bool = True, system_prompt: Optional[str] = None, predict_config: Optional[dict] = None) -> None:
        """Convenience method with streaming - handles DeepSeek reasoning properly"""
        model = self.get_model()
        print(f"Question: {question}")
        
        # Create chat with system prompt if provided
        if system_prompt:
            print(f"System prompt: {system_prompt}")
            chat = lms.Chat(system_prompt)
        else:
            chat = lms.Chat()
        
        chat.add_user_message(question)
        
        if predict_config:
            print(f"Prediction config: {predict_config}")
        
        # Track state for handling reasoning
        in_reasoning = False
        is_first_content = True
        
        for fragment in model.respond_stream(chat, config=predict_config):
            # If fragment is a string or has content attribute
            if isinstance(fragment, str):
                content = fragment
            elif hasattr(fragment, 'content'):
                content = fragment.content
            else:
                content = str(fragment)
            
            # Check if this is a reasoning fragment (DeepSeek uses reasoning_type)
            is_reasoning_fragment = (
                hasattr(fragment, 'reasoning_type') and 
                fragment.reasoning_type
            )
            
            # Handle reasoning content
            if is_reasoning_fragment or (isinstance(content, str) and '<think>' in content):
                if not show_reasoning:
                    # Skip reasoning entirely
                    if '<think>' in content:
                        in_reasoning = True
                    elif '</think>' in content:
                        in_reasoning = False
                    continue
                
                # Show reasoning
                if not in_reasoning and '<think>' in content:
                    print("\n[Reasoning]: ", end="", flush=True)
                    in_reasoning = True
                    content = content.replace('<think>', '')
                
                if '</think>' in content:
                    in_reasoning = False
                    content = content.replace('</think>', '')
                    if content:
                        print(content, end="", flush=True)
                    print("\n\n[Answer]: ", end="", flush=True)
                    continue
                
                if in_reasoning:
                    print(content, end="", flush=True)
                    continue
            
            # This is final answer content
            if is_first_content and not show_reasoning:
                print("[Answer]: ", end="", flush=True)
                is_first_content = False
            
            print(content, end="", flush=True)
        
        print("\n")
    
    def chat_with_history(self, messages: List[Tuple[str, str]], system_prompt: Optional[str] = None) -> str:
        """Chat with conversation history"""
        model = self.get_model()
        
        # Initialize chat with system prompt if provided
        if system_prompt:
            print(f"System prompt: {system_prompt}")
            chat = lms.Chat(system_prompt)
        else:
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
    
    def chat_with_file(self, file_path: str, question: str, system_prompt: Optional[str] = None, predict_config: Optional[dict] = None) -> str:
        """Chat about a text file's contents"""
        content = self.read_text_file(file_path)
        prompt = f"Here is the content of a file:\n\n{content}\n\nQuestion: {question}"
        return self.convenience_chat(prompt, system_prompt, predict_config)
    
    def stream_chat_with_file(self, file_path: str, question: str, show_reasoning: bool = True, system_prompt: Optional[str] = None, predict_config: Optional[dict] = None) -> None:
        """Chat about a text file's contents with streaming"""
        content = self.read_text_file(file_path)
        prompt = f"Here is the content of a file:\n\n{content}\n\nQuestion: {question}"
        self.convenience_stream_chat(prompt, show_reasoning, system_prompt, predict_config)

def build_prediction_config(args):
    """Build inference configuration from command line arguments"""
    config = {}
    if args.temperature is not None:
        config["temperature"] = args.temperature
    if args.max_tokens is not None:
        config["maxTokens"] = args.max_tokens
    if args.top_p is not None:
        config["topP"] = args.top_p
    if args.top_k is not None:
        config["topK"] = args.top_k
    if args.repeat_penalty is not None:
        config["repeatPenalty"] = args.repeat_penalty
    if args.seed is not None:
        config["seed"] = args.seed
    if args.stop is not None:
        config["stop"] = args.stop
    return config if config else None

def build_load_config(args):
    """Build load configuration from command line arguments"""
    config = {}
    if args.context_length is not None:
        config["contextLength"] = args.context_length
    if args.gpu_offload is not None:
        config["gpuOffloadRatio"] = args.gpu_offload
    if args.cache_type is not None:
        config["cacheType"] = args.cache_type
    return config if config else None

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Chat with LM Studio models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic chat with default settings
  python hawa_lms.py --mode sync -q "What is AI?"
  
  # Chat with system prompt
  python hawa_lms.py --mode sync --system-prompt "You are a helpful assistant. Answer concisely." -q "What is AI?"
  
  # Chat with temperature and token limit
  python hawa_lms.py --mode sync_stream -q "Tell a story" --temperature 0.8 --max-tokens 300
  
  # Stream with reasoning hidden
  python hawa_lms.py --mode sync_stream -q "Explain quantum physics" --no-reasoning
  
  # Use specific model with load config
  python hawa_lms.py --mode sync -m deepseek/deepseek-r1-0528-qwen3-8b --context-length 4096 --gpu-offload 0.8
  
  # Complete with top-p and seed
  python hawa_lms.py --mode complete -p "Once upon a time" --top-p 0.9 --seed 42
  
  # Chat with file
  python hawa_lms.py --mode file -f document.txt -q "Summarize this" --temperature 0.5
  
  # Full configuration example
  python hawa_lms.py --mode sync_stream -q "Explain AI" --system-prompt "You are a coding expert." --temperature 0.7 --max-tokens 500 --top-p 0.95 --repeat-penalty 1.1 --context-length 8192 --gpu-offload 0.5
        """
    )
    
    # Model selection
    parser.add_argument(
        "-m", "--model",
        type=str,
        help="Model key to use (e.g., 'qwen/qwen3-4b-2507', 'deepseek/deepseek-r1-0528-qwen3-8b')"
    )
    
    # Question/Prompt
    parser.add_argument(
        "-q", "--question",
        type=str,
        default="What is the meaning of life?",
        help="Question to ask the model"
    )
    
    # Mode
    parser.add_argument(
        "--mode",
        choices=["async", "sync", "last", "complete", "history", "prepare_image", "file",
                 "async_stream", "sync_stream", "last_stream", "complete_stream", "file_stream"],
        default="sync",
        help="Mode of operation"
    )
    
    # List models
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List all downloaded models and exit"
    )
    
    # Prompt for completion
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        help="Prompt for completion mode"
    )
    
    # System prompt
    parser.add_argument(
        "-s", "--system-prompt",
        type=str,
        default=None,
        help="System prompt to set the model's behavior, tone, or rules (e.g., 'You are a helpful assistant.')"
    )
    
    # History
    parser.add_argument(
        "--history",
        nargs="*",
        help="Chat history as alternating user/assistant messages"
    )
    
    # Image
    parser.add_argument(
        "-i", "--image",
        type=str,
        help="Path to image file for prepare_image mode"
    )
    
    # File
    parser.add_argument(
        "-f", "--file",
        type=str,
        help="Path to text file for file mode"
    )
    
    # Reasoning
    parser.add_argument(
        "--no-reasoning",
        action="store_true",
        help="Disable displaying reasoning/thinking process (only show final answer)"
    )
    
    # Inference parameters
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Temperature for prediction (0.0 to 2.0). Higher = more random."
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Maximum number of tokens to generate."
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=None,
        help="Top-p sampling parameter (0.0 to 1.0)."
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Top-k sampling parameter."
    )
    parser.add_argument(
        "--repeat-penalty",
        type=float,
        default=None,
        help="Repeat penalty (1.0 = no penalty, >1.0 discourages repetition)."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible results."
    )
    parser.add_argument(
        "--stop",
        type=str,
        nargs='+',
        default=None,
        help="Stop sequences (strings) to halt generation."
    )
    
    # Load parameters
    parser.add_argument(
        "--context-length",
        type=int,
        default=None,
        help="Context length for the model (e.g., 4096, 8192)."
    )
    parser.add_argument(
        "--gpu-offload",
        type=float,
        default=None,
        help="GPU offload ratio (0.0 to 1.0)."
    )
    parser.add_argument(
        "--cache-type",
        type=str,
        choices=["auto", "f16", "q4_0", "q4_1", "q5_0", "q5_1", "q8_0"],
        default=None,
        help="Cache type for the model."
    )
    
    return parser.parse_args()

def run():
    """Main entry point"""
    args = parse_args()
    
    # Build configurations
    predict_config = build_prediction_config(args)
    load_config = build_load_config(args)
    system_prompt = args.system_prompt
    
    chat = LMChat(model_key=args.model, load_config=load_config)
    
    if args.list:
        chat.list_models()
        return
    
    try:
        # Handle streaming modes
        if args.mode == "async_stream":
            print("\nRunning in ASYNC STREAM mode")
            asyncio.run(chat.async_stream_chat(
                args.question, 
                show_reasoning=not args.no_reasoning,
                system_prompt=system_prompt,
                predict_config=predict_config
            ))
            return
            
        elif args.mode == "sync_stream":
            print("\nRunning in SYNC STREAM mode")
            chat.sync_stream_chat(
                args.question, 
                show_reasoning=not args.no_reasoning,
                system_prompt=system_prompt,
                predict_config=predict_config
            )
            return
            
        elif args.mode == "last_stream":
            print("\nRunning in CONVENIENCE STREAM mode")
            chat.convenience_stream_chat(
                args.question, 
                show_reasoning=not args.no_reasoning,
                system_prompt=system_prompt,
                predict_config=predict_config
            )
            return
            
        elif args.mode == "complete_stream":
            print("\nRunning in COMPLETION STREAM mode")
            prompt = args.prompt or "Once upon a time,"
            chat.stream_complete(prompt, predict_config=predict_config)
            return
            
        elif args.mode == "file_stream":
            print("\nRunning in FILE STREAM mode")
            if not args.file:
                raise ValueError("Please provide a text file path using -f/--file")
            if not args.question:
                raise ValueError("Please provide a question using -q/--question")
            chat.stream_chat_with_file(
                args.file, 
                args.question, 
                show_reasoning=not args.no_reasoning,
                system_prompt=system_prompt,
                predict_config=predict_config
            )
            return
        
        # Handle non-streaming modes
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
            result = chat.chat_with_file(
                args.file, 
                args.question, 
                system_prompt=system_prompt,
                predict_config=predict_config
            )
            print("\n" + "="*50)
            print("Response:")
            print("="*50)
            print(result)
            print("="*50)
            
        elif args.mode == "complete":
            print("\nRunning in COMPLETION mode")
            prompt = args.prompt or "Once upon a time,"
            result = chat.complete(prompt, predict_config=predict_config)
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
            result = chat.chat_with_history(messages, system_prompt=system_prompt)
            
        elif args.mode == "async":
            print("\nRunning in ASYNC mode")
            result = asyncio.run(chat.async_chat(
                args.question,
                system_prompt=system_prompt,
                predict_config=predict_config
            ))
            print("\n" + "="*50)
            print("Response:")
            print("="*50)
            print(result)
            print("="*50)
            
        elif args.mode == "sync":
            print("\nRunning in SYNC mode")
            result = chat.sync_chat(
                args.question,
                system_prompt=system_prompt,
                predict_config=predict_config
            )
            print("\n" + "="*50)
            print("Response:")
            print("="*50)
            print(result)
            print("="*50)
            
        elif args.mode == "last":
            print("\nRunning in CONVENIENCE mode")
            result = chat.convenience_chat(
                args.question,
                system_prompt=system_prompt,
                predict_config=predict_config
            )
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