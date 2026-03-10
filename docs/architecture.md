# Technical Architecture

> **Deep dive into BaseAgent's system design, components, and data flow**

## System Overview

BaseAgent follows a modular architecture with clear separation of concerns:

```mermaid
graph TB
    subgraph Entry["Entry Layer"]
        agent["agent.py<br/>CLI Entry Point"]
    end
    
    subgraph Core["Core Layer"]
        loop["loop.py<br/>Agent Loop"]
        compact["compaction.py<br/>Context Manager"]
    end
    
    subgraph LLM["LLM Layer"]
        client["client.py<br/>httpx Client"]
    end
    
    subgraph Config["Configuration"]
        defaults["defaults.py<br/>Settings"]
        prompts["system.py<br/>System Prompt"]
    end
    
    subgraph Tools["Tool Layer"]
        registry["registry.py<br/>Tool Registry"]
        shell["shell.py"]
        read["read_file.py"]
        write["write_file.py"]
        patch["apply_patch.py"]
        grep["grep_files.py"]
        list["list_dir.py"]
    end
    
    subgraph Output["Output Layer"]
        jsonl["jsonl.py<br/>Event Emitter"]
    end
    
    agent --> loop
    loop --> compact
    loop --> client
    loop --> registry
    loop --> jsonl
    client --> defaults
    loop --> prompts
    registry --> shell & read & write & patch & grep & list
    
    style loop fill:#4CAF50,color:#fff
    style client fill:#2196F3,color:#fff
    style compact fill:#FF9800,color:#fff
```

---

## Component Diagram

```mermaid
classDiagram
    class AgentContext {
        +instruction: str
        +cwd: str
        +step: int
        +is_done: bool
        +history: List
        +shell(cmd, timeout) ShellResult
        +done()
        +log(msg)
    }
    
    class LLMClient {
        +model: str
        +temperature: float
        +max_tokens: int
        +cost_limit: float
        +chat(messages, tools) LLMResponse
        +get_stats() Dict
    }
    
    class LLMResponse {
        +text: str
        +function_calls: List~FunctionCall~
        +tokens: Dict
        +has_function_calls() bool
    }
    
    class FunctionCall {
        +id: str
        +name: str
        +arguments: Dict
    }
    
    class ToolRegistry {
        +tools: Dict
        +execute(ctx, name, args) ToolResult
        +get_tools_for_llm() List
    }
    
    class ToolResult {
        +success: bool
        +output: str
        +inject_content: Optional
    }
    
    AgentContext --> LLMClient : uses
    LLMClient --> LLMResponse : returns
    LLMResponse --> FunctionCall : contains
    AgentContext --> ToolRegistry : uses
    ToolRegistry --> ToolResult : returns
```

---

## Agent Loop Workflow

The heart of BaseAgent is the agent loop in `src/core/loop.py`:

```mermaid
flowchart TB
    Start([Start]) --> Init[Initialize Session]
    Init --> BuildMsg[Build Initial Messages]
    BuildMsg --> GetState[Get Terminal State]
    
    GetState --> LoopStart{Iteration < Max?}
    
    LoopStart -->|Yes| ManageCtx[Manage Context<br/>Prune/Compact if needed]
    ManageCtx --> ApplyCache[Apply Prompt Caching]
    ApplyCache --> CallLLM[Call LLM with Tools]
    
    CallLLM --> HasCalls{Has Tool Calls?}
    
    HasCalls -->|Yes| ResetPending[Reset pending_completion]
    ResetPending --> ExecTools[Execute Tool Calls]
    ExecTools --> AddResults[Add Results to Messages]
    AddResults --> LoopStart
    
    HasCalls -->|No| CheckPending{pending_completion?}
    
    CheckPending -->|No| SetPending[Set pending_completion = true]
    SetPending --> InjectVerify[Inject Verification Prompt]
    InjectVerify --> LoopStart
    
    CheckPending -->|Yes| Complete[Task Complete]
    
    LoopStart -->|No| Timeout[Max Iterations Reached]
    
    Complete --> Emit[Emit turn.completed]
    Timeout --> Emit
    Emit --> End([End])
    
    style ManageCtx fill:#FF9800,color:#fff
    style ApplyCache fill:#9C27B0,color:#fff
    style CallLLM fill:#2196F3,color:#fff
    style ExecTools fill:#4CAF50,color:#fff
    style InjectVerify fill:#E91E63,color:#fff
```

