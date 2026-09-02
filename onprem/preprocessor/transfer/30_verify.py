import ast, hashlib, sys
src = open(sys.argv[1], encoding="utf-8").read()
lines = src.splitlines()
for n in ast.parse(src).body:
    name = getattr(n, "name", "")
    if not name and isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
        name = n.targets[0].id
    if not name:
        continue
    body = "\n".join(l.rstrip() for l in lines[n.lineno - 1:n.end_lineno])
    print(hashlib.sha256(body.encode("utf-8")).hexdigest()[:8], name)
