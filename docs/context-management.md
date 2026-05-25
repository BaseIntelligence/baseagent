# Context Management

> **How BaseAgent manages memory and prevents token overflow**

## Why Context Management Matters

Large Language Models have finite context windows. Without proper management:
- "Context too long" errors terminate sessions
- Critical information gets lost
- Response quality degrades
- Costs increase unnecessarily

BaseAgent implements sophisticated context management inspired by OpenCode and Codex.

---

## Context Window Overview

```mermaid
graph TB
    subgraph Window["Configured Model Context Window (200K tokens)"]
        Output["Reserved for Output<br/>32K tokens"]
        Usable["Usable Context<br/>168K tokens"]
    end
    
    subgraph Thresholds["Management Thresholds"]
        Safe["Safe Zone<br/>< 85% (143K)"]
        Warning["Warning Zone<br/>85-100%"]
        Overflow["Overflow<br/>> 168K"]
    end
    
    Usable --> Safe
    Usable --> Warning
    Usable --> Overflow
    
    style Safe fill:#4CAF50,color:#fff
    style Warning fill:#FF9800,color:#fff
    style Overflow fill:#F44336,color:#fff
```

### Key Numbers

| Metric | Value | Description |
|--------|-------|-------------|
| Total context | 200,000 | Model's full context window |
| Output reserve | 32,000 | Reserved for LLM response |
| Usable context | 168,000 | Available for messages |
| Compaction threshold | 85% | Trigger at 142,800 tokens |
| Prune protect | 40,000 | Recent tool output to keep |
| Prune minimum | 20,000 | Minimum savings to prune |

---

## Token Estimation

BaseAgent estimates tokens using a simple heuristic:

```python
# 1 token ≈ 4 characters
def estimate_tokens(text: str) -> int:
    return len(text) // 4
```

### Message Token Components

```mermaid
graph LR
    subgraph Message["Message Token Estimation"]
        Content["Content<br/>(text / 4)"]
        Images["Images<br/>(~1000 each)"]
        ToolCalls["Tool Calls<br/>(name + args)"]
        Overhead["Role Overhead<br/>(~4 tokens)"]
    end
    
    Content --> Total["Total Tokens"]
    Images --> Total
    ToolCalls --> Total
    Overhead --> Total
```

---

## Context Management Pipeline

```mermaid
flowchart TB
    subgraph Input["Every Iteration"]
        Messages["Current Messages"]
    end
    
    subgraph Detection["1. Detection"]
        Estimate["Estimate Total Tokens"]
        Check{"Above 85%<br/>Threshold?"}
    end
    
    subgraph Pruning["2. Pruning (First Pass)"]
        Scan["Scan Backwards"]
        Protect["Protect Last 40K<br/>Tool Output Tokens"]
        Clear["Clear Old Tool Outputs"]
        CheckAgain{"Still Above<br/>Threshold?"}
    end
    
    subgraph Compaction["3. AI Compaction (Second Pass)"]
        Summary["Generate Summary<br/>via LLM"]
        Rebuild["Rebuild Messages:<br/>System + Summary"]
    end
    
    subgraph Output["Continue Loop"]
        Managed["Managed Messages"]
    end
    
    Messages --> Estimate --> Check
    Check -->|No| Managed
    Check -->|Yes| Scan --> Protect --> Clear --> CheckAgain
    CheckAgain -->|No| Managed
    CheckAgain -->|Yes| Summary --> Rebuild --> Managed
    
    style Pruning fill:#FF9800,color:#fff
    style Compaction fill:#9C27B0,color:#fff
```

---

## Stage 1: Tool Output Pruning

The first defense against context overflow is pruning old tool outputs.

### Strategy

1. Scan messages **backwards** (most recent first)
2. Skip the first 2 user turns (most recent)
3. Accumulate tool output tokens
4. After 40K tokens accumulated, mark older outputs for pruning
5. Only prune if savings exceed 20K tokens

### Implementation

```python
def prune_old_tool_outputs(messages, protect_last_turns=2):
    total = 0  # Total tool output tokens seen
    pruned = 0  # Tokens to be pruned
    to_prune = []
    turns = 0
    
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        
        if msg["role"] == "user":
            turns += 1
        
        if turns < protect_last_turns:
            continue
        
        if msg["role"] == "tool":
            content = msg.get("content", "")
            estimate = len(content) // 4
            total += estimate
            
            if total > PRUNE_PROTECT:  # 40K
                pruned += estimate
                to_prune.append(i)
    
    if pruned > PRUNE_MINIMUM:  # 20K
        # Replace content with marker
        for idx in to_prune:
            messages[idx]["content"] = "[Old tool result content cleared]"
    
    return messages
```

### Visual Example

```mermaid
graph TB
    subgraph Before["Before Pruning (150K tokens)"]
        S1["System Prompt<br/>5K tokens"]
        U1["User Instruction<br/>1K tokens"]
        A1["Assistant + Tools<br/>10K tokens"]
        T1["Tool Results (old)<br/>50K tokens"]
        A2["Assistant + Tools<br/>10K tokens"]
        T2["Tool Results (old)<br/>40K tokens"]
        A3["Assistant + Tools<br/>10K tokens"]
        T3["Tool Results (recent)<br/>24K tokens"]
    end
    
    subgraph After["After Pruning (60K tokens)"]
        S2["System Prompt<br/>5K tokens"]
        U2["User Instruction<br/>1K tokens"]
        A4["Assistant + Tools<br/>10K tokens"]
        T4["[cleared]<br/>~0 tokens"]
        A5["Assistant + Tools<br/>10K tokens"]
        T5["[cleared]<br/>~0 tokens"]
        A6["Assistant + Tools<br/>10K tokens"]
        T6["Tool Results (protected)<br/>24K tokens"]
    end
    
    T1 -.-> T4
    T2 -.-> T5
    T3 --> T6
    
    style T4 fill:#FF9800,color:#fff
    style T5 fill:#FF9800,color:#fff
    style T6 fill:#4CAF50,color:#fff
```

