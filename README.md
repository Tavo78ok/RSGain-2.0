## RSGain GUI 2.0

<div align="center">

### Interfaz gráfica GTK4 + libadwaita para [rsgain](https://github.com/complexlogic/rsgain)

Normaliza el volumen de tu biblioteca musical con **ReplayGain 2.0**,
integrada de forma nativa en el escritorio GNOME.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)](https://python.org)
[![GTK](https://img.shields.io/badge/GTK-4.0-4a90d9?style=flat-square)](https://gtk.org)
[![libadwaita](https://img.shields.io/badge/libadwaita-1.4%2B-f66151?style=flat-square)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey?style=flat-square)](https://kernel.org)

</div>

---

## Características

| | |
|---|---|
| 📁 **Modo Easy** | `rsgain easy` — detecta álbumes automáticamente por carpeta |
| 🎵 **Modo Track** | `rsgain custom` — analiza y escribe ganancia pista a pista |
| 🎚️ **Presets** | EBU R128 (−23 LUFS) · rsgain (−18) · Streaming (−14) |
| 📊 **True Peak** | Límite configurable en dBTP |
| 🔇 **Anti-clipping** | Prevención de clipping automática |
| 🔍 **Modo análisis** | Escanea sin modificar los archivos |
| 🖱️ **Drag & drop** | Arrastra archivos y carpetas directamente a la ventana |
| 🌗 **Tema** | Claro y oscuro automático según el sistema |
| 🔔 **Notificaciones** | Toast notifications nativas al terminar |
| 📋 **Registro** | Log en tiempo real con colores por nivel |

**Formatos soportados:**
`MP3` `FLAC` `OGG` `OPUS` `M4A` `AAC` `WV` `APE` `MP4` `MPC` `WAV` `AIFF`

---

## Instalación

### Dependencias

RSGain GUI requiere **rsgain** y las bibliotecas GTK4 del sistema.

```bash
# Ubuntu / Debian
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 rsgain

# Arch Linux
sudo pacman -S python-gobject gtk4 libadwaita rsgain

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita rsgain
```

> ¿rsgain no está en los repos de tu distro?
> Descarga el binario desde [complexlogic/rsgain/releases](https://github.com/complexlogic/rsgain/releases).

---

### Método 1 — Script automático *(recomendado)*

Detecta tu distribución e instala todo de una vez:

```bash
git clone https://github.com/Tavo78ok/rsgain-gui.git
cd rsgain-gui
bash install.sh
```

Para desinstalar:

```bash
bash install.sh uninstall
```

---

### Método 2 — Paquete .deb *(Debian / Ubuntu)*

Descarga el `.deb` de la página de [Releases](https://github.com/Tavo78ok/rsgain-gui/releases):

```bash
sudo apt install ./rsgain-gui_1.0.0_all.deb
```

---

### Método 3 — pip

```bash
pip install --user rsgain-gui
rsgain-gui
```

> **Nota:** PyGObject no se instala vía pip; las dependencias del sistema
> indicadas arriba son necesarias de todas formas.

---

### Método 4 — Sin instalar

```bash
git clone https://github.com/TU_USUARIO/rsgain-gui.git
cd rsgain-gui
python3 -m rsgain_gui
```

---

## Uso

### Desde el menú de aplicaciones

Busca **RSGain** en el lanzador de GNOME, XFCE o tu entorno de escritorio.

### Desde la terminal

```bash
rsgain-gui
```

### Flujo básico

1. **Añade archivos o carpetas** — arrastra a la ventana o usa los botones del header  
2. **Configura** — elige el modo, volumen objetivo y opciones en el panel *Ajustes*  
3. **Procesa** — pulsa **Procesar**; el log muestra el progreso en tiempo real  
4. **Resultado** — cada archivo muestra ✓ o ✗ y aparece un toast de confirmación

---

## Estructura del proyecto

```
rsgain-gui/
├── rsgain_gui/
│   ├── __init__.py        ← versión y metadatos del paquete
│   └── __main__.py        ← aplicación principal (GTK4 + libadwaita)
├── data/
│   ├── rsgain-gui.svg     ← icono de la aplicación
│   └── rsgain-gui.desktop ← entrada del menú de escritorio
├── debian/
│   ├── control            ← metadatos del paquete .deb
│   ├── changelog          ← historial en formato Debian
│   ├── copyright          ← licencia en formato DEP-5
│   ├── install            ← mapa de archivos a instalar
│   ├── postinst           ← script post-instalación
│   ├── prerm              ← script pre-desinstalación
│   └── postrm             ← script post-desinstalación
├── scripts/
│   └── build_deb.sh       ← construye el .deb desde el repositorio
├── .github/workflows/
│   └── release.yml        ← publica el .deb al crear un tag de versión
├── install.sh             ← instalador multi-distribución
├── pyproject.toml         ← configuración del paquete pip
├── CHANGELOG.md
├── LICENSE                ← MIT
└── README.md
```

---

## Desarrollo

```bash
git clone https://github.com/TU_USUARIO/rsgain-gui.git
cd rsgain-gui

# Instalar en modo editable
pip install -e .

# Ejecutar directamente
python3 -m rsgain_gui
```

### Construir el .deb manualmente

```bash
bash scripts/build_deb.sh
# → dist/rsgain-gui_1.0.0_all.deb
```

---

## Requisitos del sistema

| Requisito | Versión mínima |
|---|---|
| Python | 3.10 |
| PyGObject | 3.42 |
| GTK | 4.0 |
| libadwaita | 1.4 |
| rsgain | cualquiera |

---

## Contribuir

Los pull requests son bienvenidos. Para cambios importantes, abre primero un
[issue](https://github.com/Tavo78ok/rsgain-gui/issues) para discutir el cambio.

---

## Créditos

- **[rsgain](https://github.com/complexlogic/rsgain)** por complexlogic — motor de normalización ReplayGain 2.0
- **[libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/)** — widgets GNOME nativos
- **[GNOME HIG](https://developer.gnome.org/hig/)** — guías de diseño de interfaz

## Licencia

[MIT](LICENSE) © 2026 RSGain GUI Contributors


<img width="1440" height="900" alt="Captura de pantalla_2026-03-19_04-05-43" src="https://github.com/user-attachments/assets/45312e56-2bb2-40b7-a7d9-800f55a9d9e6" />
