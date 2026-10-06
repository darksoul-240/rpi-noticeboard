#!/bin/bash

export DISPLAY=:0
export XAUTHORITY=/home/ibrahim/.Xauthority

exec chromium \
    --kiosk \
    --disable-cache \
    --noerrdialogs \
    --disable-infobars \
    "http://localhost:8000/?v=$(date +%s)"