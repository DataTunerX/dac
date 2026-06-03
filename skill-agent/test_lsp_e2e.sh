#!/bin/bash
# Minimal LSP documentSymbol test for Go / Python / Java
set -euo pipefail

# ==========================================================================
echo "=============================="
echo " Go: gopls documentSymbol "
echo "=============================="

mkdir -p /tmp/gopls-test
cat > /tmp/gopls-test/main.go <<'EOF'
package main

type Calculator struct {
    value int
}

func (c *Calculator) Add(n int) int { return c.value + n }
func main() {}
EOF

python3 << 'PY'
import subprocess, json, sys, os, time

def r(stream):
    h = b""
    while not h.endswith(b"\r\n\r\n"):
        c = stream.read(1)
        if not c: return None
        h += c
    d = {}
    for l in h.decode().strip().split("\r\n"):
        if ":" in l:
            k, v = l.split(":", 1)
            d[k.strip().lower()] = v.strip()
    body = stream.read(int(d.get("content-length", 0)))
    return json.loads(body)

def resp(stream, eid, to=15):
    dl = time.time() + to
    while time.time() < dl:
        m = r(stream)
        if m is None: raise RuntimeError("closed")
        if m.get("id") == eid: return m
    raise TimeoutError(f"no response for id={eid}")

def s(stream, msg):
    c = json.dumps(msg)
    stream.write(f"Content-Length: {len(c)}\r\n\r\n{c}".encode())
    stream.flush()

p = subprocess.Popen(["gopls"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    s(p.stdin, {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "processId":os.getpid(), "rootUri":"file:///tmp/gopls-test","rootPath":"/tmp/gopls-test",
        "capabilities":{"textDocument":{"documentSymbol":{"hierarchicalDocumentSymbolSupport":True}}}
    }})
    if not resp(p.stdout,1).get("result",{}).get("capabilities"):
        print("FAIL: gopls init"); sys.exit(1)

    s(p.stdin, {"jsonrpc":"2.0","method":"initialized","params":{}})
    time.sleep(2)

    with open("/tmp/gopls-test/main.go") as f:
        s(p.stdin, {"jsonrpc":"2.0","method":"textDocument/didOpen","params":{
            "textDocument":{"uri":"file:///tmp/gopls-test/main.go","languageId":"go","version":1,"text":f.read()}
        }})
    time.sleep(2)

    s(p.stdin, {"jsonrpc":"2.0","id":2,"method":"textDocument/documentSymbol","params":{
        "textDocument":{"uri":"file:///tmp/gopls-test/main.go"}
    }})
    rv = resp(p.stdout,2)
    syms = rv.get("result",[])
    names = [x.get("name","?") for x in syms]
    if len(names) >= 2:
        print(f"PASS: gopls documentSymbol → {names}")
    else:
        print(f"FAIL: gopls documentSymbol → {names}")
finally:
    p.terminate(); p.wait(timeout=5)
PY

# ==========================================================================
echo ""
echo "=============================="
echo " Python: pyright documentSymbol "
echo "=============================="

mkdir -p /tmp/pyright-test
cat > /tmp/pyright-test/app.py <<'EOF'
class Calculator:
    def add(self, n: int) -> int: return n

def compute(x: int) -> int:
    c = Calculator()
    return c.add(x)
EOF

python3 << 'PY'
import subprocess, json, sys, os, time

def r(stream):
    h = b""
    while not h.endswith(b"\r\n\r\n"):
        c = stream.read(1)
        if not c: return None
        h += c
    d = {}
    for l in h.decode().strip().split("\r\n"):
        if ":" in l:
            k, v = l.split(":", 1)
            d[k.strip().lower()] = v.strip()
    body = stream.read(int(d.get("content-length", 0)))
    return json.loads(body)

def resp(stream, eid, to=15):
    dl = time.time() + to
    while time.time() < dl:
        m = r(stream)
        if m is None: raise RuntimeError("closed")
        if m.get("id") == eid: return m
    raise TimeoutError(f"no response for id={eid}")

def s(stream, msg):
    c = json.dumps(msg)
    stream.write(f"Content-Length: {len(c)}\r\n\r\n{c}".encode())
    stream.flush()

p = subprocess.Popen(["pyright-langserver","--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    s(p.stdin, {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "processId":os.getpid(), "rootUri":"file:///tmp/pyright-test","rootPath":"/tmp/pyright-test",
        "workspaceFolders":[{"uri":"file:///tmp/pyright-test","name":"pytest"}],
        "capabilities":{"textDocument":{"documentSymbol":{"hierarchicalDocumentSymbolSupport":True}}}
    }})
    if not resp(p.stdout,1).get("result",{}).get("capabilities"):
        print("FAIL: pyright init"); sys.exit(1)

    s(p.stdin, {"jsonrpc":"2.0","method":"initialized","params":{}})
    time.sleep(3)

    with open("/tmp/pyright-test/app.py") as f:
        s(p.stdin, {"jsonrpc":"2.0","method":"textDocument/didOpen","params":{
            "textDocument":{"uri":"file:///tmp/pyright-test/app.py","languageId":"python","version":1,"text":f.read()}
        }})
    time.sleep(3)

    s(p.stdin, {"jsonrpc":"2.0","id":2,"method":"textDocument/documentSymbol","params":{
        "textDocument":{"uri":"file:///tmp/pyright-test/app.py"}
    }})
    rv = resp(p.stdout,2)
    syms = rv.get("result",[])
    names = [x.get("name","?") for x in syms]
    if len(names) >= 2:
        print(f"PASS: pyright documentSymbol → {names}")
    else:
        print(f"FAIL: pyright documentSymbol → {names}")
