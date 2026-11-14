# Despliegue de PMS en un VPS Linux

Guía para instalar PMS en un servidor Linux propio (por ejemplo, el de SEMAR). No contiene
credenciales: donde haga falta un usuario se escribe `<usuario>`.

> **Estado al 14/11/2026:** PMS **v0.5.1** en dos servidores, el de entrega
> (<http://66.179.210.78:8000>) y uno alternativo (<http://74.208.218.146:8443>). Ver
> [Servidores con PMS](#servidores-con-pms-14112026).
>
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

Solo si faltan Git o `venv` (**no** hace falta actualizar el sistema). En el 66.179.210.78 ya venían; en el
74.208.218.146 faltaba `ensurepip` y se instaló `python3-venv` (antes, `apt-get install -s` confirmó que
solo agregaba 4 paquetes y no actualizaba el Python del sistema):

```bash
sudo apt install -y git python3-venv
```

Los comandos usan `sudo`; si entras como `root`, quítalo (en el servidor de entrega se
trabajó como `root` por SSH con llave: `ssh -i ~/.ssh/<llave> <usuario>@<ip-del-servidor>`).

## 1. Usuario de servicio y clon en /opt/pms, fijo en una versión

```bash
sudo useradd --system --create-home --home-dir /var/lib/pms --shell /usr/sbin/nologin pms
# Si el servidor tiene contenedores (Docker), elige un uid que no use ningún proceso: con
# --system, useradd suele dar el 999, el mismo que usan Postgres y MySQL dentro de sus imágenes.
# Así se hizo en el 74.208.218.146: groupadd --system --gid 980 pms; useradd --system --uid 980 --gid 980 …
sudo git clone https://github.com/renecano/sargazo_prototipo.git /opt/pms
cd /opt/pms
sudo git checkout -B main v0.5.1                 # Ajuste: fija la versión entregada
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

## Servidores con PMS (14/11/2026)

| | Servidor de entrega | Servidor alternativo (respaldo) |
|---|---|---|
| URL | **<http://66.179.210.78:8000>** | **<http://74.208.218.146:8443>** |
| Versión | v0.5.1 (`09f02a7`, modelo `pms-browniano-0.4.0`) | v0.5.1 (`09f02a7`) |
| Servicio | `pms`, usuario `pms` (uid 999), `MemoryMax=450M`, `MemorySwapMax=0` | `pms`, usuario `pms` (uid y gid 980), `MemoryMax=450M`, `MemorySwapMax=0` |
| Puerto | 8000 | 8443: el firewall del proveedor filtra el 8010 y casi todos los demás; el 8000 es de la app de otro equipo |
| Pico de memoria, simulación máxima | 143 MB (al sistema le quedan 44 MB) | 135 MB (al sistema le quedan 553 MB) |
| Respaldo previo | `/root/respaldo_pms_20261114` (unidad, LEEME, commit anterior `6401852`, `pip freeze`, 30 simulaciones) | `/root/respaldo_pms_20261114` (instalación nueva; unidad con el 8010 y con el 8443) |
| Cambios fuera de `/opt/pms` | ninguno | `apt install python3-venv` (4 paquetes nuevos, ninguno actualizado: faltaba `ensurepip`) |

**Memoria medida** el 14/11/2026 con la v0.5.1, igual que en la sección 3: servicio recién
reiniciado, interfaz abierta y 5 000 partículas × 120 h (radio 50 km) en 21.00° N, 86.30° O.

| Momento | 66.179.210.78 | 74.208.218.146 |
|---|---|---|
| Arranque | 93 MB | 44 MB |
| Interfaz abierta (validación, campos, costa, localidades) | 98 MB | 86 MB |
| Simulación máxima, endpoint síncrono | 132 MB (0.75 s; registro de 3.3 MB) | 126 MB (0.60 s) |
| Simulación máxima en segundo plano (lo que usa la interfaz) | **143 MB** | **135 MB** |

La v0.5.1 pide unos 25 MB más que la v0.4.0 (116 MB) por la máscara de costa de ~100 m y las
localidades. Cabe con margen en `MemoryMax=450M`; lo que no alcanza en el 66 es la memoria del
servidor completo (abajo). No se repitió la prueba de dos simulaciones a la vez en el 66 para no
provocar una muerte por memoria de procesos ajenos.

### Por qué falló el 66 el 13/11/2026

**No era la versión ni la copia nueva.** El puerto 8000 lo seguía sirviendo `/opt/pms` en la
v0.4.0. Las copias de `/root/sargazo_prototipo` y `/root/equipo4/hidrocarburos/sargazo_prototipo`
son la v0.2.0 de octubre, con un `.venv` hecho en Windows, y no las sirve ningún servicio (no se
tocaron). **La causa es la memoria del servidor completo**: 809 MB de RAM sin swap, con Docker
(XAMPP, que trae Apache y MySQL, y Postgres: ~190 MB), `unattended-upgrades`, `apt` y `fwupd`. Del 6 al
14/11 el kernel mató 65 procesos por falta de memoria; a PMS lo mató 15 veces (7 el 13/11, entre
las 02:18 y las 04:16 UTC), siempre muy por debajo de su límite (pico de 41 a 97 MB): eran muertes
del sistema, no del `MemoryMax`. systemd lo reinició cada vez en 5–10 s, pero mientras tanto la
página no respondía. El disco está al 91 % (839 MB libres).

Se pasó el servicio a la v0.5.1 sin cambiar la unidad ni el venv (el `requirements.txt` de la
v0.5.1 es idéntico al de la v0.4.0 y el venv tenía exactamente esas dependencias). Lo que lo
haría estable no es de PMS y no se tocó: agregar swap (p. ej. 1 GB), quitar contenedores o
servicios que no se usen, o darle más RAM al servidor.

### Comparación (medido el 14/11/2026)

| | 66.179.210.78 | 74.208.218.146 |
|---|---|---|
| Sistema | Ubuntu 26.04.1, Python 3.14.4 | Ubuntu 26.04.1, Python 3.14.4 |
| CPU | 1 vCPU AMD EPYC-Milan | 2 vCPU AMD EPYC-Milan |
| RAM total / disponible en reposo | 809 MB / 57–92 MB | 1 815 MB / 598–651 MB |
| Swap | ninguna | 1 GB, llena (1 015–1 023 MB usados) |
| Disco libre | 839 MB (91 % usado) | 65 GB (16 % usado) |
| Carga (1/5/15 min) | 0.72 / 0.40 / 0.33 | 0.21 / 0.17 / 0.12 |
| Qué más corre | Docker: XAMPP (Apache y MySQL) y Postgres | 8 contenedores (MySQL ×2, Postgres ×2, phpMyAdmin ×4), nginx en 80/443, app de otro equipo en el 8000 |
| Muertes por memoria del 6 al 14/11 | 65 (15 de PMS) | 3 (todas de MySQL en contenedor, el 13/11) |
| Reinicios del servidor | 3/11 y 5/11 | 25/10 y 7/11 |
| `/api/salud` desde la laptop (10 peticiones) | mediana 90 ms (86–280) | mediana 90 ms (88–105) |
| Simulación de 2 000 × 120 h desde la laptop | 0.71 s | 0.76 s |
| Firewall | ufw inactivo; el proveedor deja pasar el 8000 | ufw inactivo; el proveedor solo deja pasar algunos puertos (8000, 8443, 3000…) |

**Riesgos.** En el 66, cualquier pico de memoria de los demás servicios vuelve a tumbar a PMS;
además el usuario `pms` comparte el uid 999 con el Postgres del contenedor (cambiarlo exigiría
detener ese contenedor). En el 74, el servidor es compartido con otros proyectos y con la app
de otro equipo, la swap está llena y el 8443 depende de una regla del proveedor que no
controlamos; no es un puerto con HTTPS aunque el número lo sugiera.

## Guía corta para el dueño del servidor

Esta misma guía está en el servidor, en `/opt/pms/LEEME_SERVIDOR.txt`.

La aplicación ya corre sola como servicio (se llama `pms`) y arranca junto con el servidor. No
hace falta lanzarla a mano.

| Para | Comando |
|---|---|
| Ver el estado | `systemctl status pms` |
| Reiniciarla | `systemctl restart pms` |
| Detenerla | `systemctl stop pms` |
| Ver los logs en vivo | `journalctl -u pms -f` |
| Ver los logs de hoy | `journalctl -u pms --since today` |

**Para correrla a mano**, primero detén el servicio, porque ocupa el puerto 8000, y usa el Python
de PMS:

```bash
systemctl stop pms
cd /opt/pms
sudo -u pms /opt/pms/.venv/bin/python main.py --host 0.0.0.0 --puerto 8000 --no-navegador
```

Usa siempre `/opt/pms/.venv/bin/python`. Nunca uses `python3` del sistema ni instales librerías
con `pip`: el entorno de PMS ya tiene las versiones correctas.

**Para volver a dejarla como servicio**, detén la que corriste a mano con Ctrl+C y arranca el
servicio:

```bash
systemctl start pms
curl -s http://127.0.0.1:8000/api/salud   # debe decir "estado":"ok"
```

## Verificación (14/11/2026, v0.5.1)

En los dos servidores, desde la laptop y por SSH (sin Playwright contra los servidores):

1. **`/api/salud`** en el servidor y desde fuera: `"version_app":"0.5.1"`, `"datos_disponibles":true`;
   `/`, `/validacion` y `/api/costa/tierra.bin` responden 200.
2. **Simulación completa por la API** desde la laptop (frente a Cancún, 2 000 partículas, 120 h):
   HTTP 200 en 0.71 s (66) y 0.76 s (74), guardada en `/opt/pms/data/simulations/` (1.3 MB,
   dueño `pms`), visible en el historial y recuperable por `GET /api/simulaciones/<id>`; después
   se borró.
3. **`systemctl restart pms`**: el servicio volvió solo en 2 s en los dos (activo y habilitado).
4. **App del otro equipo en el 74.208.218.146:8000**: antes y después de instalar PMS respondió
   igual (`/` → 302 a `/web/`, misma página, mismo PID y 0 reinicios).

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
