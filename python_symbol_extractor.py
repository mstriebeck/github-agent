"""
Python AST-based symbol extraction for MCP codebase server.

This module provides functionality to parse Python files and extract
symbols (classes, functions, methods, variables) using the Python AST.
"""

import ast
import logging
from abc import ABC, abstractmethod

from symbol_storage import Symbol

logger = logging.getLogger(__name__)


class AbstractSymbolExtractor(ABC):
    """Abstract base class for symbol extraction."""

    @abstractmethod
    def extract_from_file(self, file_path: str, repository_id: str) -> list[Symbol]:
        """Extract symbols from a Python file."""
        pass

    @abstractmethod
    def extract_from_source(
        self, source: str, file_path: str, repository_id: str
    ) -> list[Symbol]:
        """Extract symbols from Python source code."""
        pass


class PythonSymbolExtractor(AbstractSymbolExtractor):
    """Python AST-based symbol extractor."""

    def __init__(self):
        """Initialize the Python symbol extractor."""
        self.symbols: list[Symbol] = []
        self.current_file_path = ""
        self.current_repository_id = ""
        self.scope_stack: list[str] = []  # Track nested scopes
        self.scope_types: list[str] = []  # Track scope types (class/function)

    def extract_from_file(self, file_path: str, repository_id: str) -> list[Symbol]:
        """Extract symbols from a Python file.

        Args:
            file_path: Path to the Python file
            repository_id: Repository identifier

        Returns:
            List of extracted symbols

        Raises:
            FileNotFoundError: If file doesn't exist
            SyntaxError: If file contains invalid Python syntax
            UnicodeDecodeError: If file encoding is unsupported
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                source = f.read()
            return self.extract_from_source(source, file_path, repository_id)
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except UnicodeDecodeError as e:
            logger.error(f"Encoding error reading {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            raise

    def extract_from_source(
        self, source: str, file_path: str, repository_id: str
    ) -> list[Symbol]:
        """Extract symbols from Python source code.

        Args:
            source: Python source code
            file_path: Path to the file (for reference)
            repository_id: Repository identifier

        Returns:
            List of extracted symbols

        Raises:
            SyntaxError: If source contains invalid Python syntax
        """
        self.symbols = []
        self.current_file_path = file_path
        self.current_repository_id = repository_id
        self.scope_stack = []
        self.scope_types = []

        try:
            tree = ast.parse(source, filename=file_path)
            self.visit_node(tree)
            logger.debug(f"Extracted {len(self.symbols)} symbols from {file_path}")
            return self.symbols.copy()
        except SyntaxError as e:
            logger.error(f"Syntax error in {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")
            raise

    def visit_node(self, node: ast.AST) -> None:
        """Visit an AST node and extract symbols."""
        if isinstance(node, ast.ClassDef):
            self._visit_class(node)
        elif isinstance(node, ast.FunctionDef):
            self._visit_function(node)
        elif isinstance(node, ast.AsyncFunctionDef):
            self._visit_async_function(node)
        elif isinstance(node, ast.Assign):
            self._visit_assignment(node)
        elif isinstance(node, ast.AnnAssign):
            self._visit_annotated_assignment(node)
        elif isinstance(node, ast.Import):
            self._visit_import(node)
        elif isinstance(node, ast.ImportFrom):
            self._visit_import_from(node)
        elif isinstance(node, ast.AugAssign):
            self._visit_augmented_assignment(node)
        else:
            # For nodes we don't handle directly, visit children
            for child in ast.iter_child_nodes(node):
                self.visit_node(child)

    def _visit_class(self, node: ast.ClassDef) -> None:
        """Visit a class definition."""
        class_name = node.name
        full_name = self._get_full_name(class_name)
        docstring = self._extract_docstring(node)

        symbol = Symbol(
            name=full_name,
            kind="class",
            file_path=self.current_file_path,
            line_number=node.lineno,
            column_number=node.col_offset,
            repository_id=self.current_repository_id,
            docstring=docstring,
        )
        self.symbols.append(symbol)

        # Enter class scope
        self.scope_stack.append(class_name)
        self.scope_types.append("class")

        # Visit class body for methods and nested classes
        for item in node.body:
            self.visit_node(item)

        # Exit class scope
        self.scope_stack.pop()
        self.scope_types.pop()

    def _visit_function(self, node: ast.FunctionDef) -> None:
        """Visit a function definition."""
        self._process_function(node, "function")

    def _visit_async_function(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an async function definition."""
        self._process_function(node, "function")

    def _process_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, base_kind: str
    ) -> None:
        """Process function or method definition."""
        func_name = node.name
        full_name = self._get_full_name(func_name)
        docstring = self._extract_docstring(node)

        # Determine if this is a method, property, classmethod, or staticmethod
        kind = self._determine_function_kind(node, base_kind)

        symbol = Symbol(
            name=full_name,
            kind=kind,
            file_path=self.current_file_path,
            line_number=node.lineno,
            column_number=node.col_offset,
            repository_id=self.current_repository_id,
            docstring=docstring,
        )
        self.symbols.append(symbol)

        # Enter function scope
        self.scope_stack.append(func_name)
        self.scope_types.append("function")

        # Visit function body for nested functions
        for item in node.body:
            self.visit_node(item)

        # Exit function scope
        self.scope_stack.pop()
        self.scope_types.pop()

    def _visit_assignment(self, node: ast.Assign) -> None:
        """Visit a regular assignment."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                full_name = self._get_full_name(var_name)
                kind = self._determine_variable_kind(var_name, node)

                symbol = Symbol(
                    name=full_name,
                    kind=kind,
                    file_path=self.current_file_path,
                    line_number=node.lineno,
                    column_number=node.col_offset,
                    repository_id=self.current_repository_id,
                )
                self.symbols.append(symbol)
            elif isinstance(target, ast.Attribute):
                # Handle attribute assignments like self.var = value
                if isinstance(target.value, ast.Name) and target.value.id == "self":
                    attr_name = target.attr
                    full_name = self._get_full_name(attr_name)
                    kind = self._determine_variable_kind(attr_name, node)

                    symbol = Symbol(
                        name=full_name,
                        kind=kind,
                        file_path=self.current_file_path,
                        line_number=node.lineno,
                        column_number=node.col_offset,
                        repository_id=self.current_repository_id,
                    )
                    self.symbols.append(symbol)

    def _visit_annotated_assignment(self, node: ast.AnnAssign) -> None:
        """Visit an annotated assignment."""
        if isinstance(node.target, ast.Name):
            var_name = node.target.id
            full_name = self._get_full_name(var_name)
            kind = self._determine_variable_kind(var_name, node)

            symbol = Symbol(
                name=full_name,
                kind=kind,
                file_path=self.current_file_path,
                line_number=node.lineno,
                column_number=node.col_offset,
                repository_id=self.current_repository_id,
            )
            self.symbols.append(symbol)
        elif isinstance(node.target, ast.Attribute):
            # Handle attribute assignments like self.var: int = value
            if (
                isinstance(node.target.value, ast.Name)
                and node.target.value.id == "self"
            ):
                attr_name = node.target.attr
                full_name = self._get_full_name(attr_name)
                kind = self._determine_variable_kind(attr_name, node)

                symbol = Symbol(
                    name=full_name,
                    kind=kind,
                    file_path=self.current_file_path,
                    line_number=node.lineno,
                    column_number=node.col_offset,
                    repository_id=self.current_repository_id,
                )
                self.symbols.append(symbol)

    def _visit_import(self, node: ast.Import) -> None:
        """Visit an import statement."""
        for alias in node.names:
            import_name = alias.name
            alias_name = alias.asname if alias.asname else import_name

            symbol = Symbol(
                name=alias_name,
                kind="module",
                file_path=self.current_file_path,
                line_number=node.lineno,
                column_number=node.col_offset,
                repository_id=self.current_repository_id,
            )
            self.symbols.append(symbol)

    def _visit_import_from(self, node: ast.ImportFrom) -> None:
        """Visit a from-import statement."""
        for alias in node.names:
            import_name = alias.name
            alias_name = alias.asname if alias.asname else import_name

            # Skip wildcard imports
            if import_name == "*":
                continue

            symbol = Symbol(
                name=alias_name,
                kind="module",
                file_path=self.current_file_path,
                line_number=node.lineno,
                column_number=node.col_offset,
                repository_id=self.current_repository_id,
            )
            self.symbols.append(symbol)

    def _visit_augmented_assignment(self, node: ast.AugAssign) -> None:
        """Visit an augmented assignment (e.g., +=)."""
        if isinstance(node.target, ast.Name):
            var_name = node.target.id
            full_name = self._get_full_name(var_name)
            kind = self._determine_variable_kind(var_name, node)

            symbol = Symbol(
                name=full_name,
                kind=kind,
                file_path=self.current_file_path,
                line_number=node.lineno,
                column_number=node.col_offset,
                repository_id=self.current_repository_id,
            )
            self.symbols.append(symbol)

    def _get_full_name(self, name: str) -> str:
        """Get the fully qualified name including scope."""
        if self.scope_stack:
            return ".".join(self.scope_stack) + "." + name
        return name

    def _extract_docstring(
        self, node: ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef
    ) -> str | None:
        """Extract docstring from a function or class."""
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            return node.body[0].value.value
        return None

    def _determine_function_kind(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, base_kind: str
    ) -> str:
        """Determine the specific kind of function (method, property, etc.)."""
        # Only consider it a method if we're directly inside a class
        if self.scope_types and self.scope_types[-1] == "class":
            # Check for decorators (property has priority)
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name):
                    if decorator.id == "property":
                        return "property"
                    elif decorator.id == "classmethod":
                        return "classmethod"
                    elif decorator.id == "staticmethod":
                        return "staticmethod"
                elif isinstance(decorator, ast.Attribute):
                    if decorator.attr in ["property", "classmethod", "staticmethod"]:
                        return decorator.attr

            # If directly inside a class but no special decorators, it's a method
            return "method"

        return base_kind

    def _determine_variable_kind(self, var_name: str, node: ast.AST) -> str:
        """Determine if a variable is a constant or regular variable."""
        # Python convention: ALL_CAPS names are constants
        if var_name.isupper() and "_" in var_name:
            return "constant"
        elif var_name.isupper():
            return "constant"
        return "variable"


class MockSymbolExtractor(AbstractSymbolExtractor):
    """Mock symbol extractor for testing."""

    def __init__(self, symbols: list[Symbol] | None = None):
        """Initialize mock extractor with predefined symbols."""
        self.symbols = symbols or []

    def extract_from_file(self, file_path: str, repository_id: str) -> list[Symbol]:
        """Return predefined symbols."""
        return self.symbols.copy()

    def extract_from_source(
        self, source: str, file_path: str, repository_id: str
    ) -> list[Symbol]:
        """Return predefined symbols."""
        return self.symbols.copy()
