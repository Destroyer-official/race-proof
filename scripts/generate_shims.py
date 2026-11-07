"""Generate missing backward-compatibility shims for race_oracle."""
import os

proof_root = "race_proof"
oracle_root = "race_oracle"

created = []

for dirpath, _, filenames in os.walk(proof_root):
    if "__pycache__" in dirpath:
        continue
    rel_dir = os.path.relpath(dirpath, proof_root)
    target_dir = os.path.join(oracle_root, rel_dir) if rel_dir != "." else oracle_root
    os.makedirs(target_dir, exist_ok=True)

    for f in filenames:
        if not f.endswith(".py") or f.startswith("__pycache__"):
            continue
        rel_path = os.path.join(rel_dir, f) if rel_dir != "." else f
        target_path = os.path.join(oracle_root, rel_path)

        if not os.path.exists(target_path):
            mod_parts = []
            if rel_dir != ".":
                mod_parts.extend(rel_dir.replace("\\", "/").split("/"))
            if f != "__init__.py":
                mod_parts.append(f[:-3])

            mod_name = ".".join(mod_parts)
            import_target = f"race_proof.{mod_name}" if mod_name else "race_proof"
            oracle_mod = f"race_oracle.{mod_name}" if mod_name else "race_oracle"

            shim_content = (
                f'"""Backward-compatibility shim for {oracle_mod} -> {import_target}."""\n'
                f"from {import_target} import *\n"
                f"import {import_target} as _orig\n\n"
                f'if hasattr(_orig, "__all__"):\n'
                f"    __all__ = list(_orig.__all__)\n"
            )
            with open(target_path, "w", encoding="utf-8") as out:
                out.write(shim_content)
            created.append(target_path)

print(f"Successfully created {len(created)} shim files in race_oracle.")
for p in created:
    print(f"  + {p}")

