# Global Video Server

Servidor independiente para crear MP4 con una imagen y narración española. Se usa desde el navegador y no está conectado a Global Training.

## Estado y límites

- API, interfaz web, síntesis Piper y exportación MP4 implementadas.
- El despliegue en Render utiliza el plan gratuito, sin disco persistente. Los trabajos y videos pueden perderse al reiniciar o desplegar: descarga los resultados.
- El motor presentation combina imagen fija y audio; no mueve labios ni cuerpo.
- El adaptador opcional SadTalker no está instalado ni probado en este despliegue. Requiere dependencias y modelos aparte; no garantiza resultados con caricaturas ni anima el cuerpo.
- Máximo aceptado: 30 minutos de audio. Diez minutos requieren una narración de esa duración. La capacidad para trabajos largos debe medirse en el servidor gratuito.

## Despliegue

Dockerfile instala FFmpeg, las dependencias y la voz es_ES-davefx-medium durante la construcción. Inicia uvicorn server:app con un worker y el puerto PORT del proveedor. No necesita scripts/start.sh.

Configurar VIDEO_API_TOKEN como secreto aleatorio de al menos 24 caracteres, VIDEO_DATA=/data y PIPER_MODEL=/models/es_ES-davefx-medium.onnx. Nunca publicar el token ni incluirlo en una URL.

Abrir la interfaz del servidor e introducir el token para consultar capacidades, enviar un guion o audio y descargar el MP4. Verificar primero un clip corto con imagen, voz y duración.

## API

Authorization: Bearer <VIDEO_API_TOKEN> es obligatorio para /api/*.

- GET /health: salud pública.
- GET /api/capabilities: motores disponibles.
- POST /api/jobs: multipart title, script, engine (presentation o sadtalker), image y audio opcionales.
- GET /api/jobs: últimos trabajos.
- GET /api/jobs/{id}: estado y duración.
- GET /api/jobs/{id}/video: MP4 terminado.

Un solo propietario, una instancia y un trabajador. Sin política automática de borrado. Los medios se guardan en almacenamiento efímero /data.

## Modelos opcionales

SadTalker requiere SADTALKER_DIR y SADTALKER_PYTHON; SADTALKER_CPU=1 para CPU. Procesa segmentos de 30 segundos. No viene incluido en esta imagen Docker.

Fuentes: https://github.com/OHF-Voice/piper1-gpl y https://github.com/OpenTalker/SadTalker. Revisar las licencias del software y los modelos para el uso previsto.
