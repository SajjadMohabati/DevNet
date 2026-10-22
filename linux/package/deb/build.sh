#!/bin/sh
# Build a self-contained Debian package for DevNet.
#
#   ./linux/package/deb/build.sh
#   ./linux/package/deb/build.sh --output build/deb
#
# The package uses dpkg-deb directly, so it needs no debhelper or network access.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LINUX=$(CDPATH= cd -- "$HERE/../.." && pwd)
ROOT=$(CDPATH= cd -- "$LINUX/.." && pwd)
VERSION=${VERSION:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$LINUX/src/devnet/__init__.py")}
OUTPUT="$ROOT/build/deb"

usage() {
    cat <<EOF
Build the DevNet Debian package.

Usage: $0 [--output DIR]

  --output DIR   write devnet_${VERSION}_all.deb to DIR (default: build/deb)
  -h, --help     show this help

Environment: VERSION overrides the version in linux/src/devnet/__init__.py
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --output)
            [ $# -ge 2 ] || { usage >&2; exit 2; }
            OUTPUT=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            echo "devnet-package: unknown option: $1" >&2
            exit 2
            ;;
    esac
done

[ -n "$VERSION" ] || { echo "devnet-package: could not determine the version" >&2; exit 1; }
case "$VERSION" in
    *[!0-9A-Za-z.+~-]*) echo "devnet-package: invalid version: $VERSION" >&2; exit 1 ;;
esac
command -v dpkg-deb >/dev/null 2>&1 || {
    echo "devnet-package: dpkg-deb is required (install dpkg)." >&2
    exit 1
}

mkdir -p "$OUTPUT"
OUTPUT=$(CDPATH= cd -- "$OUTPUT" && pwd)
TEMP=$(mktemp -d "${TMPDIR:-/tmp}/devnet-deb.XXXXXX")
trap 'rm -rf "$TEMP"' EXIT INT TERM
STAGE="$TEMP/root"

install -d -m 755 \
    "$STAGE/DEBIAN" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/lib/devnet" \
    "$STAGE/usr/libexec/devnet" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/metainfo" \
    "$STAGE/usr/share/doc/devnet" \
    "$STAGE/usr/share/icons/hicolor"

# Application code. Keep bytecode and caches out of the package.
tar -C "$LINUX/src" \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
    -cf - devnet | tar -C "$STAGE/usr/lib/devnet" -xf -
chmod -R go-w "$STAGE/usr/lib/devnet/devnet"

install -m 755 "$LINUX/bin/devnet" "$STAGE/usr/bin/devnet"
install -m 755 "$LINUX/data/devnet-helper" "$STAGE/usr/libexec/devnet/devnet-helper"
install -m 644 "$LINUX/data/org.devnet.App.desktop" "$STAGE/usr/share/applications/"
install -m 644 "$LINUX/data/org.devnet.App.metainfo.xml" "$STAGE/usr/share/metainfo/"

for size in 16 24 32 48 64 128 256 512 1024; do
    source="$LINUX/data/icons/hicolor/${size}x${size}/apps/org.devnet.App.png"
    if [ -f "$source" ]; then
        install -d -m 755 "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps"
        install -m 644 "$source" "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps/org.devnet.App.png"
    fi
done

install -m 644 "$HERE/copyright" "$STAGE/usr/share/doc/devnet/copyright"
if [ -f "$LINUX/README.md" ]; then
    install -m 644 "$LINUX/README.md" "$STAGE/usr/share/doc/devnet/README.linux.md"
fi
gzip -9nc "$HERE/changelog" >"$STAGE/usr/share/doc/devnet/changelog.gz"
chmod 644 "$STAGE/usr/share/doc/devnet/changelog.gz"

SIZE=$(du -sk "$STAGE" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" "$HERE/control.in" \
    >"$STAGE/DEBIAN/control"
for script in postinst prerm postrm; do
    install -m 755 "$HERE/$script" "$STAGE/DEBIAN/$script"
done
chmod 644 "$STAGE/DEBIAN/control"

PACKAGE="$OUTPUT/devnet_${VERSION}_all.deb"
rm -f "$PACKAGE"
dpkg-deb --root-owner-group --build "$STAGE" "$PACKAGE" >/dev/null

printf '\n  Built %s\n' "$PACKAGE"
printf '  Size:  %s\n' "$(du -h "$PACKAGE" | cut -f1)"
printf '  Check: dpkg-deb --info %s\n\n' "$PACKAGE"
