#!/bin/zsh
# Builds DevNet.app (universal: Apple silicon + Intel).
#   ./build.sh                build and install to /Applications
#   ./build.sh --no-install   build only (build/DevNet.app)
# Created by Sajjad Mohabati — https://github.com/SajjadMohabati/DevNet
set -e
cd "$(dirname "$0")"
APP=build/DevNet.app
rm -rf build && mkdir -p $APP/Contents/MacOS $APP/Contents/Resources

for arch in arm64 x86_64; do
  swiftc -O -parse-as-library -target $arch-apple-macos26 *.swift -o build/DevNet-$arch
done
lipo -create build/DevNet-arm64 build/DevNet-x86_64 -output $APP/Contents/MacOS/DevNet
rm build/DevNet-arm64 build/DevNet-x86_64
cp Info.plist $APP/Contents/

# Privileged setup, run from inside the app by “Enable Passwordless Mode”.
cp install.sh $APP/Contents/Resources/
mkdir -p $APP/Contents/Resources/helper $APP/Contents/Resources/sudoers
cp helper/devnet-dns $APP/Contents/Resources/helper/
cp sudoers/devnet $APP/Contents/Resources/sudoers/

# App icon
ICONSET=build/AppIcon.iconset && mkdir -p $ICONSET
swift tools/make_icon.swift build/icon.png
for s in 16 32 128 256 512; do
  sips -z $s $s build/icon.png --out $ICONSET/icon_${s}x${s}.png >/dev/null
  sips -z $((s*2)) $((s*2)) build/icon.png --out $ICONSET/icon_${s}x${s}@2x.png >/dev/null
done
iconutil -c icns $ICONSET -o $APP/Contents/Resources/AppIcon.icns

codesign --force --sign - $APP
echo "Built $APP"

[[ "$1" == "--no-install" ]] && exit 0
pkill -x DevNet || true
rm -rf /Applications/DevNet.app
cp -R $APP /Applications/
open /Applications/DevNet.app
echo "Installed /Applications/DevNet.app"