---

## Data Flow

### Request Flow

```mermaid
sequenceDiagram
    participant User
    participant Entry as agent.py
    participant Loop as loop.py
    participant Context as compaction.py
    participant Cache as Prompt Cache
    participant LLM as httpx Client
    participant Provider as API Provider
    participant Tools as Tool Registry

    User->>Entry: --instruction "Create hello.txt"
    Entry->>Entry: Initialize AgentContext
    Entry->>Entry: Initialize LLMClient
    Entry->>Loop: run_agent_loop()
    
    Loop->>Loop: Build messages [system, user, state]
    
    rect rgb(255, 240, 220)
        Note over Loop,Provider: Iteration Loop
        Loop->>Context: manage_context(messages)
        Context-->>Loop: Managed messages
        
        Loop->>Cache: apply_caching(messages)
        Cache-->>Loop: Cached messages
        
        Loop->>LLM: chat(messages, tools)
        LLM->>Provider: API Request
        Provider-->>LLM: Response
        LLM-->>Loop: LLMResponse
        
        alt Has tool_calls
            Loop->>Tools: execute(ctx, tool_name, args)
            Tools-->>Loop: ToolResult
            Loop->>Loop: Append to messages
        end
    end
    
    Loop-->>Entry: Complete
    Entry-->>User: JSONL output
```

### Message Structure

Messages accumulate through the session:

```python
messages = [
    # 1. System prompt (stable, cached)
    {"role": "system", "content": SYSTEM_PROMPT},
    
    # 2. User instruction
    {"role": "user", "content": "Create hello.txt with 'Hello World'"},
    
    # 3. Initial state
    {"role": "user", "content": "Current directory:\n```\n...\n```"},
    
    # 4. Assistant response with tool calls
    {
        "role": "assistant",
        "content": "Creating the file...",
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {...}}
        ]
    },
    
    # 5. Tool result
    {"role": "tool", "tool_call_id": "call_1", "content": "File created"},
    
    # ... continues until completion
]
```

---

## Module Descriptions

### `src/core/loop.py` - Agent Loop

The main orchestration module that:
- Initializes the session and emits JSONL events
- Manages the iterative Observe→Think→Act cycle
- Applies prompt caching for cost optimization
- Handles LLM errors with retry logic
- Triggers self-verification before completion

### `src/core/compaction.py` - Context Manager

Intelligent context management that:
- Estimates token usage (4 chars ≈ 1 token)
- Detects context overflow at 85% of usable window
- Prunes old tool outputs (protects last 40K tokens)
- Runs AI compaction when pruning is insufficient
- Preserves critical information through summarization

### `src/llm/client.py` - LLM Client

httpx-based client that:
- Uses Chutes API (OpenAI-compatible)
- Tracks token usage and costs
- Handles tool/function calling format
- Enforces cost limits
- Provides usage statistics

### `src/tools/registry.py` - Tool Registry

Centralized tool management that:
- Registers all available tools
- Provides tool specs for LLM
- Executes tools with proper context
- Handles tool output truncation
- Manages image injection for `view_image`

### `src/prompts/system.py` - System Prompt

System prompt configuration that:
- Defines agent personality and behavior
- Specifies coding guidelines
- Includes AGENTS.md support
- Configures autonomous operation mode
- Provides environment context

### `src/config/defaults.py` - Configuration

Central configuration containing:
- Model settings (model name, tokens, temperature)
- Context management thresholds
- Tool output limits
- Prompt caching settings
- Execution limits