finally:
    p.terminate(); p.wait(timeout=5)
PY

# ==========================================================================
echo ""
echo "=============================="
echo " Java: jdtls documentSymbol "
echo "=============================="

mkdir -p /tmp/jdtls-test
cat > /tmp/jdtls-test/Calc.java <<'EOF'
public class Calc {
    private int value;
    public int add(int n) { return value + n; }
}
EOF

python3 << 'PY'
import subprocess, json, sys, os, time

def r(stream):
    h = b""
    while not h.endswith(b"\r\n\r\n"):
        c = stream.read(1)
        if not c: return None
        h += c
    d = {}
    for l in h.decode().strip().split("\r\n"):
        if ":" in l:
            k, v = l.split(":", 1)
            d[k.strip().lower()] = v.strip()
    body = stream.read(int(d.get("content-length", 0)))
    return json.loads(body)

def resp(stream, eid, to=30):
    dl = time.time() + to
    while time.time() < dl:
        m = r(stream)
        if m is None: raise RuntimeError("closed")
        if m.get("id") == eid: return m
    raise TimeoutError(f"no response for id={eid}")

def s(stream, msg):
    c = json.dumps(msg)
    stream.write(f"Content-Length: {len(c)}\r\n\r\n{c}".encode())
    stream.flush()

p = subprocess.Popen(["/opt/jdtls/bin/jdtls", "-data", "/tmp/jdtls-data"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    s(p.stdin, {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "processId":os.getpid(), "rootUri":"file:///tmp/jdtls-test","rootPath":"/tmp/jdtls-test",
        "workspaceFolders":[{"uri":"file:///tmp/jdtls-test","name":"jtest"}],
        "capabilities":{"textDocument":{"documentSymbol":{"hierarchicalDocumentSymbolSupport":True}}}
    }})
    if not resp(p.stdout,1,to=30).get("result",{}).get("capabilities"):
        print("FAIL: jdtls init"); sys.exit(1)

    s(p.stdin, {"jsonrpc":"2.0","method":"initialized","params":{}})
    time.sleep(5)

    with open("/tmp/jdtls-test/Calc.java") as f:
        s(p.stdin, {"jsonrpc":"2.0","method":"textDocument/didOpen","params":{
            "textDocument":{"uri":"file:///tmp/jdtls-test/Calc.java","languageId":"java","version":1,"text":f.read()}
        }})
    time.sleep(5)

    s(p.stdin, {"jsonrpc":"2.0","id":2,"method":"textDocument/documentSymbol","params":{
        "textDocument":{"uri":"file:///tmp/jdtls-test/Calc.java"}
    }})
    rv = resp(p.stdout,2,to=30)
    syms = rv.get("result",[])

    def count(ss):
        n = len(ss)
        for s in ss:
            n += count(s.get("children",[]))
        return n

    def names(ss):
        out = []
        for s in ss:
            out.append(s.get("name","?"))
            out.extend(names(s.get("children",[])))
        return out

    total = count(syms)
    all_names = names(syms)
    if total >= 2:
        print(f"PASS: jdtls documentSymbol ({total} symbols) → {all_names[:6]}")
    else:
        print(f"FAIL: jdtls documentSymbol ({total} symbols) → {all_names}")
finally:
    p.terminate(); p.wait(timeout=5)
PY

echo ""
echo "=============================="
echo " ALL TESTS DONE"
echo "=============================="
