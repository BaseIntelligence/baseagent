# 06 - LLM Usage Guide (SDK 3.0 - LLM Gateway)

This guide covers using LLMs with the **platform LLM gateway** via httpx (no more term_sdk). Challenge runs call the gateway at `BASE_LLM_GATEWAY_URL` using `BASE_GATEWAY_TOKEN`; the platform chooses the provider and model. Miners MUST NOT embed provider API keys, base URLs, or model names, and MUST NOT call any LLM provider directly. Set `BASEAGENT_MOCK_LLM=1` to run without a gateway URL or token (mock mode).

---

## Basic LLM Interaction

### Initialization

```python
from src.llm.client import LLMClient, LLMError, CostLimitExceeded

# Create the LLM client (reads BASE_LLM_GATEWAY_URL / BASE_GATEWAY_TOKEN from env)
llm = LLMClient(
    base_url="https://<gateway-host>/llm/v1",
    token="<gateway-token>",
    temperature=0.0,  # 0 = deterministic
    max_tokens=16384,
    cost_limit=10.0   # Cost limit in $
)
```

The client does not take a required model: its default placeholder model is `"gateway-default"` and the gateway injects the real provider and model.

### Conversations (MANDATORY: keep history)

```python
# ALWAYS maintain full history
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What files are in /etc?"},
]

response = llm.chat(messages)
print(response.text)

# Add response to history
messages.append({"role": "assistant", "content": response.text})
messages.append({"role": "user", "content": "Which ones are for networking?"})

response = self.llm.chat(messages)
```

---

## Effective System Prompts

### Basic Structure

```python
SYSTEM_PROMPT = """You are a task-solving agent operating in a Linux terminal.

YOUR CAPABILITIES:
- Execute shell commands
- Read and write files
- Analyze output and errors

YOUR CONSTRAINTS:
- Only use standard Linux tools
- Do not access the internet
- Do not modify system files

RESPONSE FORMAT:
Respond with valid JSON:
{
    "thinking": "your reasoning",
    "command": "shell command to run",
    "task_complete": false
}
"""
```

### Do's and Don'ts

**Do:**
- Be specific about response format
- List available tools/capabilities
- Define constraints clearly
- Give examples of expected output format

**Don't:**
- Include task-specific hints
- Pre-define solutions for task types
- Give examples of specific task solutions
- Mention benchmark or evaluation

### Format-Focused Prompt

```python
SYSTEM_PROMPT = """You are a terminal agent. Respond ONLY with valid JSON.

Required format:
{
    "analysis": "Brief analysis of current state",
    "plan": "What you will do next",
    "commands": [
        {"keystrokes": "command here", "duration": 1.0}
    ],
    "task_complete": false
}

Rules:
1. "analysis" and "plan" are required strings
2. "commands" is an array (can be empty)
3. "task_complete" defaults to false
4. Use proper JSON escaping
5. No markdown, no explanations outside JSON
"""
```

---

## Response Parsing

### Robust JSON Parser

```python
import json
import re

class ResponseParser:
    def parse(self, text: str) -> dict | None:
        """Parse JSON from LLM response."""
        
        # Try direct parse first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        # Extract JSON from text
        json_str = self._extract_json(text)
        if not json_str:
            return None
        
        # Try parsing extracted JSON
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        # Try fixing common issues
        fixed = self._fix_json(json_str)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None
    
    def _extract_json(self, text: str) -> str | None:
        """Extract JSON object from text."""
        # Find outermost braces
        start = text.find('{')
        if start == -1:
            return None
        
        depth = 0
        in_string = False
        escape = False
        
        for i, char in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if not in_string:
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:i+1]
        
        return None
    
    def _fix_json(self, json_str: str) -> str:
        """Fix common JSON issues."""
        # Remove trailing commas
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        # Fix single quotes
        # (This is naive - real impl should be smarter)
        
        return json_str
```

### Using the Parser

```python
def run(self, ctx: Any):
    parser = ResponseParser()
    
    response = self.llm.chat(messages)
    data = parser.parse(response.text)
    
    if not data:
        print("Failed to parse response, asking for retry")
        messages.append({"role": "assistant", "content": response.text})
        messages.append({"role": "user", "content": "Invalid JSON. Please respond with valid JSON only."})
        continue
    
    # Use parsed data
    commands = data.get("commands", [])
```

