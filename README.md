# Global Video Server

Servidor independiente para producir MP4 con audio. Preparado para alojarse online en un contenedor; no es necesario instalar programas en el equipo del usuario final.

## Estado real

- Código de API, interfaz web y exportación MP4 implementados.
- Voz neural local con Piper, descargada al arrancar el servicio.
- Motor `presentation`: imagen y narración. No anima labios ni cuerpo.
- Adaptador opcional `sadtalker`: animación facial por segmentos de 30 segundos y unión del resultado. No anima el cuerpo completo. Requiere instalar sus dependencias y pesos en un entorno separado. No se ha probado ese motor ni la detección de rostro de este personaje.
- Máximo de audio: 30 minutos. Un video de 10 minutos requiere un guion/audio de esa duración; no se rellena con repeticiones.
- Todavía no hay servidor publicado. El alojamiento se configura tras conectar la cuenta del proveedor. El servicio puede generar cargos de procesamiento, disco y transferencia.

## Alojamiento online

El proyecto contiene Dockerfile y render.yaml para un servicio de contenedor con disco persistente. El arranque descarga `es_ES-davefx-medium` y sirve la interfaz y la API por el puerto que asigne el proveedor. Verificar la disponibilidad y licencia de la voz/modelo antes de uso comercial.

1. Conectar el proveedor de alojamiento y seleccionar una cuenta/proyecto.
2. Guardar este código en un repositorio del usuario y enlazarlo al servicio Docker.
3. Crear el disco persistente montado en `/data`; confirmar el plan y precio.
4. Guardar un secreto aleatorio `VIDEO_API_TOKEN` de al menos 24 caracteres. Nunca incluirlo en el código público ni en la URL.
5. Ejecutar `sh scripts/start.sh` como comando de inicio. Solo un worker y una instancia, porque la cola utiliza SQLite y un trabajador local.
6. Verificar `/health`, abrir la interfaz y consultar capacidades con el token.
7. Generar un clip breve con audio y verificar imagen, audio y duración antes de un video largo.
8. Conectar el frontend de Global Video Studio al servidor mediante HTTPS con autorización. Esta conexión aún no está incorporada al frontend existente. No se ha conectado Global Training.

El servicio no debe desplegarse como función breve o como sitio estático. La animación facial pesada requiere CPU/memoria suficientes o una máquina GPU; se debe medir el consumo con una muestra antes de escalar.

## API

`Authorization: Bearer <VIDEO_API_TOKEN>` es obligatorio salvo en `/`, `/avatar`, `/health` y la documentación de API.

- GET `/api/capabilities`: motores configurados.
- POST `/api/jobs`: multipart `title`, `script`, `engine` (`presentation` o `sadtalker`), `image` opcional y `audio` opcional. Si se aporta audio, sustituye la síntesis.
- GET `/api/jobs`: últimos 30 trabajos.
- GET `/api/jobs/{id}`: estado, progreso y duración real.
- GET `/api/jobs/{id}/video`: descargar MP4 terminado.

Los trabajos y medios permanecen en `/data`. Los trabajos interrumpidos se marcan fallidos al reiniciar; los pendientes se conservan. No hay política automática de borrado ni servicio multiusuario: es un servidor privado de un solo propietario. No reutilizar este token para clientes diferentes.

## SadTalker opcional

Instalar desde el repositorio oficial y seguir sus instrucciones para entorno y modelos. Configurar `SADTALKER_DIR` y `SADTALKER_PYTHON` con rutas del servidor; `SADTALKER_CPU=1` para CPU o `0` para GPU compatible. El adaptador utiliza `inference.py --preprocess full --still --size 256`. El entorno Docker base no incluye este modelo. No promete movimientos corporales ni un resultado natural garantizado en caricaturas.

## Fuentes técnicas

- https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/CLI.md
- https://github.com/OpenTalker/SadTalker
- https://github.com/OpenTalker/SadTalker/blob/main/inference.py

Revisar las licencias de software y los modelos para el uso previsto.
