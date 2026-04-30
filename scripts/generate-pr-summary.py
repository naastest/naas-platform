#!/usr/bin/env python3
"""Generate a PR summary listing what will be provisioned for new/changed namespace files.

Compares changed files against git HEAD and prints a Markdown summary.
"""
import sys
import os
import glob
import subprocess
import yaml


TIER_QUOTAS = {
    "backend":  {"requests.cpu": "4", "requests.memory": "8Gi", "limits.cpu": "8", "limits.memory": "16Gi", "pods": "50"},
    "frontend": {"requests.cpu": "2", "requests.memory": "4Gi", "limits.cpu": "4", "limits.memory": "8Gi", "pods": "30"},
    "data":     {"requests.cpu": "8", "requests.memory": "32Gi", "limits.cpu": "16", "limits.memory": "64Gi", "pods": "20"},
    "infra":    {"requests.cpu": "16", "requests.memory": "64Gi", "limits.cpu": "32", "limits.memory": "128Gi", "pods": "100"},
}

ENV_QUOTAS = {
    "dev":        "small (cpu:4/8, memory:8Gi/16Gi)",
    "test":       "medium (cpu:8/16, memory:16Gi/32Gi)",
    "acceptance": "large (cpu:16/32, memory:32Gi/64Gi)",
    "production": "xlarge (cpu:32/64, memory:64Gi/128Gi)",
}


def get_changed_files(base: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"origin/{base}...HEAD", "--", "namespaces/**/*.yaml"],
            capture_output=True, text=True
        )
        return [f for f in result.stdout.strip().split("\n") if f.endswith(".yaml")]
    except Exception:
        return []


def summarize_namespace(path: str) -> str | None:
    try:
        with open(path) as f:
            doc = yaml.safe_load(f)
    except Exception:
        return None

    if not isinstance(doc, dict) or doc.get("kind") != "Namespace":
        return None

    labels = doc.get("metadata", {}).get("labels", {}) or {}
    name = doc.get("metadata", {}).get("name", path)
    team = labels.get("naas.io/team", "?")
    env = labels.get("naas.io/env", "?")
    tier = labels.get("naas.io/tier", "?")
    compliance = labels.get("naas.io/compliance", "standard")

    quota = ENV_QUOTAS.get(env, "?")

    lines = [
        f"### `{name}`",
        f"- **Team**: `{team}` | **Env**: `{env}` | **Tier**: `{tier}` | **Compliance**: `{compliance}`",
        "- **Will generate:**",
        f"  - ResourceQuota: {quota}",
        f"  - LimitRange: {tier} tier defaults",
        "  - NetworkPolicy: default-deny-all, allow-same-namespace, allow-dns-egress",
        f"  - RoleBindings: `naas-{team}-admin`, `naas-{team}-dev`, `naas-{team}-viewer`",
        f"  - Authentik groups: `naas-{team}-admin`, `naas-{team}-dev`, `naas-{team}-viewer`",
    ]
    if compliance == "pci":
        lines.append("  - **PCI extras**: strict egress NetworkPolicy, Pod Security Admission: restricted")
    elif compliance == "hipaa":
        lines.append("  - **HIPAA extras**: audit annotation, Pod Security Admission: restricted")

    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    base_ref = os.environ.get("GITHUB_BASE_REF", "main")

    changed = get_changed_files(base_ref)
    if not changed:
        # Fall back to scanning all namespaces if not running in CI
        root = args[0] if args else "namespaces/"
        changed = glob.glob(os.path.join(root, "**", "namespace.yaml"), recursive=True)

    summaries = []
    for f in sorted(changed):
        if os.path.exists(f):
            s = summarize_namespace(f)
            if s:
                summaries.append(s)

    if not summaries:
        print("No namespace changes detected.")
        return

    print(f"**{len(summaries)} namespace(s) will be provisioned:**\n")
    for s in summaries:
        print(s)
        print()


if __name__ == "__main__":
    main()
