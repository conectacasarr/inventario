#!/bin/bash
echo "Iniciando o sistema OAIBV..."
echo ""
echo "Por favor, aguarde enquanto o sistema é carregado..."
echo ""
python3 app.py &
sleep 2
xdg-open http://localhost:5000

