"""cluster_sync.py — sync LAN-discovered nodes into the manual cluster registry

Bridges lan_discovery (auto-scan) ↔ cluster_store (manual registry + health).
Calling sync_discovered() runs a full subnet scan then auto-registers any new
LCA nodes it finds — skipping nodes already in the registry.

Interface:
    sync_discovered(project_root, base_ip, port, timeout, max_threads) -> dict
    # Returns:
    #   {added, existing, scanned, elapsed_s}           — success
    #   {added, existing, scanned, elapsed_s, error}    — scan error (bad base_ip etc.)
"""

from __future__ import annotations

from pathlib import Path

from app import cluster_store, lan_discovery


def sync_discovered(
    project_root: Path,
    base_ip: str | None = None,
    port: int = 8420,
    timeout: float = 0.5,
    max_threads: int = 50,
) -> dict:
    result = lan_discovery.discover(
        base_ip=base_ip, port=port, timeout=timeout, max_threads=max_threads
    )

    base = {
        "added": [],
        "existing": [],
        "scanned": result.get("scanned", 0),
        "elapsed_s": result.get("elapsed_s", 0.0),
    }

    if "error" in result:
        base["error"] = result["error"]
        return base

    existing_nodes = cluster_store.list_nodes(project_root)
    existing_urls = {n.get("url", "").rstrip("/") for n in existing_nodes}

    for node in result.get("nodes", []):
        url = (node.get("url") or "").rstrip("/")
        if not url:
            continue

        name = f"lca-{node['ip']}"

        if url in existing_urls:
            base["existing"].append({"name": name, "url": url})
        else:
            try:
                cluster_store.add_node(project_root, name, url)
                base["added"].append({
                    "name": name,
                    "url": url,
                    "version": node.get("version", ""),
                })
                existing_urls.add(url)
            except ValueError:
                pass  # cluster full or invalid url — skip silently

    return base
