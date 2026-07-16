"""Main agent loop for SuperAgent - inspired by Codex CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from src.llm.client import FunctionCall, LLMClient, LLMResponse
from src.config.models import AgentConfig
from src.core.session import Session
from src.output.processor import OutputProcessor
from src.prompts.system import get_system_prompt
from src.tools.registry import ToolRegistry, ToolResult


class Agent:
    """Main agent that runs the LLM loop with tool execution.

    This implements the core agent loop similar to Codex CLI:
    1. Send messages to LLM
    2. If LLM returns tool calls, execute them
    3. Feed results back to LLM
    4. Repeat until no more tool calls (needs_follow_up = False)
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        cwd: Optional[Path] = None,
        output_processor: Optional[OutputProcessor] = None,
    ):
        """Initialize the agent.

        Args:
            config: Agent configuration
            cwd: Working directory (defaults to current)
            output_processor: Output processor for events
        """
        self.config = config or AgentConfig()
        self.cwd = cwd or Path(self.config.paths.cwd or ".").resolve()

        # Initialize components
        self.client = LLMClient(self.config)
        self.tools = ToolRegistry(self.cwd)
        self.output = output_processor or OutputProcessor(self.config)

        # Session state
        self.session: Optional[Session] = None

    def run(
        self,
        prompt: str,
        on_message: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, dict], None]] = None,
    ) -> str:
        """Run the agent with a user prompt.

        Args:
            prompt: User's instruction/prompt
            on_message: Optional callback for assistant messages
            on_tool_call: Optional callback for tool calls

        Returns:
            Final assistant message
        """
        # Create session
        self.session = Session(config=self.config, cwd=self.cwd)

        # Add system prompt
        system_prompt = get_system_prompt(cwd=self.cwd)
        self.session.add_system_message(system_prompt)

        # Add user message
        self.session.add_user_message(prompt)

        # Emit session started
        self.output.emit_turn_started(self.session)

        # Run the agent loop
        try:
            final_message = self._run_loop(on_message, on_tool_call)
            self.session.mark_done(final_message)
            self.output.emit_turn_completed(self.session, final_message)
            return final_message

        except Exception as e:
            error_msg = f"Agent error: {e}"
            self.output.emit_error(error_msg)
            self.session.mark_done(error_msg)
            raise

        finally:
            self.client.close()

    def _run_loop(
        self,
        on_message: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, dict], None]] = None,
    ) -> str:
        """Run the main agent loop.

        Returns:
            Final assistant message
        """
        if not self.session:
            raise RuntimeError("No session initialized")

        last_message = ""

        while True:
            # Check iteration limit
            if not self.session.increment_iteration():
                self.output.emit_message(
                    f"Reached maximum iterations ({self.config.max_iterations})"
                )
                break

            # Get tools for the LLM
            tools = self.tools.get_tools_for_llm()

            # Call the LLM
            self.output.emit_thinking()

            response = self.client.chat(
                messages=self.session.get_messages_for_api(),
                tools=tools,
            )

            # Update token usage
            self.session.update_usage(
                response.input_tokens,
                response.output_tokens,
                response.cached_tokens,
            )

            # Process the response
            needs_follow_up = self._process_response(
                response,
                on_message,
                on_tool_call,
            )

            # Store last message
            if response.text:
                last_message = response.text

            # If no tool calls, we're done
            if not needs_follow_up:
                break

        return last_message

    def _process_response(
        self,
        response: LLMResponse,
        on_message: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, dict], None]] = None,
    ) -> bool:
        """Process an LLM response.

        Args:
            response: The LLM response
            on_message: Callback for messages
            on_tool_call: Callback for tool calls

        Returns:
            True if follow-up is needed (tool calls were made)
        """
        if not self.session:
            raise RuntimeError("No session initialized")

        # Handle text response
        if response.text:
            self.output.emit_assistant_message(response.text)
            if on_message:
                on_message(response.text)

        # Check for tool calls
        if not response.has_function_calls:
            # No tool calls - add response and we're done
            self.session.add_assistant_message(response.text)
            return False

        # Build tool_calls format for the message
        tool_calls_data = []
        for call in response.function_calls:
            tool_calls_data.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": str(call.arguments),
                    },
                }
            )

        # Add assistant message with tool calls
        self.session.add_assistant_message(
            response.text or "",
            tool_calls=tool_calls_data,
        )

        # Execute each tool call
        for call in response.function_calls:
            result = self._execute_tool_call(call, on_tool_call)

            # Add tool result to conversation
            self.session.add_tool_result(
                tool_call_id=call.id,
                name=call.name,
                content=result.to_message(),
            )

        # Need follow-up since we executed tools
        return True

    def _execute_tool_call(
        self,
        call: FunctionCall,
        on_tool_call: Optional[Callable[[str, dict], None]] = None,
    ) -> ToolResult:
        """Execute a single tool call.

        Args:
            call: The function call to execute
            on_tool_call: Optional callback

        Returns:
            ToolResult from execution
        """
        self.output.emit_tool_call_start(call.name, call.arguments)

        if on_tool_call:
            on_tool_call(call.name, call.arguments)

        # Execute the tool
        result = self.tools.execute(call.name, call.arguments)

        self.output.emit_tool_call_end(call.name, result)

        return result
