#!/usr/bin/env python3
"""Validate namespace YAML files against the NaaS label schema.

Usage:
    python3 scripts/validate-namespace-labels.py namespaces/
    python3 scripts/validate-namespace-labels.py namespaces/dev/payments-backend/namespace.yaml
"""
import sys
import os
import re
import glob
import yaml

REQUIRED_LABELS = {
    "naas.io/team": r"^[a-z][a-z0-9-]{1,30}$",
    "naas.io/env": r"^(dev|test|acceptance|production)$",
    "naas.io/tier": r"^(backend|frontend|data|infra)$",
    "naas.io/app": r"^[a-z][a-z0-9-]{1,60}$",
    "naas.io/cost-center": r"^.+$",
    "naas.io/compliance": r"^(standard|pci|hipaa)$",
    "naas.io/owner-email": r"^[^@]+@[^@]+\.[^@]+$",
}

NAMING_PATTERN = re.compile(r"^[a-z][a-z0-9-]+-[a-z]+-[a-z]+$")

SYSTEM_NAMESPACES = {
    "kube-system", "kube-public", "kube-node-lease",
    "argocd", "kyverno", "cert-manager", "ingress-nginx",
    "authentik", "capsule-system", "monitoring", "sealed-secrets",
}


def validate_file(path: str) -> list[str]:
    errors = []
    with open(path) as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return [f"YAML parse error: {e}"]

    if not isinstance(doc, dict) or doc.get("kind") != "Namespace":
        return []  # skip non-namespace files

    name = doc.get("metadata", {}).get("name", "")
    if name in SYSTEM_NAMESPACES:
        return []  # system namespaces are exempt

    # Check namespace name convention: {team}-{tier}-{env}
    if name and not NAMING_PATTERN.match(name):
        errors.append(f"  name '{name}' does not match pattern {{team}}-{{tier}}-{{env}}")

    labels = doc.get("metadata", {}).get("labels", {}) or {}

    for label, pattern in REQUIRED_LABELS.items():
        value = labels.get(label)
        if value is None:
            errors.append(f"  missing required label: {label}")
        elif not re.match(pattern, str(value)):
            errors.append(f"  label {label}='{value}' does not match allowed values: {pattern}")

    # Check that namespace name env suffix matches naas.io/env label
    env_label = labels.get("naas.io/env", "")
    if name and env_label and not name.endswith(f"-{env_label}"):
        errors.append(
            f"  namespace name '{name}' does not end with env suffix '-{env_label}'"
        )

    return errors


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: validate-namespace-labels.py <path-or-dir> [...]")
        sys.exit(1)

    files = []
    for arg in args:
        if os.path.isfile(arg):
            files.append(arg)
        elif os.path.isdir(arg):
            for f in glob.glob(os.path.join(arg, "**", "namespace.yaml"), recursive=True):
                # Skip template directory
                if "_template" not in f.split(os.sep):
                    files.append(f)
        else:
            print(f"WARNING: {arg} not found")

    all_ok = True
    for f in sorted(files):
        errors = validate_file(f)
        if errors:
            all_ok = False
            print(f"FAIL {f}")
            for e in errors:
                print(e)
        else:
            print(f"OK   {f}")

    if not all_ok:
        sys.exit(1)

    print(f"\nAll {len(files)} namespace file(s) valid.")


if __name__ == "__main__":
    main()
