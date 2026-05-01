# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "requests"]
# ///
"""
Apply the Authentik namespace-groups blueprint for a given namespace.

Usage:
    uv run scripts/apply-namespace-blueprint.py namespaces/payments-backend-dev/namespace.yaml

What it does:
  1. Reads the namespace YAML to extract naas.io/team and namespace name
  2. Creates 3 Authentik groups: naas-{namespace}-{admin,dev,viewer}
  3. Creates a manager Role naas-{namespace}-manager, assigned to naas-{team}-admin
  4. Grants the manager Role object-level permissions on those 3 groups so
     team admins can self-service manage membership in the Authentik UI

Env vars:
  AUTHENTIK_URL      Base URL (default: https://authentik.naas.local)
  AUTHENTIK_TOKEN    Authentik API token (required)
  AUTHENTIK_CA_CERT  Path to CA cert (default: ~/.kube/naas-local-ca.crt)
"""

import os
import sys
import time
import yaml
import requests
from pathlib import Path

BASE_URL = os.environ.get("AUTHENTIK_URL", "https://authentik.naas.local").rstrip("/")
CA_CERT = os.environ.get("AUTHENTIK_CA_CERT", str(Path.home() / ".kube/naas-local-ca.crt"))
TEMPLATE = Path(__file__).parent.parent / "authentik/blueprints/namespace-groups-template.yaml"

# Permissions the manager Role gets on each namespace group
MANAGER_PERMISSIONS = [
    "authentik_core.add_user_to_group",
    "authentik_core.remove_user_from_group",
    "authentik_core.view_group",
    "authentik_core.change_group",
]


