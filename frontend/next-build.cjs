'use strict'

/**
 * Architecture-safe entrypoint for `npm run build`.
 *
 * Docker Desktop may inject `--no-opt` into process.execArgv while emulating
 * amd64 Node.js on Apple Silicon. Next.js 16.0.10 forwards execArgv to build
 * workers through NODE_OPTIONS, but Node.js does not allow `--no-opt` there and
 * throws ERR_WORKER_INVALID_EXEC_ARGV. Unsetting NODE_OPTIONS in the Dockerfile
 * cannot fix this because the flag originates in process.execArgv.
 *
 * Remove only the emulation flag before loading the normal Next.js CLI. This is
 * a no-op on native Linux/macOS builds. Keep this file behind the package.json
 * `build` script so npm still runs any future prebuild/postbuild lifecycle hooks.
 */
process.execArgv = process.execArgv.filter((arg) => arg !== '--no-opt')
process.argv = [process.execPath, require.resolve('next/dist/bin/next'), 'build']

require('next/dist/bin/next')
