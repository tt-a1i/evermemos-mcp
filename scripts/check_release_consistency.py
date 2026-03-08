from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
INIT_PATH = REPO_ROOT / "src" / "evermemos_mcp" / "__init__.py"
SERVER_PATH = REPO_ROOT / "src" / "evermemos_mcp" / "server.py"


@dataclass(frozen=True)
class ReleaseCheck:
    path: Path
    required_substrings: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()


DOC_CHECKS = (
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "04-submission.md",
        required_substrings=("`v{version}`", "(7 tools)"),
        forbidden_patterns=(r"v0\.4\.3", r"\(6 tools\)"),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "04-submission.zh-CN.md",
        required_substrings=("`v{version}`", "（7 个 tools）"),
        forbidden_patterns=(r"v0\.4\.3", r"（6 个 tools）"),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "02-architecture.md",
        required_substrings=("all 7 tools",),
        forbidden_patterns=(r"all 6 tools",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "02-architecture.zh-CN.md",
        required_substrings=("7 个 tools",),
        forbidden_patterns=(r"6 个 tools",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "03-demo-playbook.zh-CN.md",
        required_substrings=("7 个 tools",),
        forbidden_patterns=(r"6 个 tools",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "03-demo-playbook.md",
        required_substrings=("7-tool loop",),
        forbidden_patterns=(r"6-tool loop",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "01-requirements.md",
        required_substrings=("Seven MCP tools", "request_status"),
        forbidden_patterns=(r"Six MCP tools",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "01-requirements.zh-CN.md",
        required_substrings=("七个 MCP tools", "request_status"),
        forbidden_patterns=(r"六个 MCP tools",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "07-release-checklist.md",
        required_substrings=("v{version}",),
        forbidden_patterns=(r"v0\.4\.3",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "competition" / "submission_draft.md",
        required_substrings=(
            "v{version}",
            "seven production-oriented MCP tools",
            "request_status",
        ),
        forbidden_patterns=(r"v0\.4\.3", r"six production-oriented MCP tools"),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "competition" / "task_plan.md",
        required_substrings=("v{version}",),
        forbidden_patterns=(r"v0\.4\.3",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "task_plan.md",
        required_substrings=("request_status", "all 7 MCP tools"),
        forbidden_patterns=(r"all 6 MCP tools",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "task_plan.zh-CN.md",
        required_substrings=("request_status", "7 个 tools 闭环"),
        forbidden_patterns=(r"6 个 tools 闭环",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "05-client-integrations.md",
        required_substrings=('"command": "uvx"', "evermemos-mcp@latest"),
        forbidden_patterns=(
            r'"command": "evermemos-mcp"',
            r"pin `evermemos-mcp@latest`",
        ),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "05-client-integrations.zh-CN.md",
        required_substrings=('"command": "uvx"', "evermemos-mcp@latest"),
        forbidden_patterns=(
            r'"command": "evermemos-mcp"',
            r"固定 `evermemos-mcp@latest`",
        ),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "mcp-config-snippets" / "README.md",
        required_substrings=("uvx evermemos-mcp@latest",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "mcp-config-snippets" / "README.zh-CN.md",
        required_substrings=("uvx evermemos-mcp@latest",),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "mcp-config-snippets" / "claude-code.json",
        required_substrings=('"command": "uvx"', "evermemos-mcp@latest"),
        forbidden_patterns=(r'"command": "evermemos-mcp"',),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "mcp-config-snippets" / "cursor.json",
        required_substrings=('"command": "uvx"', "evermemos-mcp@latest"),
        forbidden_patterns=(r'"command": "evermemos-mcp"',),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "docs" / "mcp-config-snippets" / "cline.json",
        required_substrings=('"command": "uvx"', "evermemos-mcp@latest"),
        forbidden_patterns=(r'"command": "evermemos-mcp"',),
    ),
    ReleaseCheck(
        path=REPO_ROOT / "scripts" / "smoke_test_tools.py",
        required_substrings=("all 7 tools",),
        forbidden_patterns=(r"all 6 tools",),
    ),
)


def read_project_version(pyproject_path: Path = PYPROJECT_PATH) -> str:
    content = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError(f"Could not parse version from {pyproject_path}")
    return match.group(1)


def read_init_version(init_path: Path = INIT_PATH) -> str:
    content = init_path.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', content)
    if not match:
        raise ValueError(f"Could not parse __version__ from {init_path}")
    return match.group(1)


def read_tool_count(server_path: Path = SERVER_PATH) -> int:
    content = server_path.read_text(encoding="utf-8")
    match = re.search(
        r"TOOLS:\s*list\[types\.Tool\]\s*=\s*\[(?P<body>.*)\n\]", content, re.DOTALL
    )
    if not match:
        raise ValueError(f"Could not parse TOOLS list from {server_path}")
    return match.group("body").count("types.Tool(")


def run_checks() -> list[str]:
    errors: list[str] = []
    version = read_project_version()
    init_version = read_init_version()
    if version != init_version:
        errors.append(
            f"Version mismatch: pyproject.toml has {version}, __init__.py has {init_version}"
        )

    tool_count = read_tool_count()
    if tool_count != 7:
        errors.append(
            f"Tool count mismatch: server.py defines {tool_count} tools, expected 7"
        )

    for check in DOC_CHECKS:
        content = check.path.read_text(encoding="utf-8")
        for template in check.required_substrings:
            required = template.format(version=version)
            if required not in content:
                errors.append(
                    f"Missing '{required}' in {check.path.relative_to(REPO_ROOT)}"
                )
        for pattern in check.forbidden_patterns:
            if re.search(pattern, content):
                errors.append(
                    f"Forbidden pattern /{pattern}/ found in {check.path.relative_to(REPO_ROOT)}"
                )

    return errors


def main() -> int:
    errors = run_checks()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Release consistency checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
