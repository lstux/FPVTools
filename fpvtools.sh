#!/bin/sh
WORKDIR="$(realpath "$(dirname "${0}")")"
TOOL=""
VERSION="latest"
MODE="instupdate"
INSTALLDIR="${FPV_INSTALLDIR:-/opt/fpvtools}"
TPMDIR="$(mktemp -d)"
trap "rm -rf ${TMPDIR}" EXIT

VERBOSE="${VERBOSE:-false}"
DEBUG="${DEBUG:-false}"

usage() {
  printf "Usage : $(basename "${0}") [options] tool\n"
  printf "  setup various FPV drone configuration tools\n"
  printf "  use '$(basename "${0}") ls' to list available tools\n"
  printf "  tools are installed to '${INSTALLDIR}'\n"
  printf "  set FPV_INSTALLDIR env var to adjust\n"
  printf "Options :\n"
  printf "  -V : specify a version [latest]\n"
  printf "  -l : show latest release version\n"
  printf "  -c : check installed\n"
  printf "  -I : install/update (default)\n"
  printf "  -i : install only\n"
  printf "  -u : update only\n"
  printf "  -r : reinstall\n"
  printf "  -c : check installed\n"
  printf "  -R : remove\n"
  printf "  -v : be verbose\n"
  printf "  -d : debug mode\n"
  printf "  -h : display this help message\n"
  exit 1
}

httpcode()   { curl -sIL -o /dev/null -w "%{http_code}\n" "${1}"; }

msg() { ${VERBOSE} || return 0; printf "$@\n"; }
debug() { ${DEBUG} || return 0; msg "$@"; local a; read -p "Press Enter to continue" a; }

latest_release() { basename "$(curl -s -o /dev/null -L -w "%{url_effective}\n" "${GITURL}/releases/latest")"; }
installed_release() { cat "${INSTALLDIR}/${INSTDIRNAME}/.fpvtools_version" 2>/dev/null; }

tool_infos() {
  local t="${TOOLNAME:-${TOOL}}"
  printf "FPVTools : '${t}'\n"
  [ -n "${TOOLDESC}" ] && printf "${TOOLDESC}\n"
  printf "  %-18s : %s\n" "Latest release" "$(latest_release)"
  printf "  %-18s : %s\n" "Installed release" "$(installed_release)"
  printf "  %-18s : %s\n" "Git URL" "${GITURL}"
}

# Check if tool is installed to latest version
# errcode : 0=latest, 1=installed, 2=not_installed
check_installed() {
  local idir="${INSTALLDIR}/${INSTDIRNAME}"
  [ -d "${idir}" ] || { printf "$(basename "${idir}") is not installed\n" >&2; return 2; }
  local latest="$(latest_release "${GITURL}")" current="$(installed_release)"
  case "${current}" in
    "${latest}") printf "$(basename "${GITPACKAGE}") installed and latest version (${latest})\n" >&2; return 0;;
    "")          printf "$(basename "${GITPACKAGE}") installed, unknown version (latest is ${latest})\n" >&2; return 1;;
    *)           printf "$(basename "${GITPACKAGE}") installed, version ${current} while latest is ${latest}\n" >&2; return 1;;
  esac
  return 2
}

archextract() {
  local arch="${1}" dir="${2}" zopt="-q" topt=""
  ${VERBOSE} && { zopt=""; topt="v"; }
  [ -d "${dir}" ] || install -d -m755 "${dir}" || return 1
  case "${arch}" in
    *.zip|*.ZIP)      unzip ${zopt} "${arch}" -d "${dir}"; return $?;;
    *.tar.gz|*.tgz)   tar x${topt}zf "${arch}" -C "${dir}"; return $?;;
    *.tar.bz2|*.tbz2) tar x${topt}jf "${arch}" -C "${dir}"; return $?;;
    *.tar.xz|*.txz)   tar x${topt}Jf "${arch}" -C "${dir}"; return $?;;
    *)                printf "Error : unsupported archive format ($(basename "${arch}"))\n" >&2; return 2;;
  esac
}

downextract() {
  local ziplink="${GITURL}/releases/download/${VERSION}/${ZIPNAME}"
  if [ -e "${INSTALLDIR}/${ZIPNAME}" ]; then
    msg "${INSTALLDIR}/${ZIPNAME} already available"
  else
    debug "Downloading '${ziplink}' to '${INSTALLDIR}'"
    [ -d "${INSTALLDIR}" ] || install -d -m755 "${INSTALLDIR}" || return 1
    wget "${ziplink}" -P "${INSTALLDIR}" || return 2
  fi
  if [ -n "${ZIPDIRNAME}" ]; then
    debug "Extracting archive to '${INSTALLDIR}(/${ZIPDIRNAME})'"
    archextract "${INSTALLDIR}/${ZIPNAME}" "${INSTALLDIR}" && \
    mv "${INSTALLDIR}/${ZIPDIRNAME}" "${INSTALLDIR}/${INSTDIRNAME}-${VERSION}" || return 3
  else
    debug "Extracting archive to '${INSTALLDIR}/${INSTDIRNAME}-${VERSION}'"
    archextract "${INSTALLDIR}/${ZIPNAME}" "${INSTALLDIR}/${INSTDIRNAME}-${VERSION}" || return 3
  fi
  rm -f "${INSTALLDIR}/${ZIPNAME}"
  echo "${VERSION}" > "${INSTALLDIR}/${INSTDIRNAME}-${VERSION}/.fpvtools_version"
}

