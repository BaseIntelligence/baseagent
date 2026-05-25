# AGENTS.md - Building a High-Performance Autonomous Agent

This file provides instructions for AI agents working on this codebase. It also serves as a comprehensive guide for building autonomous coding agents.

## Quick Start

```bash
# Install dependencies
pip install -e .

# Configure DeepSeek for challenge runs
export DEEPSEEK_API_KEY="your-token"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-v4-pro"

# Run with Term SDK
python agent.py

# Local testing with Term Challenge
git clone https://github.com/PlatformNetwork/term-challenge.git
pip install -e term-challenge/sdk/python/
```

## Challenge API Policy

Challenge API policy: this agent is configured to use only the DeepSeek API for cost reasons. Challenge runs must use DEEPSEEK_API_KEY and the configured DeepSeek model. Do not add or rely on Chutes, OpenRouter, Anthropic, OpenAI, or other provider fallbacks for challenge execution.

## Project Structure

```
baseagent/
├── agent.py           # Entry point for Term SDK
├── src/
│   ├── core/
│   │   ├── loop.py    # Main agent loop (caching, verification)
│   │   └── compaction.py  # Context management
│   ├── tools/         # Tool implementations
│   ├── prompts/
│   │   └── system.py  # Codex-inspired system prompt
│   └── api/
│       └── client.py  # LLM API client
├── rules/             # Agent development guidelines (READ THESE)
└── astuces/           # Practical techniques used here
```

---

# Part 1: Core Principles

## The Golden Rule: NO HARDCODING

Your agent must solve tasks through **reasoning**, not **pattern matching**.

### FORBIDDEN

```python
# NEVER do this
if "file" in ctx.instruction:
    create_file()
elif "compile" in ctx.instruction:
    compile_code()
```

### REQUIRED

```python
# Always let LLM decide
response = llm.chat([
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": f"Task: {ctx.instruction}"}
])
execute(response.tool_calls)
```

## What Makes a Generalist Agent

| Characteristic | Description |
|----------------|-------------|
| Single code path | Same logic for ALL tasks |
| LLM-driven decisions | LLM chooses actions, not if-statements |
| No task keywords | Zero references to specific task content |
| Iterative execution | Observe → Think → Act loop |

## The Test

Ask yourself: **"Would this code behave differently if I changed the task instruction?"**

If YES and it's not because of LLM reasoning → it's hardcoding → FORBIDDEN.

---

# Part 2: Architecture

## The Agent Loop

```python
def run_agent_loop(ctx: AgentContext) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": ctx.instruction}
    ]
    
    while True:
        # 1. Apply caching for cost efficiency
        messages = apply_caching(messages)
        
        # 2. Manage context to prevent overflow
        messages = manage_context(messages, max_tokens=180000)
        
        # 3. Call LLM
        response = ctx.llm.chat(messages, tools=TOOLS)
        
        # 4. Check for completion
        if not response.has_tool_calls():
            # Inject verification before completing
            if not verified:
                messages.append(verification_prompt(ctx.instruction))
                verified = True
                continue
            return response.text
        
        # 5. Execute tools
        for call in response.tool_calls:
            result = execute_tool(call)
            messages.append(tool_result(call.id, result))
    
    return "Task completed"
```

## Essential Patterns

### 1. Explore First
Always gather context before acting:
```python
context = shell("pwd && ls -la")
readme = shell("cat README.md 2>/dev/null")
```

### 2. Iterative Execution
Never try to do everything in one shot:
```python
while not done:
    response = llm.chat(messages)
    result = execute(response)
    messages.append(result)
```

### 3. Double Confirmation
Always verify before completing:
```python
if response.says_complete:
    if not already_verified:
        inject_verification_prompt()
        continue
    return complete()
```

---

# Part 3: Key Techniques

## 1. Prompt Caching (90% Cost Reduction)

Cache the **system prompt + last 2 messages** for massive cache hits.

```python
def apply_caching(messages):
    # Cache system messages (stable)
    for msg in messages:
        if msg["role"] == "system":
            add_cache_control(msg)
    
    # Cache last 2 non-system messages (extends prefix)
    non_system = [m for m in messages if m["role"] != "system"]
    for msg in non_system[-2:]:
        add_cache_control(msg)
    
    return messages
```

**Why it works**: provider prompt caches use matching prefixes. Caching the last messages extends the cached prefix to include the entire conversation history.

## 2. Self-Verification

Before completing, force the agent to verify its work:

```python
VERIFICATION_PROMPT = f"""
STOP - Before completing, verify your work:

Original instruction: {ctx.instruction}

Checklist:
1. Re-read the instruction above
2. List ALL requirements (explicit and implicit)
3. Run commands to verify each requirement
4. Only complete after ALL verifications pass

You are in headless mode - do NOT ask questions.
"""
```

## 3. Context Management

Prevent token overflow with pruning and compaction:

