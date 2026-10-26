# shellcheck shell=bash
# Cartridge install and press helpers. Source after common.sh.

# cartridge_install: the public installer, then check cartpress is on PATH.
cartridge_install() {
  command -v cartpress >/dev/null || curl -sSf https://cartridge.app/install | sh
  command -v cartpress >/dev/null || die "cartpress is not on PATH after the install; open a new shell (or add the installer's bin directory to PATH) and re-run"
  cartpress --version
}

# press_confirm: a press spends pressing credit (the first 25 GB are free). Ask once up front; PRESS_YES=1 answers yes.
press_confirm() {
  [[ ${PRESS_YES:-0} == 1 ]] && return 0
  local ans
  read -r -p "This run presses with cartpress, which uses your Cartridge pressing credit (25 GB free). Continue? [y/N] " ans
  [[ $ans == y || $ans == Y ]] || die "aborted: no press was started"
}
