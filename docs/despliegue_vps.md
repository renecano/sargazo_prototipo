# Despliegue de PMS en un VPS Linux

Guía para instalar PMS v0.4.0 en un servidor Linux propio (por ejemplo, el de SEMAR). **No
se ha ejecutado todavía**: no hay acceso al servidor. No contiene credenciales; donde haga
falta una, se indica cómo obtenerla.

## Requisitos

- Linux x86-64 con **glibc 2.28 o superior** (Ubuntu 20.04+, Debian 11+, RHEL/Rocky/Alma 8+):
  NumPy 2.5.3 no publica paquetes para versiones anteriores.
- **Python 3.12, 3.13 o 3.14** con `venv` (`python3 --version`).
- Git, `sudo` y el puerto **8000/TCP** abierto hacia la red de los usuarios.
- ~300 MB de disco (código, entorno virtual y simulaciones) y ~200 MB de RAM libres.
- Los navegadores de los usuarios necesitan internet para las teselas de OpenStreetMap y la
  tipografía; el servidor no.

En Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

## 1. Usuario de servicio y clon en /opt/pms

```bash
sudo useradd --system --create-home --home-dir /var/lib/pms --shell /usr/sbin/nologin pms
sudo git clone https://github.com/renecano/sargazo_prototipo.git /opt/pms
sudo chown -R pms:pms /opt/pms
```

Si el repositorio vuelve a ser privado, el `git clone` pedirá un usuario de GitHub con acceso y un
*token* personal (GitHub → Settings → Developer settings → Personal access tokens, con
permiso de solo lectura del repositorio). No guardes el token en el servidor; para
actualizaciones automáticas usa una *deploy key* de solo lectura.

`data/semar/dirmarea.txt` viene en el repositorio. Para usar otro archivo, cópialo encima
(o usa `--datos <carpeta>` en el servicio).

## 2. Entorno virtual y dependencias

```bash
cd /opt/pms
sudo -u pms python3 -m venv .venv
sudo -u pms .venv/bin/python -m pip install --upgrade pip
sudo -u pms .venv/bin/python -m pip install -r requirements.txt
```

Prueba manual (Ctrl+C para salir):

```bash
sudo -u pms .venv/bin/python main.py --host 0.0.0.0 --puerto 8000 --no-navegador
curl -s http://127.0.0.1:8000/api/salud
```

Debe responder `"estado":"ok"` y `"datos_disponibles":true`.

## 3. Servicio systemd `pms`

Crea `/etc/systemd/system/pms.service`:

```ini
[Unit]
Description=PMS · Predicción de Movimiento del Sargazo
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pms
Group=pms
WorkingDirectory=/opt/pms
ExecStart=/opt/pms/.venv/bin/python main.py --host 0.0.0.0 --puerto 8000 --no-navegador
Restart=on-failure
RestartSec=5
# Endurecimiento básico: solo puede escribir en el historial de simulaciones.
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/pms/data/simulations
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /opt/pms/data/simulations && sudo chown pms:pms /opt/pms/data/simulations
sudo systemctl daemon-reload
sudo systemctl enable --now pms
sudo systemctl status pms
```

## 4. Abrir el puerto 8000

Con `ufw` (Ubuntu):

```bash
sudo ufw allow 8000/tcp
sudo ufw status
```

Con `firewalld` (RHEL/Rocky/Alma):

```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

Si el proveedor del VPS tiene un firewall propio (grupo de seguridad), abre ahí también el
8000/TCP. Comprueba desde otra máquina: `http://<ip-del-servidor>:8000`.

PMS no tiene autenticación ni HTTPS. Para exponerlo fuera de la red interna, ponlo detrás
de un proxy inverso (nginx o Caddy) con HTTPS y control de acceso, y abre solo el 443.

## 5. Logs

```bash
sudo journalctl -u pms -f            # en vivo
sudo journalctl -u pms --since today # del día
```

El servidor registra advertencias y errores. Las simulaciones guardadas quedan en
`/opt/pms/data/simulations/` (un JSON por simulación).

## 6. Actualizar

```bash
cd /opt/pms
sudo -u pms git fetch origin
sudo -u pms git log --oneline HEAD..origin/main     # qué cambia
git rev-parse HEAD | sudo tee /var/lib/pms/version_anterior   # para poder revertir
sudo -u pms git merge --ff-only origin/main
sudo -u pms .venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart pms
curl -s http://127.0.0.1:8000/api/salud
```

## 7. Revertir

```bash
cd /opt/pms
sudo -u pms git checkout "$(cat /var/lib/pms/version_anterior)"
sudo -u pms .venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart pms
```

Para volver a la rama principal después: `sudo -u pms git checkout main`.

## 8. Desinstalar

```bash
sudo systemctl disable --now pms
sudo rm /etc/systemd/system/pms.service && sudo systemctl daemon-reload
sudo rm -rf /opt/pms          # borra también el historial de simulaciones
sudo userdel -r pms
```
