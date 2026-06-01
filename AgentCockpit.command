#!/bin/bash

# macOS Finder executes .command files in the home directory by default.
# We change the working directory to the folder containing this file.
cd "$(dirname "$0")" || exit 1

# Set window title in terminal
echo -ne "\033]0;AgentCockpit Control Panel\007"

clear
echo "=================================================================="
echo "               AGENTCOCKPIT birleşik KONTROL PANELİ               "
echo "=================================================================="
echo "  * Telefon Köprüsü (PWA), Telegram UX ve Arka Uç akışları açılıyor."
echo "  * Kapatmak isterseniz bu Terminal penceresini kapatabilir veya"
echo "    [Ctrl + C] tuş kombinasyonunu kullanabilirsiniz."
echo "=================================================================="
echo ""

# Clean up any running components from the previous stack first
./runner.sh stop

# Run using the robust runner.sh script
./runner.sh

echo ""
echo "=================================================================="
echo "  Süreç sonlandı veya durduruldu."
echo "=================================================================="
read -p "Terminal penceresini kapatmak için [Enter] tuşuna basın..."
