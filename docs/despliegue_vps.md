# Despliegue de PMS en un VPS Linux

Guía para instalar PMS en un servidor Linux propio (por ejemplo, el de SEMAR). No contiene
credenciales: donde haga falta un usuario se escribe `<usuario>`.

> **Ejecutada el 03/11/2026 en Ubuntu 26.04.1 LTS** (kernel 7.0, glibc 2.43, Python 3.14.4 del
> sistema, 1 CPU, 809 MB de RAM sin swap, 8.6 GB de disco), en el servidor de entrega
> **http://66.179.210.78:8000** con PMS **v0.4.0** (commit `6401852`, etiqueta `v0.4.0`).
> Los pasos de abajo son los que funcionaron; las diferencias con la versión anterior de la
> guía están marcadas con **Ajuste**. Resultados en [Verificación](#verificación-03112026).

## Requisitos

- Linux x86-64 con **glibc 2.28 o superior** (Ubuntu 20.04+, Debian 11+, RHEL/Rocky/Alma 8+):
  NumPy 2.5.3 no publica paquetes para versiones anteriores.
- **Python 3.12, 3.13 o 3.14** con `venv` (`python3 --version`; `python3 -c "import venv, ensurepip"`).
- Git y el puerto **8000/TCP** abierto hacia la red de los usuarios.
- ~150 MB de disco (código 30 MB, entorno virtual 103 MB, ~1.3 MB por simulación guardada) y
  ~150 MB de RAM para el servicio (medido; ver la tabla de memoria).
- Los navegadores de los usuarios necesitan internet para las teselas de OpenStreetMap y la
  tipografía; el servidor no.

Solo si faltan Git o `venv` (en Ubuntu 26.04 ya venían; **no** hace falta actualizar el sistema):

```bash
sudo apt install -y git python3-venv
```

Los comandos usan `sudo`; si entras como `root`, quítalo (en el servidor de entrega se
trabajó como `root` por SSH con llave: `ssh -i ~/.ssh/<llave> <usuario>@<ip-del-servidor>`).

## 1. Usuario de servicio y clon en /opt/pms, fijo en una versión

```bash
sudo useradd --system --create-home --home-dir /var/lib/pms --shell /usr/sbin/nologin pms
sudo git clone https://github.com/renecano/sargazo_prototipo.git /opt/pms
cd /opt/pms
sudo git checkout -B main v0.4.0                 # Ajuste: fija la versión entregada
sudo git branch --set-upstream-to=origin/main main
sudo chown -R pms:pms /opt/pms
sudo -u pms git -C /opt/pms log --oneline -1     # debe mostrar el commit de la v0.4.0
```

**Ajuste:** la guía anterior dejaba el servidor en la punta de `main`. Para una entrega se fija
la versión (`v0.4.0`); actualizar a algo más nuevo es un paso aparte y reversible (sección 6).

Si el repositorio vuelve a ser privado, el `git clone` pedirá un usuario de GitHub con acceso y un
*token* personal (GitHub → Settings → Developer settings → Personal access tokens, con
permiso de solo lectura del repositorio). No guardes el token en el servidor; para
actualizaciones automáticas usa una *deploy key* de solo lectura.

`data/semar/dirmarea.txt` viene en el repositorio. Para usar otro archivo, cópialo encima
(o usa `--datos <carpeta>` en el servicio). En el servidor solo se instala el producto: ni
`requirements-validacion.txt` ni la caché de la validación (`data/validacion/`, que no está en git).

## 2. Entorno virtual y dependencias

```bash
cd /opt/pms
sudo -u pms python3 -m venv .venv
sudo -u pms .venv/bin/python -m pip install --upgrade pip
sudo -u pms .venv/bin/python -m pip install -r requirements.txt
```

En el servidor de entrega quedaron fastapi 0.142.4, uvicorn 0.54.0, numpy 2.5.3,
pydantic 2.14.2 y starlette 1.10.0 (sin scipy ni nada de la validación).

Prueba manual (se detiene sola a los 25 s):

```bash
sudo -u pms timeout 25 .venv/bin/python main.py --host 127.0.0.1 --puerto 8000 --no-navegador &
sleep 5; curl -s http://127.0.0.1:8000/api/salud
```

Debe responder `"estado":"ok"`, `"version_app":"0.4.0"` y `"datos_disponibles":true`.

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
# Límite de memoria: si una simulación se pasa, el kernel termina solo a PMS (systemd lo
# reinicia) y no afecta a SSH ni al resto del servidor.
MemoryMax=450M
MemorySwapMax=0
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
systemctl is-active pms; systemctl is-enabled pms
curl -s http://127.0.0.1:8000/api/salud
```

**Ajuste:** `MemoryMax=450M` (y `MemorySwapMax=0`). En el servidor de entrega (809 MB de RAM, sin
swap) el límite evita que una simulación grande comprometa SSH u otros servicios.

### Memoria medida (03/11/2026, en el servidor de entrega)

Máximo que permite la interfaz y la API: **5 000 partículas × 120 h** (radio 50 km), en mar
abierto (21.00° N, 86.30° O), donde ninguna partícula vara y el cálculo es el más pesado. Pico
del servicio según systemd (`systemctl show pms -p MemoryPeak`), con el servicio recién reiniciado:

| Momento | Pico del servicio |
|---|---|
| Arranque | 50 MB |
| Interfaz abierta (`/api/campos`) | 85 MB |
| Una simulación máxima, endpoint síncrono | 106 MB (0.44 s; registro de 3.3 MB) |
| Una simulación máxima en segundo plano (lo que usa la interfaz) | 116 MB |
| Dos simulaciones máximas a la vez | 150 MB |

El máximo de la interfaz cabe con amplio margen en `MemoryMax=450M`: no hubo reinicios ni eventos de
memoria en el journal. Para medir de nuevo: `sudo systemctl restart pms`, lanzar la simulación y
leer `systemctl show pms -p MemoryPeak`.

## 4. Abrir el puerto 8000

En el servidor de entrega no hizo falta: `ufw` estaba inactivo, iptables aceptaba todo y el
proveedor no filtraba el 8000 (respondió desde fuera en cuanto PMS escuchó). En otros servidores:

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
8000/TCP. Comprueba desde otra máquina: `curl http://<ip-del-servidor>:8000/api/salud`.

PMS no tiene autenticación ni HTTPS. Para exponerlo fuera de la red interna, ponlo detrás
de un proxy inverso (nginx o Caddy) con HTTPS y control de acceso, y abre solo el 443.

## 5. Logs

```bash
sudo journalctl -u pms -f            # en vivo
sudo journalctl -u pms --since today # del día
systemctl show pms -p MemoryPeak -p MemoryCurrent -p NRestarts
```

El servidor registra advertencias y errores. Las simulaciones guardadas quedan en
`/opt/pms/data/simulations/` (un JSON por simulación, ~1.3 MB con 2 000 partículas).

## 6. Actualizar

```bash
cd /opt/pms
sudo -u pms git fetch origin
sudo -u pms git log --oneline HEAD..origin/main                  # qué cambia
sudo -u pms git rev-parse HEAD | sudo tee /var/lib/pms/version_anterior   # para poder revertir
sudo -u pms git merge --ff-only origin/main
sudo -u pms .venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart pms
curl -s http://127.0.0.1:8000/api/salud
```

**Ajuste:** `git rev-parse` se corre como `pms`. Corrido como `root` sobre un repositorio de `pms`,
Git lo rechaza («detected dubious ownership»).

## 7. Revertir

```bash
cd /opt/pms
sudo -u pms git checkout "$(cat /var/lib/pms/version_anterior)"
sudo -u pms .venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart pms
curl -s http://127.0.0.1:8000/api/salud
```

Queda en un commit fijo («detached HEAD»). Para volver a la versión entregada:
`sudo -u pms git checkout v0.4.0`; para seguir la rama principal: `sudo -u pms git checkout main`.

## 8. Desinstalar

```bash
sudo systemctl disable --now pms
sudo rm /etc/systemd/system/pms.service && sudo systemctl daemon-reload
sudo rm -rf /opt/pms          # borra también el historial de simulaciones
sudo userdel -r pms
```

## Verificación (03/11/2026)

En el servidor de entrega, en este orden:

1. **systemd**: `pms` activo y habilitado; volvió solo tras `systemctl restart pms`, tras
   `kill -9` del proceso (systemd lo reinició en 5 s) y tras un reinicio completo del servidor.
2. **`/api/salud`** en el servidor (`127.0.0.1:8000`) y desde fuera (`http://66.179.210.78:8000`):
   `"estado":"ok"`, `"datos_disponibles":true`, `"version_app":"0.4.0"` (0.15 s desde fuera).
   `/`, `/validacion` y sus figuras responden 200.
3. **Simulación completa por la API** (frente a Cancún, 2 000 partículas, 120 h): HTTP 200 en
   0.27 s, guardada en `/opt/pms/data/simulations/` (1.3 MB, dueño `pms`) y recuperable por
   `GET /api/simulaciones/<id>`; después se borró. Medición de memoria: tabla de la sección 3.
4. **Pruebas e2e de Playwright contra el VPS: quedaron como revisión manual en el navegador**
   (decisión del 03/11/2026). La suite completa pasa en local y contra Vercel; para correrla contra
   un servidor: `python -m pytest -m e2e --url-base http://<ip-del-servidor>:8000` (crea
   simulaciones en el historial del servidor: bórralas después).
5. **Actualizar y revertir**, con los comandos de las secciones 6 y 7 tal cual: actualizar llevó el
   servidor de `6401852` (v0.4.0) a `c4d0797` (3 commits de documentación y pruebas) con el servicio
   sano; revertir lo regresó a `6401852` con el servicio sano. El servidor quedó en **v0.4.0**
   (`git describe --tags` → `v0.4.0`), activo y habilitado. Ahí se comprobó el ajuste de la
   sección 6: `git rev-parse` como `root` da «detected dubious ownership».

### Notas del servidor de entrega

- **SSH**: OpenSSH en Ubuntu 26.04 penaliza por IP (`PerSourcePenalties`) a quien abre conexiones
  sin autenticarse; los sondeos de puerto bastaron para que el servidor cortara la conexión antes
  del saludo («kex_exchange_identification: Connection reset by peer»). El administrador la
  desactivó. Desde redes móviles el puerto 22 puede estar bloqueado por el operador.
- **No se tocó** nada fuera de PMS: ni SSH, ni firewall, ni paquetes del sistema, ni otros
  servicios o usuarios.