def api(session: requests.Session, method: str, path: str, **kwargs):
    url = f"{BASE_URL}/api/v3{path}"
    r = session.request(method, url, **kwargs)
    if not r.ok:
        raise RuntimeError(f"{method} {path} → {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def get_session() -> requests.Session:
    token = os.environ.get("AUTHENTIK_TOKEN")
    if not token:
        print("Error: AUTHENTIK_TOKEN is not set.")
        print("Create a token at: Authentik Admin → Directory → Tokens → Create")
        print("Then: export AUTHENTIK_TOKEN=<token>")
        sys.exit(1)
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"
    s.verify = CA_CERT
    return s


def read_namespace(path: Path) -> tuple[str, str]:
    data = yaml.safe_load(path.read_text())
    name = data["metadata"]["name"]
    team = data["metadata"]["labels"]["naas.io/team"]
    return name, team


def ensure_group(session: requests.Session, name: str, namespace: str, team: str, role: str) -> str:
    """Create group if it doesn't exist, return its pk."""
    r = session.get(f"{BASE_URL}/api/v3/core/groups/", params={"name": name}, verify=CA_CERT)
    r.raise_for_status()
    results = r.json()["results"]
    if results:
        pk = results[0]["pk"]
        print(f"  group exists: {name} ({pk})")
        return pk

    r = session.post(
        f"{BASE_URL}/api/v3/core/groups/",
        json={
            "name": name,
            "is_superuser": False,
            "attributes": {"naas_namespace": namespace, "naas_team": team, "naas_role": role},
        },
        verify=CA_CERT,
    )
    r.raise_for_status()
    pk = r.json()["pk"]
    print(f"  created group: {name} ({pk})")
    return pk


def ensure_role(session: requests.Session, role_name: str, team_admin_group_pk: str) -> str:
    """Create manager Role if it doesn't exist and assign team-admin group to it."""
    r = session.get(f"{BASE_URL}/api/v3/rbac/roles/", params={"name": role_name}, verify=CA_CERT)
    r.raise_for_status()
    results = r.json()["results"]

    if results:
        role_pk = results[0]["pk"]
        print(f"  role exists: {role_name} ({role_pk})")
    else:
        r = session.post(
            f"{BASE_URL}/api/v3/rbac/roles/",
            json={"name": role_name},
            verify=CA_CERT,
        )
        r.raise_for_status()
        role_pk = r.json()["pk"]
        print(f"  created role: {role_name} ({role_pk})")

    # Assign the team-admin group to this role (idempotent: 400 = already assigned)
    r = session.post(
        f"{BASE_URL}/api/v3/rbac/roles/{role_pk}/add_user/",
        json={"pk": team_admin_group_pk},  # group pk treated as user-of-role
        verify=CA_CERT,
    )
    # Use groups M2M directly on the role via PATCH instead
    # Fetch current groups on role
    r2 = session.get(f"{BASE_URL}/api/v3/rbac/roles/{role_pk}/", verify=CA_CERT)
    r2.raise_for_status()
    existing_groups = [g["pk"] for g in r2.json().get("groups", [])]
    if team_admin_group_pk not in existing_groups:
        r3 = session.patch(
            f"{BASE_URL}/api/v3/rbac/roles/{role_pk}/",
            json={"groups": existing_groups + [team_admin_group_pk]},
            verify=CA_CERT,
        )
        if r3.ok:
            print(f"  assigned role to team-admin group")
        else:
            print(f"  warning: could not assign role to group: {r3.status_code} {r3.text[:100]}")

    return role_pk


def grant_object_permissions(
    session: requests.Session, role_pk: str, group_pks: list[str]
) -> None:
    """Grant the manager Role add/remove/view permissions on each namespace group."""
    for group_pk in group_pks:
        r = session.post(
            f"{BASE_URL}/api/v3/rbac/permissions/assigned_by_roles/{role_pk}/assign/",
            json={
                "permissions": MANAGER_PERMISSIONS,
                "model": "authentik_core.group",
                "object_pk": group_pk,
            },
            verify=CA_CERT,
        )
        if r.ok:
            print(f"  ✓ permissions granted on group {group_pk}")
        else:
            print(f"  ! permissions on {group_pk}: {r.status_code} {r.text[:100]}")


def write_blueprint_file(namespace: str, team: str) -> Path:
    """Write a concrete (no-variables) blueprint YAML next to the namespace.yaml."""
    out = Path(__file__).parent.parent / f"namespaces/{namespace}/authentik-groups.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    blueprint = {
        "version": 1,
        "metadata": {"name": f"naas-namespace-groups-{namespace}"},
        "entries": [
            {
                "model": "authentik_core.group",
                "state": "present",
                "identifiers": {"name": f"naas-{namespace}-{role}"},
                "attrs": {
                    "name": f"naas-{namespace}-{role}",
                    "is_superuser": False,
                    "attributes": {"naas_namespace": namespace, "naas_team": team, "naas_role": role},
                },
            }
            for role in ("admin", "dev", "viewer")
        ] + [
            {
                "model": "authentik_rbac.role",
                "state": "present",
                "identifiers": {"name": f"naas-{namespace}-manager"},
                "attrs": {
                    "name": f"naas-{namespace}-manager",
                    "groups": [{"!Find": ["authentik_core.group", ["name", f"naas-{team}-admin"]]}],
                },
            }
        ],
    }
    out.write_text(yaml.dump(blueprint, default_flow_style=False, sort_keys=False))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    ns_path = Path(sys.argv[1])
    if not ns_path.exists():
        print(f"File not found: {ns_path}")
        sys.exit(1)

    namespace, team = read_namespace(ns_path)
    print(f"Namespace : {namespace}")
    print(f"Team      : {team}")
    print()

    session = get_session()

    print("Creating namespace groups...")
    admin_pk = ensure_group(session, f"naas-{namespace}-admin", namespace, team, "admin")
    dev_pk = ensure_group(session, f"naas-{namespace}-dev", namespace, team, "developer")
    viewer_pk = ensure_group(session, f"naas-{namespace}-viewer", namespace, team, "viewer")

    print("\nResolving team-admin group...")
    r = session.get(f"{BASE_URL}/api/v3/core/groups/", params={"name": f"naas-{team}-admin"}, verify=CA_CERT)
    r.raise_for_status()
    results = r.json()["results"]
    if not results:
        print(f"  WARNING: naas-{team}-admin group not found — create it first")
        sys.exit(1)
    team_admin_pk = results[0]["pk"]
    print(f"  found: naas-{team}-admin ({team_admin_pk})")

    print("\nCreating manager role...")
    role_pk = ensure_role(session, f"naas-{namespace}-manager", team_admin_pk)

    print("\nGranting object-level permissions...")
    grant_object_permissions(session, role_pk, [admin_pk, dev_pk, viewer_pk])

    print("\nWriting blueprint file...")
    out = write_blueprint_file(namespace, team)
    print(f"  {out}")

    print(f"""
Done.

Groups:
  naas-{namespace}-admin   → k8s namespace-admin   (also via naas-{team}-admin)
  naas-{namespace}-dev     → k8s namespace-developer
  naas-{namespace}-viewer  → k8s namespace-viewer

Role naas-{namespace}-manager is assigned to naas-{team}-admin.
Members of naas-{team}-admin can now manage these 3 groups in Authentik:
  Admin UI → Directory → Groups → naas-{namespace}-* → Users tab
""")


if __name__ == "__main__":
    main()
