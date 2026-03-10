# Configuration Reference

> **Complete guide to all configuration options in BaseAgent**

## Overview

BaseAgent configuration is centralized in `src/config/defaults.py`. Settings can be customized via environment variables or by modifying the configuration file directly.

---

## Configuration File

The main configuration is stored in the `CONFIG` dictionary:

```python
# src/config/defaults.py
CONFIG = {
    # Model Settings
    "model": "deepseek/deepseek-chat",
    "provider": "chutes",
    "temperature": 0.0,
    "max_tokens": 16384,
    "reasoning_effort": "none",
    
    # Agent Execution
    "max_iterations": 200,
    "max_output_tokens": 2500,
    "shell_timeout": 60,
    
    # Context Management
    "model_context_limit": 200_000,
    "output_token_max": 32_000,
    "auto_compact_threshold": 0.85,
    "prune_protect": 40_000,
    "prune_minimum": 20_000,
    
    # Prompt Caching
    "cache_enabled": True,
    
    # Execution Flags
    "bypass_approvals": True,
    "bypass_sandbox": True,
    "skip_git_check": True,
    "unified_exec": True,
    "json_output": True,
    
    # Completion
    "require_completion_confirmation": False,
}
```

---

## Environment Variables

### LLM Provider Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | `deepseek/deepseek-chat` | Model identifier |
| `LLM_COST_LIMIT` | `10.0` | Maximum cost in USD before aborting |
| `CHUTES_BASE_URL` | `https://api.chutes.ai/v1` | API base URL |

### API Keys

| Variable | Provider | Description |
|----------|----------|-------------|
| `CHUTES_API_KEY` | Chutes AI | API key from chutes.ai |

### Example Setup

```bash
# For Chutes AI (default provider)
export CHUTES_API_KEY="your-key"

# Optional: Specify a different model
export LLM_MODEL="moonshotai/Kimi-K2.5-TEE"
```

---

## Configuration Sections

### Model Settings

```mermaid
graph LR
    subgraph Model["Model Configuration"]
        M1["model<br/>Model identifier"]
        M2["provider<br/>API provider"]
        M3["temperature<br/>Response randomness"]
        M4["max_tokens<br/>Max output tokens"]
        M5["reasoning_effort<br/>Reasoning depth"]
    end
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `model` | `str` | `deepseek/deepseek-chat` | Model identifier |
| `provider` | `str` | `chutes` | LLM provider name |
| `temperature` | `float` | `0.0` | Response randomness (0 = deterministic) |
| `max_tokens` | `int` | `16384` | Maximum tokens in LLM response |
| `reasoning_effort` | `str` | `none` | Reasoning depth: `none`, `minimal`, `low`, `medium`, `high`, `xhigh` |

### Agent Execution Settings

```mermaid
graph LR
    subgraph Execution["Execution Limits"]
        E1["max_iterations<br/>200 iterations"]
        E2["max_output_tokens<br/>2500 tokens"]
        E3["shell_timeout<br/>60 seconds"]
    end
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `max_iterations` | `int` | `200` | Maximum loop iterations before stopping |
| `max_output_tokens` | `int` | `2500` | Max tokens for tool output truncation |
| `shell_timeout` | `int` | `60` | Shell command timeout in seconds |

### Context Management

```mermaid
graph TB
    subgraph Context["Context Window Management"]
        C1["model_context_limit: 200K"]
        C2["output_token_max: 32K"]
        C3["Usable: 168K"]
        C4["auto_compact_threshold: 85%"]
        C5["Trigger: ~143K"]
    end
    
    C1 --> C3
    C2 --> C3
    C3 --> C4
    C4 --> C5
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `model_context_limit` | `int` | `200000` | Total model context window (tokens) |
| `output_token_max` | `int` | `32000` | Tokens reserved for output |
| `auto_compact_threshold` | `float` | `0.85` | Trigger compaction at this % of usable context |
| `prune_protect` | `int` | `40000` | Protect this many tokens of recent tool output |
| `prune_minimum` | `int` | `20000` | Only prune if recovering at least this many tokens |

### Prompt Caching

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `cache_enabled` | `bool` | `True` | Enable Anthropic prompt caching |

> **Note**: Prompt caching requires minimum token thresholds per breakpoint:
> - Claude Opus 4.5 on Bedrock: 4096 tokens
> - Claude Sonnet/other: 1024 tokens

### Execution Flags

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `bypass_approvals` | `bool` | `True` | Skip user approval prompts |
| `bypass_sandbox` | `bool` | `True` | Bypass sandbox restrictions |
| `skip_git_check` | `bool` | `True` | Skip git repository validation |
| `unified_exec` | `bool` | `True` | Enable unified execution mode |
| `json_output` | `bool` | `True` | Always emit JSONL output |
| `require_completion_confirmation` | `bool` | `False` | Require double-confirm before completing |

---

## Provider Configuration

### Chutes AI (Default Provider)

```bash
# Environment
CHUTES_API_KEY="your-key"
LLM_MODEL="deepseek/deepseek-chat"  # Default model

# Alternative models
LLM_MODEL="moonshotai/Kimi-K2.5-TEE"  # For complex reasoning tasks
```

### Available Models

| Model | Description | Context | Best For |
|-------|-------------|---------|----------|
| `deepseek/deepseek-chat` | Fast, cost-effective | Large | General tasks |
| `moonshotai/Kimi-K2.5-TEE` | 1T params, thinking mode | 256K | Complex reasoning |

---

## Configuration Workflow

```mermaid
flowchart TB
    subgraph Load["Configuration Loading"]
        Env[Environment Variables]
        File[defaults.py]
        Merge[Merged Config]
    end
    
    subgraph Apply["Configuration Application"]
        Loop[Agent Loop]
        LLM[LLM Client]
        Context[Context Manager]
        Tools[Tool Registry]
    end
    
    Env --> Merge
    File --> Merge
    Merge --> Loop
    Merge --> LLM
    Merge --> Context
    Merge --> Tools
```

---

## Computed Values

Some values are computed from configuration:

```python
# Usable context window
usable_context = model_context_limit - output_token_max
# Default: 200,000 - 32,000 = 168,000 tokens

# Compaction trigger threshold
compaction_trigger = usable_context * auto_compact_threshold
# Default: 168,000 * 0.85 = 142,800 tokens

# Token estimation
chars_per_token = 4  # Heuristic
tokens = len(text) // 4
```

---

## Best Practices

### For Cost Optimization

```bash
# Lower cost limit for testing
export LLM_COST_LIMIT="1.0"

# Use smaller context for simple tasks
# (edit defaults.py)
"model_context_limit": 100_000
```

### For Long Tasks

```bash
# Increase iterations
# (edit defaults.py)
"max_iterations": 500

# Lower compaction threshold for aggressive memory management
"auto_compact_threshold": 0.70
```

### For Debugging

```bash
# Disable caching to see full API calls
# (edit defaults.py)
"cache_enabled": False

# Increase output limits for more context
"max_output_tokens": 5000
```

---

## Next Steps

- [Chutes Integration](./chutes-integration.md) - Configure Chutes API
- [Context Management](./context-management.md) - Understand memory management
- [Best Practices](./best-practices.md) - Optimization tips
