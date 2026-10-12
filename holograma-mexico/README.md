# Holograma México · Feria internacional

Clips of Mexican culture and landmarks for a spinning LED hologram fan, made with the [Higgsfield API](https://docs.higgsfield.ai).

Each scene is made in two steps:

1. **Image.** A still of the subject on pure black, from Qwen Image 3, 1536×1536.
2. **Video.** Kling 3.0 Turbo animates that still into an 8-second 1080p clip, with a turntable turn, wings, a twirl and so on.

Black pixels leave the fan's LEDs off, so the subject appears to float in the air.

## Scenes (playlist order)

| # | id | Scene |
|---|----|-------|
| 1 | `papel-picado` | ¡Bienvenidos! Papel picado fluttering |
| 2 | `piedra-del-sol` | Aztec Sun Stone, turning like a wheel |
| 3 | `chichen-itza` | El Castillo with the equinox serpent of light |
| 4 | `teotihuacan` | Pyramid of the Sun |
| 5 | `cabeza-olmeca` | Olmec colossal head |
| 6 | `aguila-nopal` | Eagle on the nopal (founding of Tenochtitlan) |
| 7 | `bellas-artes` | Palacio de Bellas Artes |
| 8 | `angel-independencia` | Ángel de la Independencia |
| 9 | `mariposas-monarca` | Monarch butterflies spiraling |
| 10 | `ajolote` | Axolotl |
| 11 | `voladores` | Voladores de Papantla |
| 12 | `folklorico` | Ballet Folklórico skirt twirl |
| 13 | `alebrije` | Alebrije |
| 14 | `mascara-lucha` | Lucha libre mask |
| 15 | `sabores` | Corn, cacao, chile, avocado, tomato and vanilla orbiting |
| 16 | `pinata` | Star piñata |
| 17 | `catrina` | La Catrina with falling marigold petals |

The prompts are in `scenes.json`. The shared style rules (`image_style`, `video_style`) enforce the pure-black, centered look. You can also paste a scene's prompts into the Higgsfield web app by hand: use `subject` + `image_style` for the image, then `motion` + `video_style` for the video.

## Setup

1. Create an API key at [console.higgsfield.ai](https://console.higgsfield.ai) and add API credits there. The API balance is separate from a higgsfield.ai web subscription.
2. Export the key. Don't commit it.

   ```bash
   export HF_API_KEY_ID=...
   export HF_API_KEY_SECRET=...
   ```

3. You need Python 3.8+ and `ffmpeg`. No pip packages are required.

## Making the clips

```bash
python3 generate.py estimate            # prices one image + one video (free)
python3 generate.py image ajolote       # -> out/images/ajolote-1.png
python3 generate.py image ajolote --extra "make the gills more coral red"   # attempt 2
python3 generate.py select ajolote 1    # go back to attempt 1
python3 generate.py video ajolote       # -> out/videos/ajolote-1.mp4
python3 generate.py frames ajolote      # 2x2 frame sheet to check the motion
python3 generate.py fan                 # out/fan/NN-scene.mp4 for every finished scene
python3 generate.py loop                # out/mexico_loop.mp4, everything in order
python3 generate.py sheet               # out/contact_sheet.png of all chosen images
python3 generate.py status
```

- **Costs (October 2026 estimates):** about $0.08 per image and $0.95 per 8 s 1080p video, so one pass over all 17 scenes is about $17.50.
- **Budget cap:** the script logs every charge in `out/spend.jsonl` and refuses to go past `HF_BUDGET_USD` (default $30).
- **Failures:** failed or moderated requests aren't charged.
- **Download promptly:** Higgsfield keeps outputs for at least 7 days. Everything is downloaded into `out/` right away, and `out/` is git-ignored.

### What `fan` does

- Crops each clip square and scales it to `--size` (default 1080).
- Crushes near-black to true black, so faint grey haze doesn't light the LEDs.
- Masks everything outside the fan's circle.
- Adds short fades so the clips chain smoothly in a playlist.

If your fan's app expects a specific resolution (for example 720 or 1024), use `--size`.

## At the fair

- Run it in a dim spot. Bright room light washes out the hologram.
- Mount the fan high or behind a clear guard. The blades spin fast.
- Add bilingual titles in the fan's app if it supports text. The clips have no text on purpose, because AI video garbles lettering.
