import asyncio
import json
import subprocess
import sys
import os

# Ensure the server script is in the same directory or provide its path
SERVER_SCRIPT = "pr_review_server.py"

class MCPClient:
    """
    Manages the communication with the MCP server subprocess.
    Handles initialization and sends/receives JSON-RPC messages.
    """
    def __init__(self, server_script_path: str):
        self.server_script_path = server_script_path
        self.process = None
        self.reader = None
        self.writer = None
        self._request_id_counter = 0

    async def start_and_initialize(self):
        """
        Starts the server subprocess and performs the MCP initialization handshake.
        """
        print(f"Starting MCP server: {self.server_script_path}")
        try:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                self.server_script_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.reader = self.process.stdout
            self.writer = self.process.stdin

            # Read stderr in a separate task to avoid blocking and capture errors
            asyncio.create_task(self._read_stderr())

            # Send the initialization request with required parameters
            init_command = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "initialize",
                "params": {
                    # Added required initialization parameters as per MCP specification
                    "protocolVersion": "0.1.0", # A standard protocol version
                    "clientInfo": {
                        "name": "MCP Command-Line Driver",
                        "version": "1.0"
                    },
                    "capabilities": {
                        "content": {
                            "text": True # Indicate client supports text content
                        },
                        "tools": {
                            "list": True,
                            "call": True
                        }
                    },
                    "initializationOptions": {} # Empty options, can be extended if server requires specific ones
                }
            }
            print("Sending 'initialize' command...")
            response = await self._send_and_receive(init_command)

            if "error" in response:
                print(f"Initialization Error: {response['error']}", file=sys.stderr)
                raise Exception(f"Failed to initialize MCP server: {response['error']}")
            
            print("MCP server initialized successfully.")

            # Send the 'initialized' notification after successful initialization response
            # This tells the server the client is now ready to send further requests.
            await self.send_initialized_notification()

            return response

        except FileNotFoundError:
            raise Exception(f"Server script not found: {self.server_script_path}. Make sure it's in the same directory.")
        except Exception as e:
            await self.shutdown() # Ensure cleanup if initialization fails
            raise Exception(f"Error during server startup or initialization: {e}")

    async def _read_stderr(self):
        """Reads and prints stderr output from the subprocess."""
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            # Decode and print, prefixing to distinguish from stdout
            print(f"SERVER STDERR: {line.decode('utf-8').strip()}", file=sys.stderr)

    async def _send_and_receive(self, command: dict) -> dict:
        """
        Sends a JSON-RPC command to the server and waits for its response.
        This handles the synchronous request/response pattern for a single call.
        """
        if not self.writer or not self.reader:
            return {"error": "MCP client not connected. Call start_and_initialize first."}

        request_str = json.dumps(command) + "\n"
        self.writer.write(request_str.encode('utf-8'))
        await self.writer.drain()

        # Read response line by line until a valid JSON-RPC response is found
        # (assuming each response is a single line/JSON object)
        while True:
            line = await self.reader.readline()
            if not line:
                return {"error": "Server closed connection unexpectedly or no response received."}
            
            response_str = line.decode('utf-8').strip()
            if not response_str:
                continue # Skip empty lines

            try:
                response = json.loads(response_str)
                # Check if the response matches the ID of our command, or if it's a notification
                if "id" in response and response["id"] == command.get("id"):
                    return response
                elif "method" in response:
                    # This might be a notification from the server, print and continue waiting for our response
                    # For a simple driver, we can just print notifications.
                    print(f"SERVER NOTIFICATION: {response['method']} {response.get('params', {})}")
                    continue
                else:
                    # Unexpected or unmatching response, print and continue waiting
                    print(f"UNMATCHED SERVER RESPONSE: {response_str}")
                    continue
            except json.JSONDecodeError:
                # Not a valid JSON, might be server logs or unexpected output
                print(f"RAW SERVER OUTPUT (non-JSON): {response_str}", file=sys.stderr)
                continue

    async def send_command(self, method: str, params: dict = None) -> dict:
        """
        Constructs and sends a JSON-RPC command, returning the parsed result.
        """
        command_id = self._get_next_request_id()
        command = {
            "jsonrpc": "2.0",
            "id": command_id,
            "method": method,
            "params": params if params is not None else {}
        }
        return await self._send_and_receive(command)

    async def send_initialized_notification(self):
        """
        Sends an 'initialized' notification to the server.
        This is a notification, so it doesn't expect a response.
        """
        notification = {
            "jsonrpc": "2.0",
            # Corrected method name for the 'initialized' notification as per MCP spec
            "method": "notifications/initialized",
            "params": {} # As per protocol, can be empty or have specific data if needed by server
        }
        notification_str = json.dumps(notification) + "\n"
        if self.writer:
            self.writer.write(notification_str.encode('utf-8'))
            await self.writer.drain()
            print("Sent 'notifications/initialized' notification to server.")
        else:
            print("Warning: Cannot send 'notifications/initialized' notification, writer not available.")


    def _get_next_request_id(self) -> int:
        """Generates a unique request ID."""
        self._request_id_counter += 1
        return self._request_id_counter

    async def shutdown(self):
        """Closes the server connection."""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        if self.process:
            if self.process.returncode is None:
                self.process.terminate()
                await self.process.wait()
            print("MCP server process terminated.")


