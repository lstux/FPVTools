#!/usr/bin/env bash
# fpvtools.sh : install/update the Linux tools used to configure FPV drones.
# Each tool is described by tools/<tool>.conf and installed with ghrelease-install.
set -u -o pipefail

WORKDIR="$(cd "$(dirname "$(readlink -f "${0}")")" && pwd)"
PROG="$(basename "${0}")"
INSTALLDIR="${FPV_INSTALLDIR:-/opt/FPVTools}"
LINKDIR="${FPV_LINKDIR:-${HOME}/.local/bin}"
GRI="${WORKDIR}/ghrelease-install"
MODE="instupdate"
VERSION="latest"
GRI_OPTS=()

usage() {
  cat <<USAGE
Usage : ${PROG} [options] tool [tool...]
  Install/update FPV configuration tools from their GitHub releases.
  'ls' lists the available tools, 'all' selects every (non interactive) tool.
  Tools go to '${INSTALLDIR}' (set FPV_INSTALLDIR to change),
  launchers are linked in '${LINKDIR}' (set FPV_LINKDIR to change).
Options :
  -I : install or update (default)
  -i : install only (skip if already installed)
  -u : update only (skip if not installed)
  -r : reinstall
  -c : check installed version against the latest release
  -l : show latest release
  -s : show the release assets and which one would be installed
  -R : remove
  -V version : install a specific release tag [latest]
  -P : allow pre-releases
  -q : quiet
  -d : debug (shell trace)
  -h : this help
USAGE
}

while getopts IiurclsRV:Pqdh opt; do case "${opt}" in
  I) MODE="instupdate";; i) MODE="install";; u) MODE="update";; r) MODE="reinstall";;
  c) MODE="check";; l) MODE="latest";; s) MODE="show";; R) MODE="remove";;
  V) VERSION="${OPTARG}";; P) GRI_OPTS+=(-P);;
  q) GRI_OPTS+=(-q);; d) set -x;;
  h) usage; exit 0;; *) usage >&2; exit 1;;
esac; done
shift $((OPTIND - 1))
[ $# -gt 0 ] || { usage >&2; exit 1; }

[ -x "${GRI}" ] || { echo "Error : ${GRI} not found or not executable" >&2; exit 1; }

list_tools() { local f; for f in "${WORKDIR}"/tools/*.conf; do basename "${f}" .conf; done; }

show_list() {
  local t
  printf 'Available tools :\n'
  for t in $(list_tools); do
    ( DESC=""; # shellcheck disable=SC1090
      . "${WORKDIR}/tools/${t}.conf"; printf ' * %-16s %s\n' "${t}" "${DESC}" )
  done
}

ensure_dirs() {
  [ -d "${INSTALLDIR}" ] && [ -w "${INSTALLDIR}" ] && return 0
  echo "Creating ${INSTALLDIR} (sudo needed once)..." >&2
  local sudo="sudo"; [ "$(id -u)" = 0 ] && sudo=""
  ${sudo} install -d -m755 -o "$(id -un)" -g "$(id -gn)" "${INSTALLDIR}" || return 1
}

path_hint() {
  case ":${PATH}:" in *":${LINKDIR}:"*) ;; *) echo "Note : ${LINKDIR} is not in your PATH" >&2;; esac
}

# Runs one tool. Conf variables : DESC REPO NAME BIN LINKNAME ASSET EXTRA_OPTS, optional pre_install()
run_tool() {
  local tool="${1}" conf="${WORKDIR}/tools/${1}.conf" rc
  [ -e "${conf}" ] || { echo "Error : unsupported tool '${tool}' (try '${PROG} ls')" >&2; return 2; }
  # shellcheck disable=SC1090
  ( DESC=""; ASSET=""; NAME=""; BIN=""; LINKNAME=""; EXTRA_OPTS=""
    . "${conf}"
    [ -n "${REPO:-}" ] || { echo "Error : ${conf} has no REPO" >&2; exit 2; }
    declare -F pre_install >/dev/null && { pre_install || exit 1; }
    [ -n "${NAME}" ] || NAME="${tool}"
    opts=("${GRI_OPTS[@]}" -d "${INSTALLDIR}" -l "${LINKDIR}" -n "${NAME}" -v "${VERSION}")
    [ -n "${ASSET}" ]    && opts+=(-a "${ASSET}")
    [ -n "${BIN}" ]      && opts+=(-b "${BIN}")
    [ -n "${LINKNAME}" ] && opts+=(-B "${LINKNAME}")
    # shellcheck disable=SC2206
    [ -n "${EXTRA_OPTS}" ] && opts+=(${EXTRA_OPTS})
    gri() { "${GRI}" "${opts[@]}" "$@" "${REPO}"; }
    printf '== %s (%s)\n' "${tool}" "${REPO}"
    case "${MODE}" in
      latest)  gri -L;;
      show)    gri -s;;
      check)   gri -c; rc=$?; [ ${rc} -le 2 ] && exit 0 || exit ${rc};;
      remove)  gri -R;;
      reinstall) ensure_dirs && gri -f;;
      install) gri -c >/dev/null 2>&1; rc=$?
               if [ ${rc} -eq 2 ]; then ensure_dirs && gri; else echo "${NAME} already installed (use -u to update)"; fi;;
      update)  gri -c >/dev/null 2>&1; rc=$?
               case ${rc} in 2) echo "${NAME} is not installed (use -i)";; 0) echo "${NAME} is up to date";;
                             1) ensure_dirs && gri;; *) exit ${rc};; esac;;
      instupdate) ensure_dirs && gri;;
    esac )
}

if [ "${1}" = "ls" ]; then show_list; exit 0; fi

tools=("$@")
if [ "${1}" = "all" ]; then
  tools=()
  for t in $(list_tools); do
    if grep -q '^pre_install' "${WORKDIR}/tools/${t}.conf"; then echo "(skipping interactive tool '${t}')" >&2; continue; fi
    tools+=("${t}")
  done
fi

status=0
for t in "${tools[@]}"; do run_tool "${t}" || status=1; done
case "${MODE}" in instupdate|install|update|reinstall) path_hint;; esac
exit ${status}
