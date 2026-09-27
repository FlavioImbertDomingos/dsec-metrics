#!/bin/sh
# Copy the shared libraries WeasyPrint loads, their dependencies, the Fontconfig
# configuration and the DejaVu fonts into $1, with dpkg status entries for every
# package they came from so image scanners still see them. Runs in the build stage only.
set -eu
dest=$1
arch=$(dpkg --print-architecture)
mkdir -p "$dest/var/lib/dpkg/status.d"

# Already in the distroless cc base image; do not ship a second copy.
skip='^(libc\.so|libm\.so|ld-linux|libgcc_s|libstdc\+\+|libdl\.so|libpthread|librt\.so|libgomp)'

roots="libpango-1.0.so.0 libpangoft2-1.0.so.0 libharfbuzz.so.0 libharfbuzz-subset.so.0 libfontconfig.so.1 libgobject-2.0.so.0"
: > /tmp/libs
for lib in $roots; do
  path=$(ldconfig -p | awk -v l="$lib" '$1 == l { print $NF; exit }')
  [ -n "$path" ] || { echo "missing $lib" >&2; exit 1; }
  echo "$path" >> /tmp/libs
  ldd "$path" | awk '/=>/ { print $3 }' >> /tmp/libs
done

: > /tmp/pkgs
# /lib is a symlink to /usr/lib in both images (merged /usr); copy under /usr only.
sed 's|^/lib/|/usr/lib/|' /tmp/libs | sort -u | while read -r file; do
  base=$(basename "$file")
  if echo "$base" | grep -Eq "$skip"; then continue; fi
  real=$(readlink -f "$file")
  mkdir -p "$dest$(dirname "$file")" "$dest$(dirname "$real")"
  cp -a "$real" "$dest$real"
  [ "$file" = "$real" ] || cp -a "$file" "$dest$file"
  dpkg -S "$real" | head -n 1 | cut -d: -f1 >> /tmp/pkgs
done

# Fontconfig configuration and one font family for the generic names.
cp -a --parents /etc/fonts "$dest"
cp -a --parents /usr/share/fonts/truetype/dejavu "$dest"
echo fontconfig-config >> /tmp/pkgs
echo fonts-dejavu-core >> /tmp/pkgs

sort -u /tmp/pkgs | while read -r pkg; do
  dpkg-query -s "$pkg" > "$dest/var/lib/dpkg/status.d/$pkg" 2>/dev/null ||
    dpkg-query -s "$pkg:$arch" > "$dest/var/lib/dpkg/status.d/$pkg"
done
echo "copied $(sed 's|^/lib/|/usr/lib/|' /tmp/libs | sort -u | wc -l) libraries from $(sort -u /tmp/pkgs | wc -l) packages"