---

## Context Management Pipeline

```mermaid
flowchart LR
    subgraph Input
        Msgs[Messages<br/>~150K tokens]
    end
    
    subgraph Detection
        Est[Estimate Tokens]
        Check{> 85% of<br/>168K usable?}
    end
    
    subgraph Pruning
        Scan[Scan backwards]
        Protect[Protect last 40K<br/>tool tokens]
        Clear[Clear old outputs]
    end
    
    subgraph Compaction
        CheckAgain{Still > 85%?}
        Summarize[AI Summarization]
        NewMsgs[Compacted Messages]
    end
    
    subgraph Output
        Result[Managed Messages]
    end
    
    Msgs --> Est --> Check
    Check -->|No| Result
    Check -->|Yes| Scan --> Protect --> Clear
    Clear --> CheckAgain
    CheckAgain -->|No| Result
    CheckAgain -->|Yes| Summarize --> NewMsgs --> Result
```

---

## Tool Execution Flow

```mermaid
flowchart TB
    subgraph LLM["LLM Response"]
        Calls["tool_calls: [<br/>  {name: 'shell_command', args: {command: 'ls'}},<br/>  {name: 'read_file', args: {file_path: 'README.md'}}<br/>]"]
    end
    
    subgraph Registry["Tool Registry"]
        direction TB
        Lookup[Lookup Tool]
        Execute[Execute with Context]
        Truncate[Truncate Output<br/>max 2500 tokens]
    end
    
    subgraph Tools["Tool Implementations"]
        Shell[shell_command]
        Read[read_file]
        Write[write_file]
        Patch[apply_patch]
        Grep[grep_files]
        List[list_dir]
    end
    
    subgraph Output["Results"]
        Results["tool results added<br/>to messages"]
    end
    
    Calls --> Lookup
    Lookup --> Execute
    Execute --> Shell & Read & Write & Patch & Grep & List
    Shell & Read & Write & Patch & Grep & List --> Truncate
    Truncate --> Results
```

---

## JSONL Event Emission

BaseAgent emits structured JSONL events throughout execution:

```mermaid
sequenceDiagram
    participant Loop as Agent Loop
    participant JSONL as Event Emitter
    participant stdout as Standard Output

    Loop->>JSONL: emit(ThreadStartedEvent)
    JSONL->>stdout: {"type": "thread.started", ...}
    
    Loop->>JSONL: emit(TurnStartedEvent)
    JSONL->>stdout: {"type": "turn.started", ...}
    
    loop Each Tool Call
        Loop->>JSONL: emit(ItemStartedEvent)
        JSONL->>stdout: {"type": "item.started", ...}
        Loop->>JSONL: emit(ItemCompletedEvent)
        JSONL->>stdout: {"type": "item.completed", ...}
    end
    
    Loop->>JSONL: emit(TurnCompletedEvent)
    JSONL->>stdout: {"type": "turn.completed", "usage": {...}}
```

---

## Error Handling Strategy

```mermaid
flowchart TB
    Error[Error Occurs] --> Type{Error Type?}
    
    Type -->|CostLimitExceeded| Abort[Emit TurnFailed<br/>Abort Session]
    
    Type -->|Authentication| Abort
    
    Type -->|Rate Limit| Retry{Attempt < 5?}
    Retry -->|Yes| Wait[Wait 10s × attempt]
    Wait --> TryAgain[Retry Request]
    Retry -->|No| Abort
    
    Type -->|Timeout/504| Retry
    
    Type -->|Other| Retry
    
    TryAgain --> Success{Success?}
    Success -->|Yes| Continue[Continue Loop]
    Success -->|No| Retry
```

---

## Next Steps

- [Configuration Reference](./configuration.md) - All settings explained
- [Tools Reference](./tools.md) - Detailed tool documentation
- [Context Management](./context-management.md) - Deep dive into memory management
