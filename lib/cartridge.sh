# shellcheck shell=bash
# Cartridge install and press helpers. Source after common.sh.

# cartridge_install: the public installer, then check cartpress is on PATH.
cartridge_install() {
  command -v cartpress >/dev/null || curl -sSf https://cartridge.app/install | sh
  command -v cartpress >/dev/null || die "cartpress is not on PATH after the install; open a new shell (or add the installer's bin directory to PATH) and re-run"
  cartpress --version
}
