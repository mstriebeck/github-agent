# CLAUDE.md - Python Coding Agent Guidelines

This document outlines the essential guidelines and procedures for working with this Python codebase as a coding agent.

## Project Structure

- **Codebase**: Python
- **Tests**: Located under `tests/`
- **Virtual Environment**: `.venv/`
- **Log Files**: `~/.local/share/github-agent/logs`
- **Scripts**: Various automation scripts under `scripts/`

## Core Principles

### Testing Requirements
- **ALL functionality MUST be covered by tests**
- **NEVER modify test code to make a test pass**
- Always check back and get **explicit approval** before changing any test code
- Tests must run without failures AND without Python warnings
- Run all tests before any code commits

### Type Annotations
Use modern Python type annotations:
- ✅ `| None` instead of `Optional[T]`
- ✅ `dict` instead of `Dict`
- ✅ `list` instead of `List`

```python
# Good
def process_data(items: list[str] | None) -> dict[str, int]:
    pass

# Avoid
from typing import Optional, Dict, List
def process_data(items: Optional[List[str]]) -> Dict[str, int]:
    pass
```

## Development Workflow

### Environment Setup
- Always work within the virtual environment under `.venv/`
- Never run code outside of this environment

### Code Quality Checks (Pre-commit)
Before committing any code, run these scripts in order:

1. **Auto-format code**:
   ```bash
   scripts/ruff-autofix.sh
   ```

2. **Run linting checks**:
   ```bash
   scripts/run-code-checks.sh
   ```
   - Ignore bandit warnings and error messages as instructed
   - Address all other linting issues

3. **Run all tests**:
   - Execute the full test suite
   - Fix any test failures
   - Resolve any Python warnings that appear during testing

### Deployment
- **NEVER run the service manually**
- Always use: `scripts/deploy.sh`
- **Get confirmation before running deployment script**

## Commit Process

### When to Commit
Commit code at opportune times when:
- All tests pass without failures
- No Python warnings are present
- Code quality checks are clean

### Commit Procedure
1. Stage your changes
2. Write a comprehensive commit message that includes:
   - Clear description of changes made
   - Any new functionality added
   - Bug fixes implemented
   - Impact on existing code
   - Test coverage updates

### Example Commit Message Format
```
feat: Add user authentication module

- Implement JWT-based authentication system
- Add password hashing with bcrypt
- Create user login/logout endpoints
- Add comprehensive test coverage for auth flows
- Update API documentation for new endpoints

Tests: All 47 tests passing
Coverage: Authentication module at 100%
```

## Testing Guidelines

### Test Coverage
- Every function, method, and class must have corresponding tests
- Edge cases and error conditions must be tested
- Integration tests for complex workflows

### Usage of mock libraries (e.g. unittest.mock)
- Only use mocking libraries for mocking out external resources (e.g. file system or http request)
- For our own objects, we don't use mocking libraries but create and abstract base class of the object and then create a mock version of the object. We use dependency injection to be able to pass in the real objects in production and the mock objects in tests.

### Test Modification Policy
- **CRITICAL**: Never change test code to make failing tests pass
- If tests need modification, always seek explicit approval first
- Document the reason for any approved test changes

### Test Execution
- Run tests frequently during development
- Ensure tests pass in the virtual environment
- Address both test failures and Python warnings

## Code Style Standards

### Formatting
- Use `scripts/ruff-autofix.sh` for consistent formatting
- Follow PEP 8 guidelines
- Use modern Python features and syntax

### Type Safety
- Include type hints for all function parameters and return types
- Use the newer type annotation syntax
- Leverage type checking tools

## Logging and Debugging

- Log files are stored in: `~/.local/share/github-agent/logs`
- Use appropriate logging levels
- Include contextual information in log messages

## Error Handling

- Implement proper exception handling
- Use specific exception types
- Provide meaningful error messages
- Log errors appropriately

## Documentation

- Update docstrings for new or modified functions
- Keep README and other documentation current
- Document any breaking changes

## Checklist Before Each Commit

- [ ] All code runs in `.venv` virtual environment
- [ ] Ran `scripts/ruff-autofix.sh` successfully
- [ ] Ran `scripts/run-code-checks.sh` (ignored bandit warnings)
- [ ] All tests pass without failures
- [ ] No Python warnings during test execution
- [ ] Test coverage maintained for new/modified code
- [ ] No test code was modified to make tests pass
- [ ] Used modern type annotations (`| None`, `dict`, `list`)
- [ ] Comprehensive commit message prepared
- [ ] Got approval for deployment if using `scripts/deploy.sh`

## Emergency Procedures

If you need to modify test code:
1. **STOP** - Do not proceed
2. Clearly explain why the test modification is necessary
3. Wait for **explicit approval**
4. Document the approved change thoroughly

## Contact and Approvals

Always seek explicit approval for:
- Test code modifications
- Running deployment scripts
- Major architectural changes
- Breaking changes to existing APIs

---

**Remember**: Code quality and test integrity are paramount. When in doubt, ask for clarification rather than making assumptions.
