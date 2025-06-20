# Multi-Port Architecture for GitHub MCP Server

## Current State & Problems

The current multi-repository implementation uses a single server process with URL routing:
- Single server on port 8080
- URLs: `http://localhost:8080/mcp/repo-name/`
- MCP client compatibility issues with timeout errors
- Some repositories fail to complete handshake sequence

## Proposed Solution: One Port Per Repository

Implement a master-worker architecture where each repository gets its own dedicated server process and port:

### Architecture
- **Master Process**: `github_mcp_master.py` spawns and monitors worker processes
- **Worker Processes**: `github_mcp_worker.py` handles single repository on dedicated port
- **Clean URLs**: `http://localhost:8081/mcp/`, `http://localhost:8082/mcp/`
- **Process Isolation**: Repository issues don't affect other repositories

### Configuration Schema
```json
{
  "repositories": {
    "github-agent": {
      "path": "/Volumes/Code/github-agent",
      "port": 8081,
      "description": "GitHub Agent repository"
    },
    "news-reader": {
      "path": "/Volumes/Code/news_reader", 
      "port": 8082,
      "description": "News Reader repository"
    }
  }
}
```

## Implementation Plan

### Phase 1: Core Architecture
1. **Create Master Process (`github_mcp_master.py`)**
   - Read configuration and validate ports
   - Spawn worker processes for each repository
   - Monitor process health and restart failed workers
   - Handle graceful shutdown

2. **Create Worker Process (`github_mcp_worker.py`)**
   - Simplified single-repository server (no URL routing)
   - Accept repository config and port as parameters
   - Maintain existing tool functionality

### Phase 2: Service Integration
1. **Update Service Management**
   - Modify launchctl service to use master process
   - Ensure proper signal handling for graceful shutdown
   - Update service scripts

2. **Update CLI Tools**
   - Modify `repository_cli.py` to show port assignments
   - Add port conflict detection and validation
   - Update status reporting to show per-repository health

### Phase 3: Enhanced Features
1. **Logging & Monitoring**
   - Separate log files per repository: `logs/github-agent.log`, `logs/news-reader.log`
   - Master process logs: `logs/master.log`
   - Health check endpoints for each worker

2. **Configuration Management**
   - Hot reload: detect config changes and restart affected workers
   - Port assignment validation and conflict detection
   - Migration tools for existing single-port configurations

## Benefits

### Technical Benefits
- **Better Client Compatibility**: Each repository appears as separate MCP server
- **Process Isolation**: Issues in one repository don't affect others
- **Cleaner Architecture**: Simplified worker processes, clear separation of concerns
- **Easier Debugging**: Clear process boundaries and dedicated logs

### User Experience Benefits
- **Reliable Connections**: No more timeout issues with MCP handshakes
- **Independent Operation**: Can restart/debug individual repositories
- **Clean URLs**: Simpler endpoint management
- **Better Scalability**: Easy to add new repositories

## Migration Strategy

1. **Backward Compatibility**: Keep single-port mode as fallback if no ports specified
2. **Gradual Migration**: Existing configurations work, new configurations can specify ports
3. **Clear Documentation**: Update README with new configuration options
4. **Testing**: Comprehensive testing with different MCP clients

## Estimated Effort

- **Phase 1**: 4-6 hours (core master-worker implementation)
- **Phase 2**: 2-3 hours (service integration and CLI updates)  
- **Phase 3**: 3-4 hours (logging, monitoring, advanced features)
- **Total**: ~10-13 hours for complete implementation

## Success Criteria

1. ✅ Multiple repositories running on different ports simultaneously
2. ✅ MCP clients can connect reliably to each repository endpoint
3. ✅ Graceful process management (start, stop, restart, health monitoring)
4. ✅ Backward compatibility with existing single-port configurations
5. ✅ Clear logging and debugging capabilities
6. ✅ Easy configuration management through CLI tools
