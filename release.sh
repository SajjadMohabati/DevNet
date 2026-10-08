#!/bin/zsh
# Builds a universal DevNet.app and packages it as a styled drag-to-install DMG: build/DevNet-<version>.dmg
# Created by Sajjad Mohabati — https://github.com/SajjadMohabati/DevNet
set -e
cd "$(dirname "$0")"
./build.sh --no-install
VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" Info.plist)
DMG=build/DevNet-$VERSION.dmg
STAGE=build/dmg && RW=build/rw.dmg
rm -rf $STAGE $RW $DMG && mkdir -p $STAGE/.background

# Window background (@1x + @2x in one TIFF so it's sharp on Retina).
swift tools/make_art.swift dmg build/bg@2x.png
sips -z 400 660 build/bg@2x.png --out build/bg.png >/dev/null
tiffutil -cathidpicheck build/bg.png build/bg@2x.png -out $STAGE/.background/bg.tiff >/dev/null
cp -R build/DevNet.app $STAGE/
ln -s /Applications $STAGE/Applications

hdiutil create -quiet -volname DevNet -srcfolder $STAGE -fs HFS+ -format UDRW -size 60m $RW
MOUNT=$(hdiutil attach -readwrite -noverify -noautoopen $RW | awk -F'\t' '/\/Volumes\// {print $NF}')

# Finder layout: icon positions, size, background. Needs Finder automation; skipped gracefully if denied.
osascript <<OSA || echo "warning: Finder layout skipped (allow Terminal to control Finder for the styled window)"
tell application "Finder"
  tell disk "DevNet"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 860, 520}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 128
    set text size of opts to 13
    set background picture of opts to file ".background:bg.tiff"
    set position of item "DevNet.app" of container window to {165, 200}
    set position of item "Applications" of container window to {495, 200}
    update without registering applications
    delay 1
    close
  end tell
end tell
OSA
# Volume icon (after Finder, which drops it while laying out the window).
cp build/DevNet.app/Contents/Resources/AppIcon.icns "$MOUNT/.VolumeIcon.icns" && SetFile -a C "$MOUNT"
sync
hdiutil detach -quiet "$MOUNT"
hdiutil convert -quiet $RW -format ULFO -o $DMG
rm -f $RW
echo "Created $DMG"
