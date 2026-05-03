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

# Object-level permissions the manager Role gets on each namespace group
MANAGER_PERMISSIONS = [
    "authentik_core.add_user_to_group",
    "authentik_core.remove_user_from_group",
    "authentik_core.view_group",
    "authentik_core.change_group",
]

# Global (non-object) permissions the manager Role gets.
# access_admin_interface: required for the admin UI button to appear.
# view_user: required to list/search users when adding them to a group.
#   (object-level add_user_to_group alone isn't enough — the user picker calls
#    GET /api/v3/core/users/ which requires global view_user)
MANAGER_GLOBAL_PERMISSIONS = [
    "authentik_rbac.access_admin_interface",
    "authentik_core.view_user",
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
    """Create manager Role if it doesn't exist and assign it to the team-admin group.

    Authentik's RBAC model: roles are assigned via Group.roles (M2M), not Role.groups.
    Patching the group (not the role) is the correct direction.
    Any group member with at least one role/permission gets access to the Authentik
    admin UI, scoped to the objects they have permissions on (Authentik 2023.6+).
    """
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

    # Add the role to the team-admin group's roles list (append, don't replace).
    r2 = session.get(f"{BASE_URL}/api/v3/core/groups/{team_admin_group_pk}/", verify=CA_CERT)
    r2.raise_for_status()
    raw_roles = r2.json().get("roles", [])
    # API may return roles as list of PKs or list of objects depending on serializer depth
    existing_role_pks = [r["pk"] if isinstance(r, dict) else r for r in raw_roles]
    if role_pk not in existing_role_pks:
        r3 = session.patch(
            f"{BASE_URL}/api/v3/core/groups/{team_admin_group_pk}/",
            json={"roles": existing_role_pks + [role_pk]},
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
            print(f"  ✓ object permissions granted on group {group_pk}")
        else:
            print(f"  ! object permissions on {group_pk}: {r.status_code} {r.text[:100]}")


def grant_global_permissions(session: requests.Session, role_pk: str) -> None:
    """Grant global (non-object) permissions to the manager Role.

    access_admin_interface is required for the Authentik admin UI button to appear.
    Without it, is_staff stays False and users see only the user portal.
    """
    r = session.post(
        f"{BASE_URL}/api/v3/rbac/permissions/assigned_by_roles/{role_pk}/assign/",
        json={"permissions": MANAGER_GLOBAL_PERMISSIONS},
        verify=CA_CERT,
    )
    if r.ok:
        print(f"  ✓ global permissions granted: {MANAGER_GLOBAL_PERMISSIONS}")
    else:
        print(f"  ! global permissions: {r.status_code} {r.text[:100]}")


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

    print("\nResolving team-level groups...")
    team_group_pks = []
    team_admin_pk = None
    for suffix in ("admin", "dev", "viewer"):
        r = session.get(f"{BASE_URL}/api/v3/core/groups/", params={"name": f"naas-{team}-{suffix}"}, verify=CA_CERT)
        r.raise_for_status()
        results = r.json()["results"]
        if results:
            pk = results[0]["pk"]
            team_group_pks.append(pk)
            if suffix == "admin":
                team_admin_pk = pk
            print(f"  found: naas-{team}-{suffix} ({pk})")
        else:
            print(f"  WARNING: naas-{team}-{suffix} not found — skipping")
    if not team_admin_pk:
        print(f"  ERROR: naas-{team}-admin group not found — create it first")
        sys.exit(1)

    print("\nCreating manager role...")
    role_pk = ensure_role(session, f"naas-{namespace}-manager", team_admin_pk)

    print("\nGranting object-level permissions (namespace groups + tenant groups)...")
    grant_object_permissions(session, role_pk, [admin_pk, dev_pk, viewer_pk] + team_group_pks)

    print("\nGranting global permissions...")
    grant_global_permissions(session, role_pk)

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