---

## Error Handling

### LLM Errors

```python
from src.llm.client import LLMError, CostLimitExceeded

def call_llm_safe(self, messages: list, max_retries: int = 3) -> Response | None:
    """Call LLM with error handling."""
    
    for attempt in range(max_retries):
        try:
            return self.llm.chat(messages)
        
        except CostLimitExceeded as e:
            # Fatal - can't continue
            self.print(f"Cost limit exceeded: ${e.used:.2f}/${e.limit:.2f}")
            return None
        
        except LLMError as e:
            self.print(f"LLM error ({e.code}): {e.message}")
            
            if e.code == "rate_limit":
                # Wait and retry
                wait_time = 30 * (attempt + 1)
                self.print(f"Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            elif e.code == "context_length":
                # Reduce context and retry
                self.print("Context too long, truncating...")
                messages = self._truncate_messages(messages)
                continue
            
            elif e.code in ("server_error", "service_unavailable"):
                # Transient, retry
                time.sleep(5 * (attempt + 1))
                continue
            
            else:
                # Unknown error
                if attempt == max_retries - 1:
                    return None
    
    return None
```

### Parse Errors

```python
def get_valid_response(self, ctx, messages: list, max_attempts: int = 3) -> dict | None:
    """Get a valid parsed response from LLM."""
    
    for attempt in range(max_attempts):
        response = self.call_llm_safe(messages)
        if not response:
            return None
        
        data = self.parser.parse(response.text)
        if data:
            return data
        
        # Ask for valid JSON
        print(f"Parse failed (attempt {attempt + 1})")
        messages.append({"role": "assistant", "content": response.text})
        messages.append({
            "role": "user",
            "content": "Your response was not valid JSON. Please respond with ONLY valid JSON, no other text."
        })
    
    return None
```

---

## Context Management

### Token Estimation

```python
def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token)."""
    return len(text) // 4

class ContextManager:
    def __init__(self, max_tokens: int = 50000):
        self.max_tokens = max_tokens
        self.messages = []
    
    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        self._enforce_limit()
    
    def _enforce_limit(self):
        total = sum(estimate_tokens(m["content"]) for m in self.messages)
        
        while total > self.max_tokens and len(self.messages) > 2:
            # Keep first (system) and remove oldest user/assistant
            removed = self.messages.pop(1)
            total -= estimate_tokens(removed["content"])
    
    def get_messages(self) -> list:
        return self.messages.copy()
```

### Sliding Window

```python
def run(self, ctx: Any):
    # Keep only last N exchanges
    MAX_HISTORY = 10
    
    system_msg = {"role": "system", "content": SYSTEM_PROMPT}
    history = []
    
    while True:
        # Build messages with sliding window
        messages = [system_msg] + history[-MAX_HISTORY * 2:]
        
        response = self.llm.chat(messages)
        history.append({"role": "assistant", "content": response.text})
        
        # ... execute ...
        
        history.append({"role": "user", "content": output})
```

---

## Function Calling

### Defining Tools

```python
# Tool format (OpenAI-compatible)

TOOLS = [
    Tool(
        name="execute_command",
        description="Run a shell command and return the output",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                    "default": 30
                }
            },
            "required": ["command"]
        }
    ),
    Tool(
        name="read_file",
        description="Read the contents of a file",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read"
                }
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="write_file",
        description="Write content to a file",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["path", "content"]
        }
    ),
    Tool(
        name="task_complete",
        description="Mark the task as complete",
        parameters={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of what was accomplished"
                }
            },
            "required": ["summary"]
        }
    )
]
```

### Implementing Tool Handlers