async def main():
    print("Initializing MCP Command-Line Driver...")

    # Check if the server script exists
    if not os.path.exists(SERVER_SCRIPT):
        print(f"Error: The server script '{SERVER_SCRIPT}' was not found in the current directory.")
        print("Please ensure 'pr_review_server.py' is in the same directory as this driver script.")
        sys.exit(1)

    client = MCPClient(SERVER_SCRIPT)
    try:
        await client.start_and_initialize()

        # 1. List all available tools
        print("\nFetching available tools...")
        tools_response = await client.send_command("tools/list")

        if "error" in tools_response:
            print(f"Error fetching tools: {tools_response['error']}")
            return

        tools = tools_response.get("result", [])
        if not tools:
            print("No tools found from the server.")
            return

        print("\nAvailable Tools:")
        for i, tool in enumerate(tools):
            print(f"[{i+1}] {tool['name']}: {tool['description']}")

        # 2. Pick a tool
        while True:
            try:
                choice = input("\nEnter the number of the tool to execute (or 'q' to quit): ")
                if choice.lower() == 'q':
                    print("Exiting driver.")
                    break # Exit the loop and shutdown

                tool_index = int(choice) - 1
                if 0 <= tool_index < len(tools):
                    selected_tool = tools[tool_index]
                    break
                else:
                    print("Invalid tool number. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number or 'q'.")

        if choice.lower() == 'q':
            return # Exit main if user chose to quit

        print(f"\nSelected tool: {selected_tool['name']}")

        # 3. Enter tool parameters by hand
        tool_arguments = {}
        input_schema = selected_tool.get('inputSchema', {})
        properties = input_schema.get('properties', {})
        required_params = input_schema.get('required', [])

        print("\nEnter parameters for the selected tool (press Enter for optional parameters to skip):")
        for param_name, param_details in properties.items():
            param_type = param_details.get('type', 'string')
            param_description = param_details.get('description', '')
            is_required = param_name in required_params

            prompt_text = f"  - {param_name} ({param_type}, { 'REQUIRED' if is_required else 'optional' }): {param_description}: "
            
            while True:
                value = input(prompt_text)
                if not value and not is_required:
                    # Optional parameter, user skipped
                    break
                elif not value and is_required:
                    print(f"  This parameter is required. Please provide a value.")
                else:
                    # Attempt to convert type
                    try:
                        if param_type == "integer":
                            tool_arguments[param_name] = int(value)
                        elif param_type == "boolean":
                            tool_arguments[param_name] = value.lower() in ('true', '1', 't', 'y', 'yes')
                        elif param_type == "number": # for float
                            tool_arguments[param_name] = float(value)
                        else: # default to string
                            tool_arguments[param_name] = value
                        break
                    except ValueError:
                        print(f"  Invalid input for type '{param_type}'. Please enter a valid value.")

        # 4. Execute the tool and print the result
        print(f"\nExecuting tool '{selected_tool['name']}' with arguments: {tool_arguments}")
        result = await client.send_command(
            "tools/call",
            {"name": selected_tool['name'], "arguments": tool_arguments}
        )

        print("\n--- Tool Execution Result ---")
        if isinstance(result, dict) and "error" in result:
            print(f"Error: {result['error']}")
        elif isinstance(result, dict) and "result" in result:
            output_contents = result["result"]
            if isinstance(output_contents, list):
                for content_item in output_contents:
                    if isinstance(content_item, dict) and content_item.get("type") == "text":
                        print(content_item.get("text"))
                    else:
                        print(f"Unexpected content item format: {content_item}")
            else:
                print(f"Unexpected result format: {result}")
        else:
            print(json.dumps(result, indent=2, default=str)) # Fallback if result structure is unexpected
        print("-----------------------------\n")

    finally:
        await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())