instupdate() {
  local mode="${1}"
  if [ "x${VERSION}" = "x" -o "${VERSION}" = "latest" ]; then
    VERSION="$(latest_release)"
    . "${WORKDIR}/tools/${TOOL}.conf"
    [ -n "${INSTDIRNAME}" ] || INSTDIRNAME="${ZIPDIRNAME}"
  fi
  check_installed
  case "$?" in
    0) [ "${mode}" = "reinstall" ] || return 0;;
    1) [ "${mode}" = "install" ] && return 0;;
    2) [ "${mode}" = "update" ] && return 1;;
  esac
  if [ -e "${INSTALLDIR}/${INSTDIRNAME}-${VERSION}/${EXECBIN}" ]; then
    if [ "${mode}" = "reinstall" ]; then
      msg "Forcing reinstallation"
      downextract || return $?
    else
      msg "'${INSTDIRNAME}-${VERSION}' already available, not reinstalling"
    fi
  else
    downextract || return $?
  fi
  # Check Version Symlink
  if ! [ -L "${INSTALLDIR}/${INSTDIRNAME}" ]; then
    debug "Creating symlink '${INSTALLDIR}/${INSTDIRNAME}' -> '${INSTDIRNAME}-${VERSION}'"
    ln -sv "${INSTDIRNAME}-${VERSION}" "${INSTALLDIR}/${INSTDIRNAME}"
  else
    if [ "$(readlink "${INSTALLDIR}/${INSTDIRNAME}")" = "${INSTDIRNAME}-${VERSION}" ]; then
      msg "Symlink '${INSTDIRNAME}' -> '${INSTDIRNAME}-${VERSION}' OK"
    else
      debug "Updating symlink '${INSTALLDIR}/${INSTDIRNAME}' -> '${INSTDIRNAME}-${VERSION}'"
      rm -f "${INSTALLDIR}/${INSTDIRNAME}" && \
      ln -sv "${INSTDIRNAME}-${VERSION}" "${INSTALLDIR}/${INSTDIRNAME}"
    fi
  fi
  # Check that binary is executable
  [ -x "${INSTALLDIR}/${INSTDIRNAME}/${EXECBIN}" ] || chmod 755 "${INSTALLDIR}/${INSTDIRNAME}/${EXECBIN}"
  # Check Binary symlink
  if [ -L "/usr/bin/${EXECBIN}" ]; then
    msg "Symlink '/usr/bin/${EXECBIN}' OK"
  else
    if [ -n "${EXECBIN}" ]; then
      local sudo="sudo"
      [ "$(id -un)" = "root" ] && sudo=""
      debug "Creating symlink '/usr/bin/${EXECBIN}' -> '${INSTALLDIR}/${INSTDIRNAME}/${EXECBIN}'"
      if [ -n "${EXECBIN}" ]; then
        ${sudo} ln -sv "${INSTALLDIR}/${INSTDIRNAME}/${EXECBIN}" "/usr/bin/${EXECBIN}"
      fi
    fi
  fi
}

uninstall() {
  printf "Tools uninstallation not implemented for now :(\n" >&2
  printf "Please remove needed folder(s) manually in ${INSTALLDIR}\n" >&2
  return 1
}

while getopts V:lIirucRvdh opt; do case "${opt}" in
  V) VERSION="${OPTARG}";;
  l) MODE="latest";;
  I) MODE="instupdate";;
  i) MODE="install";;
  r) MODE="reinstall";;
  u) MODE="update";;
  c) MODE="check";;
  R) MODE="remove";;
  v) VERBOSE=true;;
  d) VERBOSE=true; DEBUG=true;;
  *) usage;;
esac; done
shift $((${OPTIND} - 1))

GITACCOUNT=""
GITPACKAGE=""
TOOL="${1}"
case "${TOOL}" in
  ls) printf "Available tools :\n"
      for tool in "${WORKDIR}/tools/"*.conf; do
      printf " * %s\n" "$(basename "${tool}" .conf)"
      done
      exit 0;;
  "") usage;;
esac

msg "Selected tool : '${TOOL}'"
if ! [ -e "${WORKDIR}/tools/${TOOL}.conf" ]; then
  printf "Error : unsupported tool '${TOOL}'\n" >&2
  printf "Use '$(basename "${0}") ls' to list available tools\n" >&2
  exit 2
fi
msg "using conf ${WORKDIR}/tools/${TOOL}.conf"
. "${WORKDIR}/tools/${TOOL}.conf"

GITURL="https://github.com/${GITACCOUNT}"
code="$(httpcode "${GITURL}")"
[ "${code}" = "200" ] || { printf "Error : '${GITURL}' HTTP error ${code}" >&2; exit 1; }
GITURL="${GITURL}/${GITPACKAGE}"
code="$(httpcode "${GITURL}")"
[ "${code}" = "200" ] || { printf "Error : '${GITURL}' HTTP error ${code}" >&2; exit 1; }
msg "Git URL : ${GITURL}"

eval ZIPNAME=\"${ZIPNAME}\"
eval ZIPDIRNAME=\"${ZIPNAME}\"
eval INSTDIRNAME=\"${INSTDIRNAME}\"
eval EXECBIN=\"${EXECBIN}\"

msg "Mode '${MODE}'"
case "${MODE}" in
  infos)      tool_infos;;
  latest)     LATEST="$(latest_release "${GITURL}")"; printf "Latest release for ${TOOLNAME} : ${LATEST}\n";;
  check)      check_installed "${INSTALLDIR}/${INSTDIRNAME}" "${GITURL}";;
  instupdate) instupdate "instupdate";;
  install)    instupdate "install";;
  update)     instupdate "update";;
  remove)     uninstall;;
  *)          printf "OOOOpsss... You shouldn't see this... :D\n"; exit 255;;
esac
