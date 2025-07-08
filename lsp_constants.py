"""
LSP Protocol Constants and Message Types

This module defines the essential constants and message types for Language Server Protocol
communication, following the LSP 3.17 specification.
"""

from enum import Enum
from typing import Any


class LSPErrorCode(Enum):
    """LSP Error Codes as defined in the specification."""

    # JSON-RPC Error Codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # LSP-specific Error Codes
    SERVER_NOT_INITIALIZED = -32002
    UNKNOWN_ERROR_CODE = -32001
    REQUEST_FAILED = -32803
    SERVER_CANCELLED = -32802
    CONTENT_MODIFIED = -32801
    REQUEST_CANCELLED = -32800


class LSPMessageType(Enum):
    """LSP Message Types for logging and notifications."""

    ERROR = 1
    WARNING = 2
    INFO = 3
    LOG = 4


class LSPMethod:
    """LSP Method Names as constants."""

    # General
    INITIALIZE = "initialize"
    INITIALIZED = "initialized"
    SHUTDOWN = "shutdown"
    EXIT = "exit"
    CANCEL_REQUEST = "$/cancelRequest"
    SET_TRACE = "$/setTrace"

    # Text Document Sync
    DID_OPEN = "textDocument/didOpen"
    DID_CHANGE = "textDocument/didChange"
    DID_CLOSE = "textDocument/didClose"
    DID_SAVE = "textDocument/didSave"
    WILL_SAVE = "textDocument/willSave"
    WILL_SAVE_WAIT_UNTIL = "textDocument/willSaveWaitUntil"

    # Language Features
    DEFINITION = "textDocument/definition"
    REFERENCES = "textDocument/references"
    HOVER = "textDocument/hover"
    COMPLETION = "textDocument/completion"
    COMPLETION_RESOLVE = "completionItem/resolve"
    SIGNATURE_HELP = "textDocument/signatureHelp"
    DOCUMENT_SYMBOLS = "textDocument/documentSymbol"
    CODE_ACTION = "textDocument/codeAction"
    RENAME = "textDocument/rename"
    FORMATTING = "textDocument/formatting"
    RANGE_FORMATTING = "textDocument/rangeFormatting"
    ON_TYPE_FORMATTING = "textDocument/onTypeFormatting"
    PUBLISH_DIAGNOSTICS = "textDocument/publishDiagnostics"

    # Workspace Features
    WORKSPACE_SYMBOLS = "workspace/symbol"
    DID_CHANGE_CONFIGURATION = "workspace/didChangeConfiguration"
    DID_CHANGE_WATCHED_FILES = "workspace/didChangeWatchedFiles"

    # Window Features
    SHOW_MESSAGE = "window/showMessage"
    SHOW_MESSAGE_REQUEST = "window/showMessageRequest"
    LOG_MESSAGE = "window/logMessage"
    PROGRESS = "$/progress"


class LSPCapabilities:
    """LSP Capabilities structure templates."""

    @staticmethod
    def client_capabilities() -> dict[str, Any]:
        """Default client capabilities."""
        return {
            "textDocument": {
                "synchronization": {
                    "dynamicRegistration": True,
                    "willSave": True,
                    "willSaveWaitUntil": True,
                    "didSave": True,
                },
                "completion": {
                    "dynamicRegistration": True,
                    "completionItem": {
                        "snippetSupport": True,
                        "commitCharactersSupport": True,
                        "documentationFormat": ["markdown", "plaintext"],
                    },
                },
                "hover": {
                    "dynamicRegistration": True,
                    "contentFormat": ["markdown", "plaintext"],
                },
                "definition": {"dynamicRegistration": True, "linkSupport": True},
                "references": {"dynamicRegistration": True},
                "documentSymbol": {
                    "dynamicRegistration": True,
                    "symbolKind": {
                        "valueSet": list(range(1, 26))  # All symbol kinds
                    },
                },
                "codeAction": {
                    "dynamicRegistration": True,
                    "codeActionLiteralSupport": {
                        "codeActionKind": {
                            "valueSet": [
                                "quickfix",
                                "refactor",
                                "refactor.extract",
                                "refactor.inline",
                                "refactor.rewrite",
                                "source",
                                "source.organizeImports",
                            ]
                        }
                    },
                },
                "publishDiagnostics": {
                    "relatedInformation": True,
                    "versionSupport": True,
                },
            },
            "workspace": {
                "applyEdit": True,
                "workspaceEdit": {
                    "documentChanges": True,
                    "resourceOperations": ["create", "rename", "delete"],
                    "failureHandling": "textOnlyTransactional",
                },
                "didChangeConfiguration": {"dynamicRegistration": True},
                "didChangeWatchedFiles": {"dynamicRegistration": True},
                "symbol": {
                    "dynamicRegistration": True,
                    "symbolKind": {
                        "valueSet": list(range(1, 26))  # All symbol kinds
                    },
                },
                "configuration": True,
                "workspaceFolders": True,
            },
            "window": {
                "showMessage": {
                    "messageActionItem": {"additionalPropertiesSupport": True}
                },
                "showDocument": {"support": True},
                "workDoneProgress": True,
            },
            "experimental": {},
        }


class LSPTextDocumentSyncKind(Enum):
    """Text document synchronization kind."""

    NONE = 0
    FULL = 1
    INCREMENTAL = 2


class LSPSymbolKind(Enum):
    """Symbol kinds for document and workspace symbols."""

    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRING = 15
    NUMBER = 16
    BOOLEAN = 17
    ARRAY = 18
    OBJECT = 19
    KEY = 20
    NULL = 21
    ENUM_MEMBER = 22
    STRUCT = 23
    EVENT = 24
    OPERATOR = 25
    TYPE_PARAMETER = 26


class LSPDiagnosticSeverity(Enum):
    """Diagnostic severity levels."""

    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


# JSON-RPC 2.0 Message Types
JsonRPCRequest = dict[str, Any]
JsonRPCResponse = dict[str, Any]
JsonRPCNotification = dict[str, Any]
JsonRPCMessage = JsonRPCRequest | JsonRPCResponse | JsonRPCNotification

# LSP-specific types
Position = dict[str, int]  # {"line": int, "character": int}
Range = dict[str, Position]  # {"start": Position, "end": Position}
Location = dict[str, str | Range]  # {"uri": str, "range": Range}
TextDocumentIdentifier = dict[str, str]  # {"uri": str}
VersionedTextDocumentIdentifier = dict[str, str | int]  # {"uri": str, "version": int}

# Common LSP request/response structures
InitializeParams = dict[str, Any]
InitializeResult = dict[str, Any]
CompletionParams = dict[str, Any]
CompletionList = dict[str, Any]
DefinitionParams = dict[str, Any]
ReferenceParams = dict[str, Any]
HoverParams = dict[str, Any]
DocumentSymbolParams = dict[str, Any]
