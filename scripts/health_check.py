import subprocess
import os
import sys

def run(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.stdout.strip()

print("=== 1. Structure & Size ===")
files = run("git ls-files").splitlines()
print(f"git ls-files count: {len(files)}")

# git size
git_size = 0
for root, dirs, fnames in os.walk(".git"):
    for f in fnames:
        fp = os.path.join(root, f)
        try:
            git_size += os.path.getsize(fp)
        except OSError:
            pass
print(f".git size: {git_size / (1024*1024):.2f} MB")

# repo size
repo_size = 0
for root, dirs, fnames in os.walk("."):
    if ".git" in root or ".venv" in root:
        continue
    for f in fnames:
        fp = os.path.join(root, f)
        try:
            repo_size += os.path.getsize(fp)
        except OSError:
            pass
print(f"repo working tree size (excl .git/.venv): {repo_size / (1024*1024):.2f} MB")

# Code lines
code_lines = 0
for f in files:
    if f.endswith((".py", ".rs", ".java", ".ts")):
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                code_lines += sum(1 for _ in fh)
        except OSError:
            pass
print(f"Total code lines (.py, .rs, .java, .ts): {code_lines}")

print("\n=== 2. Hygiene Files ===")
expected_files = [
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "pyproject.toml",
    "requirements.txt",
    "Dockerfile",
    ".github",
    "Makefile",
    "REPRODUCIBILITY.md",
    "ATTESTATION.md",
    ".gitignore",
]
for ef in expected_files:
    exists = os.path.exists(ef)
    status = "EXISTS" if exists else "MISSING"
    print(f"{ef:<20}: {status}")

print("\n=== 3. .gitignore First 20 Lines ===")
if os.path.exists(".gitignore"):
    with open(".gitignore", "r", encoding="utf-8") as gf:
        for i, line in enumerate(gf):
            if i >= 20:
                break
            print(line.rstrip())
else:
    print("No .gitignore found")

print("\n=== 4. CI Workflows ===")
ci_dir = os.path.join(".github", "workflows")
if os.path.exists(ci_dir):
    print("Workflows:", os.listdir(ci_dir))
else:
    print("No .github/workflows directory")

print("\n=== 5. Tests ===")
test_files = [f for f in files if f.startswith("tests/") and f.endswith(".py")]
print(f"Test files count: {len(test_files)}")

print("\n=== 6. Deps ===")
pip_out = run(f'"{sys.executable}" -m pip list')
matched_deps = [line for line in pip_out.splitlines() if any(k in line.lower() for k in ["pydantic", "rich", "click", "llama", "jmespath", "matplotlib", "ddgs"])]
print("Installed key dependencies:")
for d in matched_deps:
    print("  ", d)

print("\n=== 7. Commits ===")
print("Recent 5 commits:")
print(run("git log --oneline -5"))
all_commits = run("git log --oneline").splitlines()
print(f"Total commits: {len(all_commits)}")
