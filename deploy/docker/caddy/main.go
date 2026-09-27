// Caddy built from source with the standard modules, so the web image can use a
// current Go toolchain and patched dependencies instead of the upstream binary.
package main

import (
	caddycmd "github.com/caddyserver/caddy/v2/cmd"

	_ "github.com/caddyserver/caddy/v2/modules/standard"
)

func main() {
	caddycmd.Main()
}