---

## Stage 2: AI Compaction

When pruning isn't enough, BaseAgent uses the LLM to summarize the conversation.

### Compaction Process

```mermaid
sequenceDiagram
    participant Loop as Agent Loop
    participant Compact as Compaction
    participant LLM as LLM API

    Loop->>Compact: Context still too large
    Compact->>Compact: Add compaction prompt
    Compact->>LLM: Request summary
    LLM-->>Compact: Summary response
    Compact->>Compact: Build new messages
    Compact-->>Loop: [System, Summary]
```

### Compaction Prompt

```python
COMPACTION_PROMPT = """
You are performing a CONTEXT CHECKPOINT COMPACTION. 
Create a handoff summary for another LLM that will resume the task.

Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue
- Which files were modified and how
- Any errors encountered and how they were resolved

Be concise, structured, and focused on helping the next LLM 
seamlessly continue the work. Use bullet points and clear sections.
"""
```

### Result

The compacted messages are:

```python
compacted = [
    {"role": "system", "content": original_system_prompt},
    {"role": "user", "content": SUMMARY_PREFIX + llm_summary},
]
```

### Summary Prefix

```python
SUMMARY_PREFIX = """
Another language model started to solve this problem and produced 
a summary of its thinking process. You also have access to the state 
of the tools that were used. Use this to build on the work that has 
already been done and avoid duplicating work.

Here is the summary from the previous context:

"""
```

---

## Middle-Out Truncation

For individual tool outputs, BaseAgent uses middle-out truncation:

```mermaid
graph LR
    subgraph Original["Original Output"]
        O1["Start<br/>(headers, definitions)"]
        O2["Middle<br/>(repetitive data)"]
        O3["End<br/>(results, errors)"]
    end
    
    subgraph Truncated["Truncated Output"]
        T1["Start<br/>(preserved)"]
        T2["[...truncated...]"]
        T3["End<br/>(preserved)"]
    end
    
    O1 --> T1
    O2 -.-> T2
    O3 --> T3
    
    style O2 fill:#FF9800,color:#fff
    style T2 fill:#FF9800,color:#fff
```

### Implementation

```python
def middle_out_truncate(text: str, max_tokens: int = 2500) -> str:
    max_chars = max_tokens * 4  # 4 chars per token
    
    if len(text) <= max_chars:
        return text
    
    keep = max_chars // 2 - 50  # Room for marker
    return f"{text[:keep]}\n\n[...truncated...]\n\n{text[-keep:]}"
```

### Why Middle-Out?

| Section | Contains | Value |
|---------|----------|-------|
| **Start** | Headers, imports, definitions | High |
| **Middle** | Repetitive data, logs | Low |
| **End** | Results, errors, summaries | High |

---

## Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `model_context_limit` | 200,000 | Total context window |
| `output_token_max` | 32,000 | Reserved for output |
| `auto_compact_threshold` | 0.85 | Trigger threshold |
| `prune_protect` | 40,000 | Recent tool tokens to keep |
| `prune_minimum` | 20,000 | Minimum savings to prune |
| `max_output_tokens` | 2,500 | Per-tool output limit |

### Tuning Guidelines

**For Long Tasks:**
```python
"auto_compact_threshold": 0.70,  # More aggressive
"prune_protect": 30_000,          # Protect less
```

**For Complex Tasks (need more context):**
```python
"auto_compact_threshold": 0.90,  # Less aggressive
"prune_protect": 60_000,          # Protect more
```

---

## Monitoring Context Usage

BaseAgent logs context status each iteration:

```
[14:30:16] [compaction] Context: 45000 tokens (26.8% of 168000)
[14:35:22] [compaction] Context: 125000 tokens (74.4% of 168000)
[14:38:45] [compaction] Context: 148000 tokens (88.1% of 168000)
[14:38:45] [compaction] Context overflow detected, managing...
[14:38:45] [compaction] Prune scan: 95000 total tokens, 55000 prunable
[14:38:45] [compaction] Pruning 12 tool outputs, recovering ~55000 tokens
[14:38:46] [compaction] Pruning sufficient: 148000 -> 93000 tokens
```

---

## Best Practices

### 1. Keep Tool Outputs Focused

```bash
# ❌ Too much output
ls -laR /  # Lists entire filesystem

# ✅ Targeted
ls -la /workspace/src/  # Just what's needed
```

### 2. Use Appropriate Search Patterns

```bash
# ❌ Too broad
grep "function"  # Matches everything

# ✅ Specific
grep "def calculate_total" src/billing.py
```

### 3. Read Sections, Not Entire Files

```json
// ❌ Entire large file
{"name": "read_file", "arguments": {"file_path": "huge.py"}}

// ✅ Specific section
{"name": "read_file", "arguments": {"file_path": "huge.py", "offset": 100, "limit": 50}}
```

### 4. Monitor Long Sessions

For tasks exceeding 50 iterations, watch for:
- Repeated compaction events
- Context oscillating near threshold
- Loss of important context after compaction

---

## Next Steps

- [Best Practices](./best-practices.md) - Optimization strategies
- [Configuration](./configuration.md) - Tuning options
- [Architecture](./architecture.md) - System design
