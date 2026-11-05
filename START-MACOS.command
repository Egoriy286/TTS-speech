#!/bin/zsh
set -e
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
export PYTHONUTF8=1
if command -v uv >/dev/null 2>&1; then
  TTS_UV="$(command -v uv)"
else
  TTS_UV="$PWD/.tools/uv"
  if [[ ! -x "$TTS_UV" ]]; then
    mkdir -p .tools/download
    case "$(uname -m)" in
      arm64) TTS_TARGET="aarch64-apple-darwin" ;;
      x86_64) TTS_TARGET="x86_64-apple-darwin" ;;
      *) print 'Unsupported architecture'; exit 1 ;;
    esac
    TTS_ARCHIVE="uv-${TTS_TARGET}.tar.gz"
    TTS_URL="https://github.com/astral-sh/uv/releases/download/0.13.1/${TTS_ARCHIVE}"
    /usr/bin/curl -fL "$TTS_URL" -o ".tools/download/$TTS_ARCHIVE"
    /usr/bin/curl -fL "$TTS_URL.sha256" -o ".tools/download/$TTS_ARCHIVE.sha256"
    (cd .tools/download && /usr/bin/shasum -a 256 -c "$TTS_ARCHIVE.sha256")
    /usr/bin/tar -xzf ".tools/download/$TTS_ARCHIVE" --strip-components=1 -C .tools
  fi
fi
"$TTS_UV" run --no-project --no-config --python 3.12 launcher.py "$@" || {
  print 'Launch failed. See the message above. Press Enter to close.'
  read
  exit 1
}
