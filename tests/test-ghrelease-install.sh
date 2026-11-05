#!/usr/bin/env bash
# Offline tests for ghrelease-install : a tiny fake GitHub API + asset server.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
GRI="${HERE}/../ghrelease-install"
W="$(mktemp -d)"; SRV=""
trap '[ -n "${SRV}" ] && kill "${SRV}" 2>/dev/null; rm -rf "${W}"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
ko()   { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check() { local d="$1"; shift; if "$@"; then ok "${d}"; else ko "${d}"; fi; }

mkdir -p "${W}/www" "${W}/mk"
cd "${W}/mk" || exit 1
# --- fake assets -------------------------------------------------------
mkdir -p "Cfg Linux" && printf '#!/bin/sh\necho cfg-%s\n' v1 >"Cfg Linux/cfg" && chmod 755 "Cfg Linux/cfg"
( cd . && zip -qr "${W}/www/cfg_1.0.0_linux64.zip" "Cfg Linux" )
printf '#!/bin/sh\necho cfg-v2\n' >"Cfg Linux/cfg"
( zip -qr "${W}/www/cfg_2.0.0_linux64.zip" "Cfg Linux" )
for o in windows64.zip macos.dmg linux-arm64.zip linux64.zip.sha256; do echo x >"${W}/www/cfg_2.0.0_${o}"; done
printf '#!/bin/sh\necho appimg\n' >"${W}/www/Tool-1.2.3-x86_64.AppImage"
echo x >"${W}/www/Tool-1.2.3-aarch64.AppImage"; echo x >"${W}/www/Tool-1.2.3.exe"
mkdir -p top/SOUNDS && echo s >top/SOUNDS/a.wav && ( cd top && zip -qr "${W}/www/c480x272.zip" SOUNDS )
mkdir -p tg && printf '#!/bin/sh\necho gyro\n' >tg/gyroflow && chmod 755 tg/gyroflow && tar -czf "${W}/www/Gyroflow-linux64.tar.gz" -C tg gyroflow
SUM="$(sha256sum "${W}/www/Tool-1.2.3-x86_64.AppImage" | cut -d' ' -f1)"

# --- fake API ----------------------------------------------------------
cat >"${W}/srv.py" <<'PY'
import http.server, json, os, sys
www, port, base = sys.argv[1], int(sys.argv[2]), sys.argv[3]
state = {"cfg": "2.0.0", "badsum": False}
def asset(n, digest=None):
    d = {"name": n, "browser_download_url": f"{base}/dl/{n}"}
    if digest: d["digest"] = digest
    return d
def rel(tag, names, pre=False, pub="2026-01-01T00:00:00Z", dig=None):
    return {"tag_name": tag, "draft": False, "prerelease": pre, "published_at": pub,
            "assets": [asset(n, (dig or {}).get(n)) for n in names]}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path
        if p.startswith("/dl/"):
            f = os.path.join(www, p[4:])
            return self.send(200, open(f, "rb").read(), "application/octet-stream") if os.path.exists(f) else self.send(404, {})
        if p == "/__bump": state["cfg"] = "3.0.0"; return self.send(200, {})
        if p == "/__badsum": state["badsum"] = True; return self.send(200, {})
        if p == "/repos/o/cfg/releases/latest":
            v = state["cfg"]
            if v == "1.0.0": return self.send(200, rel("v1.0.0", ["cfg_1.0.0_linux64.zip"]))
            return self.send(200, rel("v2.0.0", ["cfg_2.0.0_linux64.zip","cfg_2.0.0_windows64.zip","cfg_2.0.0_macos.dmg","cfg_2.0.0_linux-arm64.zip","cfg_2.0.0_linux64.zip.sha256"], pub="2026-02-01T00:00:00Z"))
        if p == "/repos/o/cfg/releases/tags/v1.0.0": return self.send(200, rel("v1.0.0", ["cfg_1.0.0_linux64.zip"]))
        if p == "/repos/o/tool/releases/latest":
            sm = "sha256:" + ("0"*64 if state["badsum"] else open(os.path.join(www,"SUM")).read().strip())
            return self.send(200, rel("1.2.3", ["Tool-1.2.3-aarch64.AppImage","Tool-1.2.3-x86_64.AppImage","Tool-1.2.3.exe"], dig={"Tool-1.2.3-x86_64.AppImage": sm}))
        if p == "/repos/o/sd/releases/latest": return self.send(404, {"message": "Not Found"})
        if p.startswith("/repos/o/sd/releases"): return self.send(200, [rel("latest", ["c480x272.zip"], pre=True)])
        if p == "/repos/o/gyro/releases/latest": return self.send(200, rel("v1.6.3", ["Gyroflow-linux64.tar.gz","Gyroflow-mac-universal.dmg","Gyroflow-windows64.zip"]))
        self.send(404, {"message": "Not Found"})
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
PY
echo "${SUM}" >"${W}/www/SUM"
PORT=$((20000 + RANDOM % 20000))
python3 -I "${W}/srv.py" "${W}/www" "${PORT}" "http://127.0.0.1:${PORT}" & SRV=$!
export GHRELEASE_API="http://127.0.0.1:${PORT}"
for _ in $(seq 40); do curl -s -o /dev/null "${GHRELEASE_API}/x" && break; sleep 0.1; done

I="${W}/inst"; L="${W}/bin"
run() { "${GRI}" -q -d "${I}" -l "${L}" "$@"; }

echo "== zip release, top-level dir stripped, auto asset selection"
run -b cfg o/cfg; check "binary linked and runnable" test "$("${L}/cfg" 2>&1)" = "cfg-v2"
check "active symlink -> cfg-v2.0.0" test "$(readlink "${I}/cfg")" = "cfg-v2.0.0"
check "check says up to date" run -c o/cfg
run -c -v v1.0.0 o/cfg; check "old tag -> outdated(1)" test $? -eq 1
echo "== specific older version, then update"
run -b cfg -v 1.0.0 o/cfg -f; check "v1 installed" test "$("${L}/cfg")" = "cfg-v1"
run -b cfg o/cfg; check "update brings v2 back" test "$("${L}/cfg")" = "cfg-v2"
check "both versions kept" test -d "${I}/cfg-v1.0.0" -a -d "${I}/cfg-v2.0.0"
run -b cfg -k 0 -f o/cfg; check "-k 0 prunes old versions" test ! -e "${I}/cfg-v1.0.0" -a -d "${I}/cfg-v2.0.0"
echo "== show / latest"
check "-L prints tag" test "$(run -L o/cfg)" = "v2.0.0"
out="$("${GRI}" -s o/cfg)"; check "-s marks linux64 zip" grep -q '\* cfg_2.0.0_linux64.zip' <<<"${out}"
echo "== AppImage + digest"
run -n tool -B tool o/tool; check "x86_64 AppImage chosen, linked" test "$("${L}/tool")" = appimg
run -n tool -c o/tool; check "up to date" test $? -eq 0
run -n tool2 o/tool; run -n tool3 -R o/tool3; check "remove of unknown -> 2" test $? -eq 2
curl -s "${GHRELEASE_API}/__badsum" >/dev/null
run -n toolbad -f o/tool 2>/dev/null; check "digest mismatch refused" test $? -ne 0
check "nothing installed on failure" test ! -e "${I}/toolbad"
echo "== rolling prerelease (tag 'latest') and -S"
run -n sd -S o/sd; check "single dir kept with -S" test -f "${I}/sd/SOUNDS/a.wav"
echo "== tar.gz single binary at top level"
run -n gyroflow -b gyroflow o/gyro; check "gyroflow runs" test "$("${L}/gyroflow")" = gyro
echo "== remove"
run -R -n cfg o/cfg; check "dirs gone" test ! -e "${I}/cfg-v2.0.0" -a ! -e "${I}/cfg"
check "link gone" test ! -e "${L}/cfg"
echo "== errors"
"${GRI}" -q -d "${I}" o/missing 2>/dev/null; check "unknown repo fails" test $? -ne 0
"${GRI}" -q -d "${I}" badarg 2>/dev/null;    check "bad repo spec fails" test $? -ne 0

echo "== fpvtools.sh end-to-end"
R="${W}/repo"; mkdir -p "${R}/tools" "${W}/fpv"
cp "${HERE}/../fpvtools.sh" "${GRI}" "${R}/"
printf 'REPO="o/cfg"\nNAME="MyCfg"\nBIN="cfg"\nDESC="x"\n' >"${R}/tools/mycfg.conf"
sed 's#EdgeTX/edgetx-sdcard#o/sd#' "${HERE}/../tools/edgetx-sdcard.conf" >"${R}/tools/mysd.conf"
export FPV_INSTALLDIR="${W}/fpv" FPV_LINKDIR="${W}/fpvbin"
FT="${R}/fpvtools.sh"
"${FT}" -i mycfg >/dev/null 2>&1; check "-i installs" test "$("${W}/fpvbin/cfg")" = cfg-v2
"${FT}" -i mycfg 2>&1 | grep -q "already installed"; check "-i twice: skipped" test $? -eq 0
"${FT}" -u mycfg 2>&1 | grep -q "up to date"; check "-u: up to date" test $? -eq 0
"${FT}" -c mycfg 2>&1 | grep -q "up to date"; check "-c reports" test $? -eq 0
EDGETX_SDCARD=c480x272 "${FT}" -i mysd >/dev/null 2>&1; check "sdcard variant installed" test -f "${W}/fpv/EdgeTX-sdcard-c480x272/SOUNDS/a.wav"
"${FT}" ls | grep -q mycfg; check "ls lists tools" test $? -eq 0
"${FT}" -R mycfg >/dev/null 2>&1; check "-R removes" test ! -e "${W}/fpv/MyCfg"
"${FT}" nosuchtool >/dev/null 2>&1; check "unknown tool fails" test $? -ne 0

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
