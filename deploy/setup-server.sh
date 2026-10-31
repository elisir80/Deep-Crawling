#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/home/the-matrix/deep-crawling
SERVICE=deep-crawling.service
DOMAIN=raccampo.no-ip.org
APP_USER=the-matrix

sudo install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/data"
sudo tee "/etc/systemd/system/$SERVICE" >/dev/null <<EOF
[Unit]
Description=Deep Crawling SEO Spider
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PORT=5132
Environment=PYTHONUNBUFFERED=1
Environment=REGISTRATION_DISABLED=true
Environment=DISABLE_GUEST=true
Environment=SECRET_KEY=REPLACE_WITH_A_RANDOM_SECRET
ExecStart=$APP_DIR/.venv/bin/python main.py --disable-register --disable-guest
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$APP_DIR/data

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/nginx/sites-available/deep-crawling >/dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN _;

    location / {
        proxy_pass http://127.0.0.1:5132;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
EOF

sudo rm -f /etc/nginx/sites-enabled/crypto_dashboard
sudo ln -sfn /etc/nginx/sites-available/deep-crawling /etc/nginx/sites-enabled/deep-crawling
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE"
sudo systemctl reload nginx

echo "Deep Crawling attivo su http://$DOMAIN e http://$(hostname -I | awk '{print $1}')"
echo "Servizio: systemctl status $SERVICE"
echo "HTTPS non attivato automaticamente: richiede DNS/port-forwarding verificati e certificato valido."
