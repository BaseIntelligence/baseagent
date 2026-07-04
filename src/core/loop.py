"""
Main agent loop - the heart of the SuperAgent system.

Implements the agentic loop that:
1. Receives instruction via --instruction argument
2. Calls LLM with tools (via the platform LLM gateway)
3. Executes tool calls
4. Loops until task is complete
5. Emits JSONL events throughout

Context management strategy (like OpenCode/Codex):
- Token-based overflow detection (not message count)
- Tool output pruning (clear old outputs first)
- AI compaction when needed (summarize conversation)
- Stable system prompt for cache hits
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from src.core.compaction import (
    manage_context,
)
from src.llm.client import CostLimitExceeded, LLMError
from src.output.jsonl import (
    ItemCompletedEvent,
    ItemStartedEvent,
    ThreadStartedEvent,
    TurnCompletedEvent,
    TurnFailedEvent,
    TurnStartedEvent,
    emit,
    make_agent_message_item,
    make_command_execution_item,
    next_item_id,
    reset_item_counter,
)
from src.prompts.system import get_system_prompt
from src.utils.truncate import middle_out_truncate

if TYPE_CHECKING:
    from src.llm.client import LLMClient
    from src.tools.registry import ToolRegistry


def _log(msg: str) -> None:
    """Log to stderr."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [loop] {msg}", file=sys.stderr, flush=True)


def _add_cache_control_to_message(
    msg: Dict[str, Any],
    cache_control: Dict[str, str],
) -> Dict[str, Any]:
    """Add cache_control to a message, converting to multipart if needed."""
    content = msg.get("content")

    if isinstance(content, list):
        has_cache = any(isinstance(p, dict) and "cache_control" in p for p in content)
        if has_cache:
            return msg

        new_content = list(content)
        for i in range(len(new_content) - 1, -1, -1):
            part = new_content[i]
            if isinstance(part, dict) and part.get("type") == "text":
                new_content[i] = {**part, "cache_control": cache_control}
                break
        return {**msg, "content": new_content}

    if isinstance(content, str):
        return {
            **msg,
            "content": [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": cache_control,
                }
            ],
        }

    return msg


def _apply_caching(
    messages: List[Dict[str, Any]],
    enabled: bool = True,
) -> List[Dict[str, Any]]:
    """
    Apply prompt caching like OpenCode does:
    - Cache first 2 system messages (stable prefix)
    - Cache last 2 non-system messages (extends cache to cover conversation history)

    How prefix caching works:
    - Cache is based on IDENTICAL PREFIX
    - A cache_control breakpoint tells compatible providers to cache everything before it
    - By marking the last messages, we cache the entire conversation history
    - Each new request only adds new messages after the cached prefix

    Provider limits vary; unsupported cache markers are stripped before gateway requests.

    Reference: OpenCode transform.ts applyCaching()
    """
    if not enabled or not messages:
        return messages

    cache_control = {"type": "ephemeral"}

    # Separate system and non-system message indices
    system_indices = []
    non_system_indices = []

    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            system_indices.append(i)
        else:
            non_system_indices.append(i)

    # Determine which messages to cache:
    # 1. First 2 system messages (stable system prompt)
    # 2. Last 2 non-system messages (extends cache to conversation history)
    indices_to_cache = set()

    # Add first 2 system messages
    for idx in system_indices[:2]:
        indices_to_cache.add(idx)

    # Add last 2 non-system messages
    for idx in non_system_indices[-2:]:
        indices_to_cache.add(idx)

    # Build result with cache_control added to selected messages
    result = []
    for i, msg in enumerate(messages):
        if i in indices_to_cache:
            result.append(_add_cache_control_to_message(msg, cache_control))
        else:
            result.append(msg)

    cached_system = len([i for i in indices_to_cache if i in system_indices])
    cached_final = len([i for i in indices_to_cache if i in non_system_indices])

    if indices_to_cache:
        _log(
            f"Prompt caching: {cached_system} system + {cached_final} final messages marked ({len(indices_to_cache)} breakpoints)"
        )

    return result


