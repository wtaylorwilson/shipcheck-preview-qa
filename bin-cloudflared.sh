#!/bin/bash
exec /workspace/shipcheck/cloudflared tunnel --url http://127.0.0.1:8788 --no-autoupdate --logfile /workspace/shipcheck/cloudflared.log
