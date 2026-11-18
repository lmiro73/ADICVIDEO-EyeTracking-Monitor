# ADICVIDEO – Real-Time Eye Tracking Monitor

## Instalación en Windows 11

1. Instala Python 3.10 o posterior y abre PowerShell en la carpeta que contiene
   `monitor`. Comprueba la instalación con `py -3 --version`.
2. Para LIVE, instala una versión reciente de FFmpeg y añade su carpeta `bin`
   al PATH de usuario. Abre PowerShell de nuevo y ejecuta `ffmpeg -version`
   y `ffmpeg -hide_banner -h demuxer=rtsp`. El demultiplexor debe admitir
   `-rtsp_transport` y `-timeout`.
3. Inicia DEMO y abre [el dashboard local](http://127.0.0.1:8010) en Edge o
   Chrome actualizado. La aplicación nueva usa la biblioteca estándar de
   Python. Puede ejecutarse sin instalar los paquetes del TFG.

```powershell
py -3 -m monitor --mode demo
```

Detén el servidor con Ctrl+C para cambiar de modo. Si el puerto está
ocupado, usa `--port 8011` y ajusta la dirección del navegador. El
servidor escucha por defecto únicamente en la interfaz local.

## LIVE · Tobii por Wi-Fi

Conecta el portátil a la red Wi-Fi de la unidad Tobii Pro Glasses 3.
Confirma la IP de la unidad y comprueba que Windows puede alcanzar el
puerto RTSP. Sustituye la dirección de ejemplo si la unidad usa otra.

```powershell
Test-NetConnection 192.168.75.51 -Port 8554
py -3 -m monitor --mode live --rtsp rtsp://192.168.75.51:8554/live/all
```

La ruta `/live/all`, el transporte TCP y la extracción del stream `0:3`
mediante FFmpeg con `-c copy -f data` conservan el mecanismo del TFG.
Si el firmware anuncia el canal de datos en otro índice, inspecciona los
streams con el siguiente comando y cambia `--stream 0:3` al índice
correspondiente.

```powershell
ffprobe -hide_banner -rtsp_transport tcp -timeout 5000000 -show_streams rtsp://192.168.75.51:8554/live/all
```

La interfaz indica recepción cuando llegan muestras interpretables.
Después de 2 s sin muestras indica silencio, y reintenta tras el cierre
de FFmpeg. La extracción se verificó con el contrato de argumentos y
telemetría simulada. Quedan por verificar la negociación RTSP, el
firmware, la señal física y los tiempos con el dispositivo de Lisboa.

## REPLAY · Registros locales

```powershell
py -3 -m monitor --mode replay --file "C:\Registros\captura.jsonl" --time-unit s
py -3 -m monitor --mode replay --file "C:\Registros\captura.csv" --time-unit ms
```

Admite mensajes JSON por línea, también comprimidos en gzip, y CSV de
muestras con columnas `timestamp,gaze2d_x,gaze2d_y,pupil_left,pupil_right`.
Las otras columnas del CSV se ignoran. Un CSV agregado por sesión carece
de la secuencia temporal requerida. La unidad de `timestamp` se elige
con `--time-unit s|ms|us` y debe comprobarse con el formato de origen.
La reproducción empieza inmediatamente, a velocidad 1× en orden de
archivo, incluidos los intervalos sin muestras. Reinicia el proceso para
volver al principio.

Ejemplo de formato con dos mensajes sintéticos.

```json
{"timestamp":0.00,"type":"gaze","data":{"gaze2d":[0.38,0.62],"eyeleft":{"pupildiameter":3.5},"eyeright":{"pupildiameter":3.7}}}
{"timestamp":0.02,"type":"event","data":{"label":"Inicio de estímulo"}}
```

También se admite el objeto plano de mirada del lector TFG. La mirada
puede estar ausente y los campos de pupila son independientes.
REPLAY requiere timestamps numéricos para reproducir los mensajes
reconocidos en el tiempo previsto. Guarda los registros fuera del
repositorio. El monitor mantiene una ventana rodante en memoria y los
marcadores de operador se pierden al cerrar el proceso.

## Lectura de la interfaz

- **Señales medidas.** Diámetros pupilares positivos por ojo en mm y
  mirada 2D en coordenadas normalizadas. En DEMO son valores sintéticos.
- **Frecuencia observada.** Número de intervalos entre muestras dividido
  por la suma de sus duraciones en la ventana seleccionada. Incluye los
  intervalos sin muestras dentro del mismo segmento y excluye los cambios
  de reloj o de conexión. Con reloj de recepción puede reflejar el
  agrupamiento de los datos por la red o FFmpeg.
- **Calidad de señal.** El porcentaje usa como denominador las muestras
  de mirada recibidas. Una mirada válida tiene dos coordenadas finitas
  en [0,1] y carece de una marca explícita `valid:false`. La pupila
  ausente se indica por ojo y por separado. Los mensajes que faltan
  aparecen como discontinuidades sin completar la serie.
- **Relojes.** LIVE usa el campo numérico `timestamp` (segundos) si
  existe, o el reloj de recepción UTC del portátil. REPLAY usa el tiempo
  y unidad del registro. DEMO usa tiempo sintético. El eje horizontal es
  relativo a la última muestra. Al cambiar de reloj, reiniciar la fuente
  o reconectar, se abre un segmento con referencia de recepción monótona.
  Un salto superior a 150 ms es una marca operativa de discontinuidad.
- **Eventos.** Los eventos de fuente muestran su timestamp original
  convertido a segundos. Los marcadores manuales muestran el timestamp
  UTC del servidor y se sitúan en el tiempo de la última muestra
  disponible. Su posición no implica sincronización de precisión con un
  estímulo externo.
- **Interpretación.** La relación entre estas señales y la fatiga
  requiere validación específica para ADICVIDEO.

## Pruebas

```powershell
py -3 -m unittest discover -s tests -v
```

Las pruebas crean entradas sintéticas temporales. El código original
del TFG y sus créditos de Git se mantienen. El manifiesto original
declara ISC y se conserva. El checkout de partida carece de un archivo
de licencia propio.
