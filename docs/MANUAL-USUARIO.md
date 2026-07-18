# Manual de Usuario — Orbika 🚗🔧

**Para:** el equipo del negocio · **Nivel:** sin conocimientos técnicos · Versión 2026-07-17

Orbika es tu **consola de cotizaciones de repuestos**: recibe los correos de SURA, encuentra los repuestos en tus proveedores y en internet, y te los muestra ordenados para que cotices rápido.

---

## Parte 1 — Instalación (una sola vez)

1. **Descarga** el archivo **`Orbika-Setup.exe`** que te enviamos.
2. **Doble clic** para instalarlo.
3. Si Windows muestra un aviso azul *"Windows protegió tu PC / editor desconocido"*:
   - Clic en **"Más información"** → botón **"Ejecutar de todas formas"**. (Es seguro; es nuestro instalador.)
4. Acepta el permiso de administrador si lo pide.
5. Espera unos segundos. El instalador hace todo solo:
   - Instala la conexión segura (Tailscale).
   - Crea el ícono **"Orbika"** en el **Escritorio** y el **Menú Inicio**.
6. ✅ Listo. No hay que configurar nada más.

> **Importante:** el PC debe tener **internet** durante la instalación (para conectarse a la red segura la primera vez).

---

## Parte 2 — Abrir Orbika

- Haz **doble clic en el ícono "Orbika"** (escritorio o menú inicio).
- Se abre como una **aplicación** (a pantalla, sin barra de navegador).
- Si alguna vez se ve desactualizado, dentro de la ventana presiona **Ctrl + Shift + R** (recarga).

---

## Parte 3 — Cómo usar la consola

### La bandeja (columna izquierda)
Lista de cotizaciones **ordenadas por urgencia**, con un semáforo:
- 🟢 **Verde** = lista, con proveedores encontrados.
- 🟡 **Amarillo** = parcial, revisar.
- 🔴 **Rojo** = vencida o sin repuestos.

Arriba hay 3 pestañas: **Cotizables · Todas · Vencidas**. Y un buscador (por placa, aseguradora o aviso).
Cada cotización tiene una **casilla** para marcarla (para acciones en grupo, ver más abajo).

### El detalle (parte derecha)
Al hacer clic en una cotización ves:
- **Datos del vehículo** arriba (placa, marca, versión, año, aseguradora).
- **Repuestos a cotizar**, y por cada uno las **opciones encontradas** en tarjetas:
  - **"◇ Mejor match · IA"** (violeta) = la mejor opción de tu catálogo, elegida por la IA.
  - **"🌐 Web"** (azul) = opción encontrada en internet (ej. MercadoLibre).
  - **"✓ Ref. exacta"** = la referencia coincide exactamente.
  - Una **barra de compatibilidad** (%) y el botón **"Ver producto"** (abre el enlace).
- Un chip **"🌐 N de internet"** junto al repuesto te dice cuántas opciones web tiene.

### Los botones (arriba a la derecha)
- 🔄 **Actualizar** — recarga la bandeja.
- ⚙️ **Operación** — acciones:
  - *Recalcular matching* / *Revisión con IA* — sobre **todas** las cotizaciones.
  - *Matching de selección* / *Revisión IA de selección* — solo sobre las que **marcaste** con la casilla.
- 📊 **Actividad** — muestra en palabras simples qué está haciendo el sistema (correos nuevos, búsquedas, revisiones).
- 🌓 **Tema** — claro / oscuro.

---

## Parte 4 — Preguntas frecuentes

**¿Tengo que dejar algo prendido?**
El sistema corre en el portátil del negocio. Mientras ese portátil esté encendido y con internet, todo funciona solo (revisa los correos cada pocos minutos).

**No me abre Orbika / sale en blanco.**
- Revisa que el **portátil del negocio esté encendido** y con internet.
- Cierra y vuelve a abrir el ícono. Si sigue, presiona **Ctrl+Shift+R** dentro de la ventana.

**Una cotización no muestra opciones de internet.**
- Márcala con la casilla → botón **Operación → "Revisión IA de selección"**. En un momento aparecen.

**¿Los precios son en vivo?**
Por ahora Orbika muestra el **producto, el proveedor y el enlace** (con "Ver producto" ves el precio en el sitio). El precio automático dentro de Orbika es una mejora futura.

**¿A quién llamo si algo falla?**
A tu contacto de soporte (la agencia). Ellos pueden entrar de forma remota y arreglarlo sin ir al local.
