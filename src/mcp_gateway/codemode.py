"""Code Mode engine — sandboxed Python execution against OpenAPI specs and API clients."""
from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Dict, Optional

import httpx


# Dangerous names that must never appear in user code
_BLOCKED_NAMES = frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib", "importlib",
    "ctypes", "socket", "signal", "threading", "multiprocessing",
    "__import__", "eval", "exec", "compile", "globals", "locals",
    "getattr", "setattr", "delattr", "open", "breakpoint",
    "__builtins__", "__loader__", "__spec__",
})

_BLOCKED_ATTRS = frozenset({
    "__subclasses__", "__bases__", "__mro__", "__class__",
    "__code__", "__globals__", "__closure__",
})

_SAFE_BUILTINS: Dict[str, Any] = {
    "True": True, "False": False, "None": None,
    "int": int, "float": float, "str": str, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set, "frozenset": frozenset,
    "len": len, "range": range, "enumerate": enumerate, "zip": zip,
    "map": map, "filter": filter, "sorted": sorted, "reversed": reversed,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    "any": any, "all": all, "isinstance": isinstance, "type": type,
    "print": print,  # captured via stdout redirect
    "hasattr": hasattr,
}


class SandboxViolation(Exception):
    """Raised when user code tries something disallowed."""


class _CodeValidator(ast.NodeVisitor):
    """AST visitor that rejects dangerous constructs."""

    def visit_Import(self, node: ast.Import) -> None:
        raise SandboxViolation(f"import not allowed: {ast.dump(node)}")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise SandboxViolation(f"import not allowed: from {node.module}")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _BLOCKED_NAMES:
            raise SandboxViolation(f"access to '{node.id}' is not allowed")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _BLOCKED_ATTRS:
            raise SandboxViolation(f"access to '.{node.attr}' is not allowed")
        self.generic_visit(node)


def _validate_code(code: str) -> ast.Module:
    """Parse and validate code, returning the AST if safe."""
    tree = ast.parse(code, mode="exec")
    _CodeValidator().visit(tree)
    return tree


@dataclass
class CodeResult:
    success: bool
    output: Any = None
    error: Optional[str] = None
    execution_ms: float = 0.0


class ApiClient:
    """Controlled HTTP client exposed to execute() sandbox."""

    def __init__(self, base_url: str, tenant_id: str, headers: Dict[str, str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self._headers = {"x-tenant-id": tenant_id, **(headers or {})}

    def get(self, path: str, **kwargs: Any) -> dict:
        with httpx.Client(base_url=self.base_url, headers=self._headers, timeout=30) as c:
            r = c.get(path, **kwargs)
            r.raise_for_status()
            return r.json()

    def post(self, path: str, **kwargs: Any) -> dict:
        with httpx.Client(base_url=self.base_url, headers=self._headers, timeout=30) as c:
            r = c.post(path, **kwargs)
            r.raise_for_status()
            return r.json()

    def put(self, path: str, **kwargs: Any) -> dict:
        with httpx.Client(base_url=self.base_url, headers=self._headers, timeout=30) as c:
            r = c.put(path, **kwargs)
            r.raise_for_status()
            return r.json()

    def delete(self, path: str, **kwargs: Any) -> dict:
        with httpx.Client(base_url=self.base_url, headers=self._headers, timeout=30) as c:
            r = c.delete(path, **kwargs)
            r.raise_for_status()
            return r.json()


class CodeModeExecutor:
    """Sandboxed Python code executor for Code Mode."""

    def search(self, code: str, spec: dict) -> CodeResult:
        """Execute code against an OpenAPI spec for progressive discovery."""
        return self._run(code, {"spec": spec})

    def execute(self, code: str, api_client: ApiClient, tenant_id: str) -> CodeResult:
        """Execute code that can call APIs via the provided client."""
        return self._run(code, {"api": api_client, "tenant_id": tenant_id})

    def _run(self, code: str, namespace_extras: Dict[str, Any]) -> CodeResult:
        start = time.monotonic()
        try:
            tree = _validate_code(code)
        except SandboxViolation as exc:
            return CodeResult(success=False, error=f"Sandbox violation: {exc}",
                              execution_ms=(time.monotonic() - start) * 1000)
        except SyntaxError as exc:
            return CodeResult(success=False, error=f"Syntax error: {exc}",
                              execution_ms=(time.monotonic() - start) * 1000)

        namespace: Dict[str, Any] = {**_SAFE_BUILTINS, **namespace_extras}
        # Capture result via special `_result` variable
        buf = StringIO()
        namespace["print"] = lambda *a, **kw: buf.write(" ".join(str(x) for x in a) + kw.get("end", "\n"))
        compiled = compile(tree, "<codemode>", "exec")
        try:
            exec(compiled, {"__builtins__": {}}, namespace)  # noqa: S102
        except Exception as exc:
            return CodeResult(success=False, error=str(exc),
                              execution_ms=(time.monotonic() - start) * 1000)

        output = namespace.get("result", None)
        printed = buf.getvalue()
        if output is None and printed:
            output = printed.rstrip("\n")

        return CodeResult(success=True, output=output,
                          execution_ms=(time.monotonic() - start) * 1000)
