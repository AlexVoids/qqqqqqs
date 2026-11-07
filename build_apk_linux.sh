#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -U "flet[all]>=0.86,<1" requests phonenumbers
flet build apk
printf '\nAPK files: build/apk/\n'
