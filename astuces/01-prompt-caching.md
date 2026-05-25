# Prompt Caching - Achieve 90%+ Cache Hit Rate

## The Problem

Without caching, every API call sends the full conversation history. For long tasks, this means:
- Sending 100k+ tokens repeatedly
- Paying full price for each request
- Slow response times

## How Prompt Caching Works

Provider prompt caches generally work from **prefixes**. If the first N tokens of your request match a cached prefix, those tokens may be served from cache at a reduced cost.

Key insight: **Cache breakpoints extend the cached prefix**.

```
Request 1: [System] [User1] [Assistant1] [User2]
                     ↑ breakpoint here = cache includes System + User1

Request 2: [System] [User1] [Assistant1] [User2] [Assistant2] [User3]
                     ↑ same prefix = CACHE HIT on System + User1
```

## The Codex Strategy

Codex CLI caches:
1. **System messages** (first 2)
2. **Last 2 non-system messages**

This creates up to 4 cache breakpoints.

Why last 2 messages? Because the entire conversation history BEFORE those messages becomes the cached prefix!

## Implementation

```python
def _apply_caching(messages: List[Dict], enabled: bool = True) -> List[Dict]:
    """Apply cache_control to messages for prompt caching."""
    if not enabled or not messages:
        return messages
    
    result = [msg.copy() for msg in messages]
    cache_control = {"type": "ephemeral"}
    breakpoints_used = 0
    max_breakpoints = 4
    
    # 1. Cache system messages (first 2)
    for msg in result:
        if msg.get("role") == "system" and breakpoints_used < 2:
            msg = _add_cache_control(msg, cache_control)
            breakpoints_used += 1
    
    # 2. Cache last 2 non-system messages
    non_system = [(i, m) for i, m in enumerate(result) if m.get("role") != "system"]
    
    for idx, msg in reversed(non_system[-2:]):
        if breakpoints_used < max_breakpoints:
            result[idx] = _add_cache_control(msg, cache_control)
            breakpoints_used += 1
    
    return result
```

## Cache Control Format

For simple text content:
```python
{
    "role": "user",
    "content": [
        {
            "type": "text",
            "text": "Your message here",
            "cache_control": {"type": "ephemeral"}
        }
    ]
}
```

For multipart content, add `cache_control` to the LAST text block.

## Verifying It Works

Check your API response for:
```json
{
    "usage": {
        "input_tokens": 50000,
        "cache_creation_input_tokens": 45000,
        "cache_read_input_tokens": 45000
    }
}
```

Cache hit rate = `cache_read_input_tokens / input_tokens`

Target: **>90%** on multi-turn conversations.

## Common Mistakes

1. **Only caching system prompt**: Gives ~5% hit rate, not 90%
2. **Caching ALL messages**: Wastes breakpoints, no benefit
3. **Forgetting multipart format**: Cache control must be on content blocks
4. **Not using ephemeral type**: Only `ephemeral` works for prompt caching

## Cost Impact

| Scenario | Cost per 1M input tokens |
|----------|-------------------------|
| No caching | $3.00 |
| 90% cache hit | $0.30 |
| **Savings** | **90%** |

For a 100-turn task with 100k context, this saves ~$27 per task.
