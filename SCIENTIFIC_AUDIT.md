# Auditoría científica del TFG

Revisión estática del código en `20ddfed`. Se revisaron el lector y motor en
`tobii_tracker.py`, las alertas de `server.js` y `public/index.html`, y
el análisis histórico en `procesar_datos.py` y `app.py`. Las fórmulas
siguientes documentan el comportamiento del TFG.

## Referencias, cálculo y normalización

El cálculo comienza a las 1.500 entradas, usa hasta 3.000 y se actualiza
como máximo una vez por segundo. Supone 50 Hz (dt = 0,02 s) incluso cuando
las entradas no llegan a ese ritmo. C(x) recorta x al intervalo [0, 1].

| Variable | Valor bruto | Normalización y referencias del código |
| --- | --- | --- |
| PDR | Máximo de media basal menos media pupilar actual y cero | C(PDR/0,5 mm). Basal individual fijada con la primera ventana que contiene pupilas válidas. |
| PDV | Desviación estándar poblacional de las pupilas de la ventana | C(PDV/0,20 mm). |
| BR | N.º de inicios detectados × 60/(N × dt) | 0 entre 12 y 20/min, inclusive. Fuera de ese intervalo, C(\|BR−16\|/10). |
| BD | Media de (índice final − inicial) × dt | C((BD−0,15)/0,20). Referencias de 0,15 y 0,35 s. |
| PERCLOS | Fracción de entradas marcadas como parpadeo | C(fracción/0,20). El payload envía una fracción con etiqueta de porcentaje. |
| FD | Tiempo de intervalos a ≤30 °/s dividido por el número de transiciones de alta a baja velocidad, con mínimo de un episodio | C((FD−0,2)/0,3). Referencias de 0,2 y 0,5 s. |
| GE | Entropía de Shannon en bits, histograma 10×10 de mirada en [0,1]² | C((3−GE)/3). |
| SV | Media de las velocidades >30 °/s | C((70−SV)/40) si hay velocidades elegibles. La escala se satura a 30 °/s y llega a cero a 70 °/s. |

El índice es la media aritmética de las ocho puntuaciones, con umbrales
0,20 y 0,50 para las alertas. El código no aporta medias poblacionales
estimadas, calibración de esos cortes ni referencias que justifiquen los
pesos. El 16/min es el centro de una regla implementada. La pupila usa
preferentemente el ojo derecho y el izquierdo como sustituto.

## Detección y ausencias

- Si faltan coordenadas, son negativas o no hay pupila positiva, el lector
  marca parpadeo. Cada espera de cola de 120 ms también genera una entrada
  artificial marcada como parpadeo. Un error de parseo se descarta sin
  diagnóstico. El bucle procesa las entradas según llegan, sin reloj de
  muestreo fijo, y el lector descarta el timestamp original.
- El conteo por transiciones no reconoce una ventana totalmente marcada
  como parpadeo. Si la ventana empieza y termina en pérdida, puede emparejar
  un inicio con un fin anterior y producir duraciones negativas. Tampoco
  contempla duración mínima, evidencia palpebral o censura de episodios.
  La fracción de ausencia no mide el porcentaje de cierre del párpado.
- La velocidad usa distancia euclídea en coordenadas normalizadas × 60°
  dividida por dt. No hay transformación angular calibrada ni corrección
  de geometría. Al excluir entradas inválidas antes de calcular diferencias,
  une puntos separados por lagunas como si fueran consecutivos. Todo tramo
  bajo el corte puede contribuir a FD sin duración mínima ni control de
  dispersión, incluidos movimientos lentos.
- Las métricas sin observaciones elegibles suelen quedar a cero. Esto
  confunde ausencia de evidencia con una contribución baja al índice,
  mientras las ausencias penalizan BR/BD/PERCLOS. Las coordenadas por encima
  de 1 pueden entrar en velocidad pero quedan fuera del histograma.
- El histórico promedia pupilas disponibles por fila y resume por participante
  y juego. Pandas omite NaN en medias y desviaciones, y la suma absoluta del
  giroscopio puede dar cero con todos sus ejes ausentes. El promedio no
  ponderado de NASA incluye rendimiento invertido (11 − valor) y puede
  calcularse con ítems ausentes. La unión izquierda conserva sesiones sin
  cuestionario. Estas agregaciones no calibran el motor en directo.

## Validez e implicaciones

La luminancia, la distancia al estímulo, los movimientos de cabeza, el
contenido del juego y la calibración pueden modificar estas señales. La
carga subjetiva NASA-TLX no establece por sí sola un criterio de fatiga.
Harían falta referencias independientes, anotaciones de parpadeos y
fijaciones, control de factores de confusión y evaluación con participantes
y sesiones fuera del ajuste antes de interpretar los indicadores. El
monitor nuevo muestra telemetría y calidad operativa. Las muestras inválidas
y las discontinuidades se registran como observaciones de calidad, con
causa sin determinar.
