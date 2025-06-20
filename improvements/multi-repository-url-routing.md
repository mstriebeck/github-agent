# Multi-Repository URL Routing Design

## Current State

The GitHub MCP server currently supports only a single repository per server instance, configured via the `LOCAL_REPO_PATH` environment variable. All MCP requests operate on this single repository.

## Problem Statement

Users want to work with multiple repositories from a single Amp chat session. The current architecture requires running separate server instances or constantly changing environment variables, which is cumbersome and doesn't scale.

## Proposed Solution

Implement URL-based routing where different repositories are accessible via distinct URL paths:
- `http://localhost:8080/mcp/my-project/` → `/Users/bob/code/my-project`
- `http://localhost:8080/mcp/work-stuff/` → `/Users/bob/work/complex-repository`
- `http://localhost:8080/mcp/github-agent/` → `/Volumes/Code/github-agent`

## Technical Design

### Repository Configuration

Create a `repositories.json` configuration file:
```json
{
  "repositories": {
    "my-project": {
      "path": "/Users/bob/code/my-project",
      "description": "Personal project repository"
    },
    "work-stuff": {
      "path": "/Users/bob/work/complex-repository", 
      "description": "Work-related code"
    },
    "github-agent": {
      "path": "/Volumes/Code/github-agent",
      "description": "GitHub MCP Agent"
    }
  }
}
```

### URL Structure
- Base URL: `http://localhost:8080/mcp/{repo-name}/`
- Repository name must match a key in the configuration file
- Invalid repository names return 404 with available options

### Server Architecture Changes

1. **Repository Manager**: Central component that loads and validates repository configuration
2. **URL Router**: Extracts repository name from URL path and validates against configuration
3. **Request Context**: Each MCP request carries repository context throughout the call chain
4. **Tool Adaptation**: All GitHub tools receive repository path as context rather than from environment

### Configuration Management

- Default location: `~/.local/share/github-agent/repositories.json`
- Environment override: `GITHUB_AGENT_REPO_CONFIG`
- Validation on startup: Ensure all configured paths exist and are git repositories
- Hot reload support: Watch file for changes and reload configuration

## Implementation Plan

### Phase 1: Core Infrastructure
1. Create repository configuration schema and JSON structure
2. Implement Repository Manager class for loading/validating config
3. Add URL routing logic to extract repository name from path
4. Update server startup to load and validate repository configuration

### Phase 2: Tool Integration  
1. Modify all GitHub tools to accept repository path as parameter
2. Update tool registration to be repository-agnostic
3. Ensure proper error handling when repository context is missing
4. Remove dependency on `LOCAL_REPO_PATH` environment variable

### Phase 3: Error Handling & UX
1. Return meaningful error messages for invalid repository names
2. Provide list of available repositories in error responses
3. Add repository validation (git repo check, permissions, etc.)
4. Add logging for repository access and errors

### Phase 4: Configuration Management
1. Implement configuration file hot reload
2. Add CLI commands for repository management (add/remove/list)
3. Create setup script updates for multi-repo configuration
4. Update documentation and examples

## Backward Compatibility

Maintain backward compatibility by:
- Supporting old single-repository mode when no config file exists
- Falling back to `LOCAL_REPO_PATH` environment variable if no config
- Providing migration script from single-repo to multi-repo setup

## Error Scenarios

1. **Invalid repository name**: Return 404 with list of available repositories
2. **Repository path doesn't exist**: Fail at startup with clear error message
3. **Repository not a git repo**: Fail at startup with validation error
4. **Permission issues**: Fail gracefully with permission error details
5. **Configuration file malformed**: Fail at startup with JSON validation errors

## Testing Strategy

1. Unit tests for Repository Manager and URL routing
2. Integration tests with multiple repository configurations
3. Error condition testing (missing repos, bad config, etc.)
4. Performance testing with large numbers of repositories
5. Backward compatibility testing with existing single-repo setups

## Considerations

### Security
- Validate repository paths to prevent directory traversal attacks
- Ensure users can only access explicitly configured repositories
- Consider adding access control per repository if needed

### Performance
- Repository configuration loaded once at startup
- No per-request file system lookups for validation
- Consider caching git repository metadata if needed

### UX
- Clear error messages help users understand configuration requirements
- Repository names should be intuitive and match project names
- Consider auto-discovery of repositories as future enhancement

## Future Enhancements

1. **Auto-discovery**: Scan common directories for git repositories
2. **Repository aliases**: Multiple names pointing to same repository
3. **Repository groups**: Organize repositories into logical groups
4. **Repository metadata**: Store additional info like branch, remote URL
5. **CLI management**: Commands to add/remove/list repositories via CLI
