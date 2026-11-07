# Rap Rebuild

Полностью переделанная версия из исходной вокальной записи
`Натуральное звучание C Мажор.m4a`. Исходник не изменён.

## Скачать
GitHub Release: https://github.com/ketchuneziko/-/releases/tag/rap-rebuild-v2

- `rap_master.mp3` — основной мастер, 320 kbps
- `rap_master.wav` — мастер 24-bit/44.1 kHz
- `rap_instrumental.mp3` — минус
- `rap_acapella.mp3` — обработанный вокал
- `rap_stems_flac.zip` — раздельные партии: vocal / drums / 808 bass / music / fx & samples

## Параметры
- Стиль: dark boom-bap / trap hybrid
- Темп: 88 BPM
- Тональность: A minor
- Длительность: ~1:52
- Мастер: около -12 LUFS, true-peak <= -1.2 dB

## Структура
| Секция | Такты | Время |
|---|---:|---:|
| Intro | 0–1 | 0:00–0:05.45 |
| Verse 1 | 2–9 | 0:05.45–0:27.27 |
| Hook 1 | 10–17 | 0:27.27–0:49.09 |
| Verse 2 | 18–25 | 0:49.09–1:10.91 |
| Bridge | 26–29 | 1:10.91–1:21.82 |
| Break / scratches | 30 | 1:21.82–1:24.55 |
| Pause | 31 | 1:24.55–1:27.27 |
| Final hook | 32–37 | 1:27.27–1:43.64 |
| Outro | 38–39 | 1:43.64–1:49.09 |
| Tail | — | до 1:52.09 |

## Вокал
- фразы поставлены по сетке, умеренный time-stretch через Rubber Band
- лёгкая коррекция высоты по медиане фразы
- high-pass / low-pass, EQ, de-esser, компрессия, лимитирование
- дабл-треки и ad-lib tails на хуках
- короткая room-реверберация и delay, вокал выведен вперёд

## Бит и сэмплы
- барабаны: SR16 free pack (MIT) + синтезированные kick/snare/hats
- 808-бас с glide
- тёмные piano/bell/pad партии
- вокальные чопы и скретчи из исходного голоса
- riser / impact / downlifter / vinyl-air текстура
- пауза перед финальным дропом

## Повторный рендер
```bash
pip install numpy scipy soundfile imageio-ffmpeg praat-parselmouth
python3 song/make_rap.py
```

## Лицензия сэмплов
SR16 drum samples: MIT, Alonso Varas. Текст лицензии: `samples/SR16/LICENSE.txt`.