```python
def manage_context(messages, max_tokens):
    current = estimate_tokens(messages)
    
    # Stage 1: Prune old tool outputs
    if current > max_tokens * 0.70:
        messages = prune_tool_outputs(messages, keep_last=5)
    
    # Stage 2: AI compaction
    if current > max_tokens * 0.85:
        messages = compact_with_llm(messages)
    
    return messages
```

## 4. Middle-Out Truncation

For large tool outputs, keep start AND end:

```python
def truncate(text, max_bytes=50000):
    if len(text) <= max_bytes:
        return text
    
    keep = max_bytes // 2 - 50
    return f"{text[:keep]}\n\n[...truncated...]\n\n{text[-keep:]}"
```

**Why**: Start has headers, end has results/errors, middle is often repetitive.

## 5. Autonomous Mode

The agent must NEVER ask questions in headless mode:

```python
# In system prompt:
"""
You are fully autonomous:
- Do NOT ask questions - make reasonable decisions
- Do NOT wait for confirmation - just execute
- If something fails, try alternative approaches
- Only complete after verifying your work
"""
```

---

# Part 4: System Prompt Design

Based on Codex CLI, include these sections:

## Identity
```
You are a coding agent running in [AgentName], an autonomous terminal-based assistant.
```

## AGENTS.md Support
```
Repos may contain AGENTS.md files with instructions. Obey them.
```

## Preamble Messages
```
Before tool calls, send a brief preamble (8-12 words):
"Exploring the repo structure, then checking the API routes."
```

## Git Hygiene
```
- NEVER revert changes you didn't make
- NEVER use git reset --hard or git checkout --
- Do not commit unless explicitly asked
```

## Task Execution
```
Keep going until the task is COMPLETELY resolved.
- Make decisions autonomously
- Fix problems at root cause
- Validate your work before completing
```

## Output Formatting
```
- Be concise (10 lines max for simple tasks)
- Use backticks for code/paths
- Reference files as: src/file.py:42
```

---

# Part 5: Tools

## Essential Tools

| Tool | Purpose |
|------|---------|
| `shell_command` | Execute shell commands |
| `read_file` | Read files with line numbers |
| `write_file` | Create/overwrite files |
| `apply_patch` | Modify files surgically |
| `grep_files` | Search file contents (ripgrep) |
| `list_dir` | List directory contents |

## Tool Output Limits

```python
MAX_OUTPUT_BYTES = 50000  # 50KB per tool
MAX_OUTPUT_LINES = 500
```

Always truncate before adding to context.

---

# Part 6: What NOT To Do

## Forbidden Patterns

| Pattern | Why Forbidden |
|---------|---------------|
| `if "keyword" in instruction` | Task-specific routing |
| `handlers[task_type]()` | Pre-defined handlers |
| `SOLUTIONS[task_hash]` | Cached solutions |
| `re.match(task_pattern)` | Regex task matching |
| Reading test files | Cheating |

## Common Mistakes

1. **Not exploring first** - Always gather context
2. **One-shot execution** - Use iterative loop
3. **No verification** - Always verify before completing
4. **Unbounded context** - Truncate and prune
5. **Asking questions** - Make decisions autonomously

---

# Part 7: Testing

## Local Testing

```python
from unittest.mock import MagicMock
from src.core.loop import run_agent_loop

ctx = MagicMock()
ctx.instruction = "Create hello.txt with 'Hello World'"
ctx.cwd = "/tmp/test"
ctx.llm = YourLLM()

result = run_agent_loop(ctx)
```

## With Term Challenge

```bash
git clone https://github.com/PlatformNetwork/term-challenge.git
cd term-challenge
pip install -e sdk/python/

# Run benchmark
python -m term_bench run --agent /path/to/baseagent --task tasks/test.yaml
```

---

# Part 8: Checklist

Before submitting your agent:

- [ ] No keyword matching on instructions
- [ ] No task-specific handlers
- [ ] No pre-computed solutions
- [ ] Prompt caching enabled (system + last 2 messages)
- [ ] Self-verification before completion
- [ ] Context management (prune + compact)
- [ ] Tool output truncation
- [ ] Autonomous mode (no questions)
- [ ] Git hygiene rules in system prompt
- [ ] Explore-first pattern implemented

---

# Documentation

## Rules (Theory)
See `rules/` folder for comprehensive guidelines:
- What is a generalist agent
- Architecture patterns
- Allowed vs forbidden behaviors
- Anti-patterns to avoid
- Best practices

## Astuces (Practice)
See `astuces/` folder for implementation details:
- Prompt caching technique
- Self-verification system
- Context management
- System prompt design
- Tool output handling
- Cost optimization

---

# Summary

Building a high-performance autonomous agent requires:

1. **No hardcoding** - LLM decides everything
2. **Prompt caching** - 90% cost reduction
3. **Self-verification** - Validate before completing
4. **Context management** - Prevent overflow
5. **Autonomous execution** - No questions, just execute

The goal is an agent that **thinks**, not one that **pattern matches**.
