#!/usr/bin/env python3
"""
PR Review Agent - Import Verification Script
Verifies that all required Python imports are available and the main server script is valid.
"""

import sys
from pathlib import Path

def main():
    """Main verification function"""
    
    # Get the script directory (parent of setup directory)
    script_dir = Path(__file__).parent.parent
    
    # Add the main directory to Python path
    sys.path.insert(0, str(script_dir))
    
    try:
        # Test required imports
        import mcp  # noqa: F401
        import github  # noqa: F401
        import git  # noqa: F401
        import requests  # noqa: F401
        import pydantic  # noqa: F401
        print("All required libraries are available")
        
        # Test main server script import
        import github_mcp_server  # noqa: F401
        print("PR agent server script is valid")
        
        return 0
        
    except ImportError as e:
        print(f"Import Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