def run_agent_loop(
    llm: "LLMClient",
    tools: "ToolRegistry",
    ctx: Any,
    config: Dict[str, Any],
) -> None:
    """
    Run the main agent loop.

    Args:
        llm: LLM client
        tools: Tool registry with available tools
        ctx: Agent context with instruction, shell(), done()
        config: Configuration dictionary
    """
    # Reset item counter for fresh session
    reset_item_counter()

    # Generate session ID
    session_id = f"sess_{int(time.time() * 1000)}"

    # 1. Emit thread.started
    emit(ThreadStartedEvent(thread_id=session_id))

    # 2. Emit turn.started
    emit(TurnStartedEvent())

    # 3. Build initial messages
    cwd = Path(ctx.cwd)
    system_prompt = get_system_prompt(cwd=cwd)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": ctx.instruction},
    ]

    # 4. Get initial terminal state
    _log("Getting initial state...")
    initial_result = ctx.shell("pwd && ls -la")
    max_output_tokens = config.get("max_output_tokens", 2500)
    initial_state = middle_out_truncate(initial_result.output, max_tokens=max_output_tokens)

    messages.append(
        {
            "role": "user",
            "content": f"Current directory and files:\n```\n{initial_state}\n```",
        }
    )

    # 5. Initialize tracking
    total_input_tokens = 0
    total_output_tokens = 0
    total_cached_tokens = 0
    pending_completion = False

    max_iterations = config.get("max_iterations", 200)
    cache_enabled = config.get("cache_enabled", True)

    # 6. Main loop
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        _log(f"Iteration {iteration}/{max_iterations}")

        try:
            # ================================================================
            # Context Management (replaces sliding window)
            # ================================================================
            # Check token usage and apply pruning/compaction if needed
            context_messages = manage_context(
                messages=messages,
                system_prompt=system_prompt,
                llm=llm,
            )

            # If compaction happened, update our messages reference
            if len(context_messages) < len(messages):
                _log(f"Context compacted: {len(messages)} -> {len(context_messages)} messages")
                messages = context_messages

            # ================================================================
            # Apply caching (system prompt only for stability)
            # ================================================================
            cached_messages = _apply_caching(context_messages, enabled=cache_enabled)

            # Get tool specs
            tool_specs = tools.get_tools_for_llm()

            # ================================================================
            # Call LLM with retry logic
            # ================================================================
            max_retries = 5
            response = None

            for attempt in range(1, max_retries + 1):
                try:
                    response = llm.chat(
                        cached_messages,
                        tools=tool_specs,
                        max_tokens=config.get("max_tokens", 16384),
                    )

                    # Track token usage from response
                    if hasattr(response, "tokens") and response.tokens:
                        tokens = response.tokens
                        if isinstance(tokens, dict):
                            total_input_tokens += tokens.get("input", 0)
                            total_output_tokens += tokens.get("output", 0)
                            total_cached_tokens += tokens.get("cached", 0)

                    break  # Success, exit retry loop

                except CostLimitExceeded:
                    raise  # Don't retry cost limit errors

                except LLMError as e:
                    error_msg = str(e.message) if hasattr(e, "message") else str(e)
                    _log(f"LLM error (attempt {attempt}/{max_retries}): {e.code} - {error_msg}")

                    # Don't retry authentication errors
                    if e.code in ("authentication_error", "invalid_api_key"):
                        raise

                    # Check if it's a retryable error
                    is_retryable = any(
                        x in error_msg.lower()
                        for x in [
                            "504",
                            "timeout",
                            "empty response",
                            "overloaded",
                            "rate_limit",
                            "connection",
                            "closed",
                            "bad file descriptor",
                            "reset",
                            "broken pipe",
                        ]
                    )

                    if attempt < max_retries and is_retryable:
                        wait_time = 10 * attempt  # 10s, 20s, 30s, 40s
                        _log(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        raise

                except Exception as e:
                    error_msg = str(e)
                    _log(
                        f"Unexpected error (attempt {attempt}/{max_retries}): {type(e).__name__}: {error_msg}"
                    )

                    is_retryable = any(
                        x in error_msg.lower()
                        for x in [
                            "504",
                            "timeout",
                            "connection",
                            "closed",
                            "bad file descriptor",
                            "reset",
                            "broken pipe",
                        ]
                    )

                    if attempt < max_retries and is_retryable:
                        wait_time = 10 * attempt
                        _log(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        raise

        except CostLimitExceeded as e:
            _log(f"Cost limit exceeded: {e}")
            emit(TurnFailedEvent(error={"message": f"Cost limit exceeded: {e}"}))
            ctx.done()
            return

        except LLMError as e:
            _log(f"LLM error (fatal): {e.code} - {e.message}")
            emit(TurnFailedEvent(error={"message": str(e)}))
            ctx.done()
            return

        except Exception as e:
            _log(f"Unexpected error (fatal): {type(e).__name__}: {e}")
            emit(TurnFailedEvent(error={"message": str(e)}))
            ctx.done()
            return

        # Process response text
        response_text = response.text or ""

        if response_text:
            # Emit agent message
            item_id = next_item_id()
            emit(ItemCompletedEvent(item=make_agent_message_item(item_id, response_text)))

        # Check for function calls
        has_function_calls = (
            response.has_function_calls()
            if hasattr(response, "has_function_calls")
            else bool(response.function_calls)
        )

        if not has_function_calls:
            # No tool calls - agent thinks it's done
            _log("No tool calls in response")

            # Always do verification before completing (self-questioning)
            if pending_completion:
                # Agent already verified - complete the task
                _log("Task completion confirmed after self-verification")
                break
            else:
                # First time without tool calls - ask for self-verification
                pending_completion = True
                messages.append({"role": "assistant", "content": response_text})

                # Build verification prompt with original instruction
                verification_prompt = f"""<system-reminder>
# Self-Verification Required - CRITICAL

You indicated the task might be complete. Before finishing, you MUST perform a thorough self-verification.

## Original Task (re-read carefully):
{ctx.instruction}

## Self-Verification Checklist:

### 1. Requirements Analysis
- Re-read the ENTIRE original task above word by word
- List EVERY requirement, constraint, and expected outcome mentioned
- Check if there are any implicit requirements you might have missed

### 2. Work Verification
- For EACH requirement identified, verify it was completed:
  - Run commands to check file contents, test outputs, or verify state
  - Do NOT assume something works - actually verify it
  - If you created code, run it to confirm it works
  - If you modified files, read them back to confirm changes are correct

### 3. Edge Cases & Quality
- Are there any edge cases the task mentioned that you haven't handled?
- Did you follow any specific format/style requirements mentioned?
- Are there any errors, warnings, or issues in your implementation?

### 4. Final Decision
After completing the above verification:
- If EVERYTHING is verified and correct: Summarize what was done and confirm completion
- If ANYTHING is missing or broken: Fix it now using the appropriate tools

## CRITICAL REMINDERS:
- You are running in HEADLESS mode - DO NOT ask questions to the user
- DO NOT ask for confirmation or clarification - make reasonable decisions
- If something is ambiguous, make the most reasonable choice and proceed
- If you find issues during verification, FIX THEM before completing
- Only complete if you have VERIFIED (not assumed) that everything works

Proceed with verification now.
</system-reminder>"""

                messages.append(
                    {
                        "role": "user",
                        "content": verification_prompt,
                    }
                )
                _log("Requesting self-verification before completion")
                continue

        # Reset pending completion flag (agent is still working)
        pending_completion = False

        # Add assistant message with tool calls
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": response_text}

        # Build tool_calls for message history
        tool_calls_data = []
        for call in response.function_calls:
            tool_calls_data.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": (
                            str(call.arguments)
                            if isinstance(call.arguments, dict)
                            else call.arguments
                        ),
                    },
                }
            )

        if tool_calls_data:
            assistant_msg["tool_calls"] = tool_calls_data

        messages.append(assistant_msg)

        # Execute each tool call
        for call in response.function_calls:
            tool_name = call.name
            tool_args = call.arguments if isinstance(call.arguments, dict) else {}

            _log(f"Executing tool: {tool_name}")

            # Emit item.started
            item_id = next_item_id()
            emit(
                ItemStartedEvent(
                    item=make_command_execution_item(
                        item_id=item_id,
                        command=f"{tool_name}({tool_args})",
                        status="in_progress",
                    )
                )
            )

            # Execute tool
            result = tools.execute(ctx, tool_name, tool_args)

            # Truncate output using middle-out (keeps beginning and end)
            output = middle_out_truncate(result.output, max_tokens=max_output_tokens)

            # Emit item.completed
            emit(
                ItemCompletedEvent(
                    item=make_command_execution_item(
                        item_id=item_id,
                        command=f"{tool_name}",
                        status="completed" if result.success else "failed",
                        aggregated_output=output,
                        exit_code=0 if result.success else 1,
                    )
                )
            )

            # Handle image injection
            if result.inject_content:
                # Add image to next user message
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Image from {tool_name}:"},
                            result.inject_content,
                        ],
                    }
                )

            # Add tool result to messages
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": output,
                }
            )

    # 7. Emit turn.completed
    emit(
        TurnCompletedEvent(
            usage={
                "input_tokens": total_input_tokens,
                "cached_input_tokens": total_cached_tokens,
                "output_tokens": total_output_tokens,
            }
        )
    )

    _log(f"Loop complete after {iteration} iterations")
    _log(
        f"Tokens: {total_input_tokens} input, {total_cached_tokens} cached, {total_output_tokens} output"
    )
    ctx.done()