```python
class ToolHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.completed = False
    
    def execute_command(self, command: str, timeout: int = 30) -> str:
        result = self.shell(command, timeout=timeout)
        output = result.output[-5000:]  # Truncate
        
        if result.timed_out:
            return f"[TIMEOUT after {timeout}s]\n{output}"
        
        status = "success" if result.ok else f"failed (exit {result.exit_code})"
        return f"[{status}]\n{output}"
    
    def read_file(self, path: str) -> str:
        result = self.read_file(path)
        if result.ok:
            return result.stdout[:10000]  # Truncate
        return f"Error reading file: {result.stderr}"
    
    def write_file(self, path: str, content: str) -> str:
        result = self.write_file(path, content)
        if result.ok:
            return f"Successfully wrote {len(content)} bytes to {path}"
        return f"Error writing file: {result.stderr}"
    
    def task_complete(self, summary: str) -> str:
        self.completed = True
        return f"Task marked complete: {summary}"
```

### Using Function Calling

```python
def run(self, ctx: Any):
    handler = ToolHandler(ctx)
    
    # Register handlers
    self.llm.register_function("execute_command", handler.execute_command)
    self.llm.register_function("read_file", handler.read_file)
    self.llm.register_function("write_file", handler.write_file)
    self.llm.register_function("task_complete", handler.task_complete)
    
    messages = [
        {"role": "system", "content": "You are a task-solving agent with tools."},
        {"role": "user", "content": f"Task: {ctx.instruction}"}
    ]
    
    # Let LLM call functions automatically
    response = self.llm.chat_with_functions(
        messages,
        TOOLS,
        max_iterations=50
    )
    
    if handler.completed:
        # Task complete
```

---

## Model Selection

### Supported Models

**All foundation models are supported** as long as they meet these criteria:

| Requirement | Allowed | Forbidden |
|-------------|---------|-----------|
| Model origin | Official provider releases | Community fine-tunes |
| Training | Base/instruct versions | Task-specific fine-tuning |
| Weights | Unmodified | Custom merged weights |

### Why No Community Fine-Tunes?

Community fine-tuned models are **forbidden** because they may:

- Be trained on benchmark data (data contamination)
- Have task-specific optimizations that constitute hardcoding
- Produce artificially inflated scores through overfitting

### Model Selection Strategy

```python
def setup(self):
    # Challenge runs go through the platform LLM gateway
    self.llm = LLMClient(
        base_url="https://<gateway-host>/llm/v1",
        token="<gateway-token>",
        temperature=0.3
    )
```

### Single Gateway Strategy

Challenge runs should keep all LLM calls on the platform LLM gateway, which injects the provider and model:

```python
def setup(self):
    self.llm = LLMClient(
        base_url="https://<gateway-host>/llm/v1",
        token="<gateway-token>",
    )

def run(self, ctx: Any):
    plan = self.llm.ask(
        f"Task: {ctx.instruction}\nCreate a plan.",
    )
    
    parsed = self.llm.ask(
        f"Extract commands from:\n{plan.text}",
    )
```

---

---

## Prompt Caching

Prompt caching significantly reduces costs and latency by reusing previously processed prompts.

### Enabling Caching

```python
from src.llm.client import LLMClient

# Caching is handled at the message level
llm = LLMClient(
    base_url="https://<gateway-host>/llm/v1",
    token="<gateway-token>",
)

# The system manages caching automatically through message preparation
```

### How Caching Works

Caching behavior depends on the model and provider. The client handles cache_control markers automatically, stripping them for providers that don't support them.

### What to Cache

**Good candidates for caching:**
- Large system prompts
- Tool definitions
- Reference documentation
- Few-shot examples
- Context that stays constant across requests

**Don't cache:**
- Dynamic user input
- Changing context
- Small prompts (under 1024 tokens)

### Inspecting Cache Usage

```python
response = llm.chat(messages)

# Check cache statistics from response tokens
if response.tokens:
    cached_tokens = response.tokens.get("cached", 0)
    print(f"Cached: {cached_tokens} tokens")
```

### Cost Optimization Tips

1. **Keep static content first** - Cache hits require matching prefixes
2. **Batch related requests** - Maximize cache hits within TTL window
3. **Monitor token usage** - Track cached vs uncached tokens

---

## Best Practices Summary

| Practice | Description |
|----------|-------------|
| Structured output | Always request JSON |
| Robust parsing | Handle malformed responses |
| Error handling | Retry transient failures |
| Context management | Bound history size |
| Token awareness | Truncate long outputs |
| Clear prompts | Specific format requirements |
| Tool definitions | Well-documented parameters |
| **Prompt caching** | Use static prompts first for better cache hits |
