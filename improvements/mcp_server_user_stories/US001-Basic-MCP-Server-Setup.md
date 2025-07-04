# US001 - Basic MCP Server Setup

**As an administrator** I want to install and configure the MCP codebase server with a single Python repository so that I can validate the basic server infrastructure works.

## Acceptance Criteria

- Install MCP server package using existing `setup/setup_system.sh` script
- Extend existing `repositories.json` configuration file with `python_path` parameter
- Start server and confirm MCP protocol communication
- Basic health check endpoint responds

## Task Breakdown

### Core Architecture Tasks

**US001-1: Add MCP codebase server dependencies**
- Add LSP client libraries, tree-sitter, etc. to `requirements.txt`
- Update `setup/setup_system.sh` to install pylsp
- Verify dependencies install correctly

**US001-2: Extend repository configuration validation**
- Add `python_path` parameter validation to existing repository validation
- Add syntactic validation (required field, correct type)
- Add semantic validation (python_path points to valid Python executable)
- Extract GitHub owner/repo from git remote during validation

**US001-3: Rename master process**
- Rename `github_mcp_master.py` → `mcp_master.py`
- Update any references/imports

### Unified Worker Architecture

**US001-4: Create unified worker**
- Create `mcp_worker.py` that replaces `github_mcp_worker.py`
- Keep completely tool-agnostic - imports both tool modules
- Handles MCP protocol, shutdown, generic tool registration

**US001-5: Refactor GitHub tools for registration**
- Add `get_tools()` function to `github_tools.py`
- Include both implementations AND descriptions in returned data
- Return dictionary with tool metadata (implementation, description, schema)

**US001-6: Move tool descriptions to GitHub tools**
- Move MCP tool descriptions from `github_mcp_worker.py` into `github_tools.py`
- Keep descriptions alongside implementations for better cohesion

**US001-7: Create codebase tools module**
- Create `codebase_tools.py` with `get_tools()` function
- Return both implementations AND descriptions
- Implement basic health check tool

**US001-8: Update master coordination**
- Modify `mcp_master.py` to spawn unified workers instead of GitHub-specific workers
- Remove GitHub-specific worker references

### Testing Tasks

**US001-9: Repository configuration validation tests**
- Test syntactic validation (missing python_path, wrong types)
- Test semantic validation (invalid python_path, non-existent directory)
- Test GitHub remote extraction from various Git URL formats
- Test error message clarity

**US001-10: Tool-agnostic worker tests**
- Test unified `mcp_worker.py` tool registration system
- Test generic tool loading from multiple modules
- Test MCP protocol handling
- Mock tool modules for isolated testing

**US001-11: Codebase tools tests**
- Test `codebase_tools.py` health check tool
- Test tool registration format
- Test error handling in tool implementations

**US001-12: Integration test**
- End-to-end test: configure single repository with `python_path`, start unified worker
- Verify health check tool functionality
- Test complete workflow from setup script to working server
- Verify server loads both GitHub and codebase tools

## Architecture Notes

### Unified Worker Pattern

```
mcp_worker.py (tool-agnostic)
├── imports github_tools.py
├── imports codebase_tools.py
└── registers all tools generically
```

### Tool Registration Pattern

Each tool module exports:
```python
def get_tools():
    return {
        "tool_name": {
            "implementation": function_ref,
            "description": "Tool description",
            "schema": {...}
        }
    }
```

This keeps `mcp_worker.py` completely tool-agnostic while allowing both GitHub and codebase tools to be served from the same port.
