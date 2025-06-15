import asyncio
import importlib
import json

# Import your MCP server module
pr = importlib.import_module("pr_review_server")

async def main():
    tools = await pr.handle_list_tools()

    print("\n📦 Available Tools:")
    for idx, tool in enumerate(tools):
        print(f"{idx + 1}. {tool.name}: {tool.description}")

    idx = int(input("\n🔢 Choose a tool to run (number): ")) - 1
    selected = tools[idx]

    print(f"\n🛠️ Running tool: {selected.name}")
    args = {}

    # Extract schema by inspecting the tool's dict (robust even if inputSchema is not a real attribute)
    tool_dict = selected.dict() if callable(getattr(selected, "dict", None)) else {}
    input_schema = tool_dict.get("inputSchema") or tool_dict.get("input_schema")

    if isinstance(input_schema, dict):
        param_schema = input_schema.get("properties", {})
        required_fields = set(input_schema.get("required", []))
    elif callable(getattr(input_schema, "model_json_schema", None)):
        model_schema = input_schema.model_json_schema()
        param_schema = model_schema.get("properties", {})
        required_fields = set(model_schema.get("required", []))
    else:
        print("⚠️ No usable input schema found — running with empty input.")
        param_schema = {}
        required_fields = set()

    # Debug: show tool metadata
    print("\n🐞 [DEBUG] Tool raw .dict() output:")
    print(json.dumps(tool_dict, indent=2))

    # Prompt for tool arguments
    if param_schema:
        print("🔧 Tool parameters:")
        for name, details in param_schema.items():
            typ = details.get("type", "string")
            default = details.get("default")
            required = name in required_fields
            prompt = f"{name} ({typ})"
            if default is not None:
                prompt += f" [default={default}]"
            prompt += ": "
            val = input(prompt)
            if val == "" and default is not None:
                val = default
            if val != "":
                args[name] = val

    print(f"\n📤 Sending arguments to tool '{selected.name}':")
    print(json.dumps(args, indent=2))

    print(f"\n📤 Sending: {json.dumps(args, indent=2)}")
    result = await pr.handle_call_tool(name=selected.name, arguments=args)

    print("\n📥 Result:")
    for r in result:
        print(r.text)

if __name__ == "__main__":
    asyncio.run(main())

